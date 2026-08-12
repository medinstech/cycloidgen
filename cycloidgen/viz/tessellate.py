"""Cutting a planar face with holes into triangles, the same way everywhere.

A disc's end face is a lobed outline with a bore and six output holes in it; a
housing's is an annulus whose inner boundary follows the ring-pin pockets, with
a bolt circle through it.  Neither is a polygon anything renders directly, so
each has to be cut up, and the two things that decides are whether the result is
*right* and whether it is the *same* everywhere.

This used to be ``vtkContourTriangulator``, which gives up part way on some
inputs and says nothing about it.  The result was checked against the loops it
came from and a face that came up short was tried again with the plane turned -
eleven angles, searched on one machine for the smallest set that cleared every
face this app can draw.  That is the flaw rather than the fix: *which* inputs
defeat the filter is a property of the build, so the same list left the housing
full of holes on VTK 9.3 under Linux and the end cap full of holes on macOS
arm64 at the version it was developed on.  Neither reproduces here, and a magic
number tuned against a failure you cannot reproduce is not a fix.

So the face is cut here, by the textbook method for a polygon with holes:

1. **A sweep from top to bottom** adds diagonals at the two kinds of vertex that
   stop a piece from being *monotone* - the ones where the region splits in two,
   and the ones where two parts of it come back together.  A hole's top vertex
   is a split and its bottom is a merge, which is how holes get joined to the
   rest without a special case for them: after this there are no holes, only
   monotone pieces.
2. **The pieces are traced** out of the loops and the diagonals together, each
   one being the face to the left of an edge nobody has walked yet.
3. **Each piece is triangulated** by the stack walk, which is linear and has no
   decision in it that two machines could take differently.

Nothing is duplicated on the way, and that is the property that matters most.
The other standard method - bridging each hole to the outer loop by a channel of
no width - has to visit both ends of every channel twice, and where two channels
face each other the two sides land on the same pair of points: the face is
covered correctly and the *merged* mesh is folded, which is a hole in the part
by the time the section plane tries to cap it.  This was written the other way
first and that is what it cost.

The triangles come back as indices into the mesh's own vertex array, so a cap
shares its corners with the walls that meet it and there is nothing to merge
afterwards.
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np

__all__ = ["triangulate"]

#: Below this, a cross product is a straight line rather than a corner.  It is
#: twice an area, in mm^2, on a part measured in tens of millimetres.
_EPS = 1e-12


def _signed_area(points: np.ndarray) -> float:
    """Shoelace area, summed elementwise rather than through a dot product.

    ``np.dot`` goes to BLAS, and the order a BLAS sums in is a property of the
    library that was linked.  The point of this module is that every machine
    reaches the same answer.
    """
    x, y = points[:, 0], points[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - y * np.roll(x, -1)))


def _cross(o: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    """Twice the signed area of ``o -> a -> b``; positive is a left turn."""
    return float((a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]))


#: Two points closer than this are the same point.  A nanometre: far below any
#: feature on a gearbox and far above the rounding that produces them.
_SNAP = 1e-9


def _clean(ring: list[int], xy: np.ndarray) -> tuple[list[int], dict[int, list[int]]]:
    """Split a loop into the points the sweep sees and the ones riding on them.

    The housing's bore is drawn as a bore arc and a pocket arc per pin, and the
    two meet at a point each of them computes for itself: the same point to
    fourteen decimal places and not to the fifteenth.  Twenty-two pins leave
    forty-four of these, and to a sweep they are edges of no length, which have
    no left and no right and no meaningful corner - one is enough to send a
    monotone piece somewhere it should not go.

    They cannot simply be dropped either: the wall below the cap has a quad on
    each of them, and a boundary the wall keeps and the cap does not is a hole
    in the part.  So the sweep is run without them and each is stitched back
    afterwards as a triangle of no area, which puts the edge back and covers
    nothing.
    """
    def same(a: int, b: int) -> bool:
        return (abs(xy[a][0] - xy[b][0]) < _SNAP
                and abs(xy[a][1] - xy[b][1]) < _SNAP)

    kept: list[int] = []
    riders: dict[int, list[int]] = {}
    for vertex in ring:
        if kept and same(vertex, kept[-1]):
            riders.setdefault(len(kept) - 1, []).append(vertex)
        else:
            kept.append(vertex)
    # And where the loop closes, which is the junction every bore has and the
    # only one the walk above cannot see: it compares each point with the one
    # before it, and the last point's neighbour is the first.
    while len(kept) > 3 and same(kept[-1], kept[0]):
        dropped = kept.pop()
        riders.setdefault(len(kept) - 1, []).append(dropped)
    return kept, riders


class _Sweep:
    """One face, cut into monotone pieces by a top-to-bottom sweep.

    Vertices are handled in order of decreasing y, ties broken by increasing x.
    That order is the whole of how horizontal edges are dealt with: "above"
    means "earlier in this order" rather than "greater y", and by that
    definition a horizontal edge has an upper end like any other. There is no
    special case for one anywhere below, and there are plenty of them - a
    twelve-sided bolt hole has two.
    """

    def __init__(self, xy: np.ndarray, rings: Sequence[Sequence[int]]) -> None:
        self.xy = xy
        self.next: dict[int, int] = {}
        self.prev: dict[int, int] = {}
        for ring in rings:
            for i, vertex in enumerate(ring):
                self.next[vertex] = ring[(i + 1) % len(ring)]
                self.prev[vertex] = ring[i - 1]
        self.order = sorted(self.next, key=self._key)
        #: The edges crossing the sweep line, left to right, named by their
        #: upper end.  A list rather than a balanced tree: these faces run to a
        #: thousand vertices, and at that size a binary search over a list beats
        #: a tree written in Python.
        self.status: list[int] = []
        #: Per edge, the last vertex that saw it from the inside.
        self.helper: dict[int, int] = {}
        #: Vertices where two parts of the face came together. A diagonal is
        #: owed to one of these the moment anything below can see it, which is
        #: what every handler's first question is.
        self.merged: set[int] = set()
        self.diagonals: list[tuple[int, int]] = []

    # ------------------------------------------------------------- ordering --
    def _key(self, vertex: int) -> tuple[float, float]:
        x, y = self.xy[vertex]
        return (-y, x)

    def _above(self, a: int, b: int) -> bool:
        return self._key(a) < self._key(b)

    def _edge_x(self, edge: int, at: int) -> float:
        """Where the edge starting at ``edge`` crosses the row ``at`` is on."""
        a, b = self.xy[edge], self.xy[self.next[edge]]
        if a[1] == b[1]:
            return float(min(a[0], b[0]))
        y = self.xy[at][1]
        return float(a[0] + (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]))

    # --------------------------------------------------------------- status --
    def _insert(self, edge: int, helper: int) -> None:
        x = self._edge_x(edge, edge)
        low, high = 0, len(self.status)
        while low < high:
            middle = (low + high) // 2
            if self._edge_x(self.status[middle], edge) < x:
                low = middle + 1
            else:
                high = middle
        self.status.insert(low, edge)
        self.helper[edge] = helper

    def _remove(self, edge: int) -> None:
        if edge in self.helper:
            self.status.remove(edge)
            del self.helper[edge]

    def _left_of(self, vertex: int) -> int | None:
        """The status edge immediately to the left of ``vertex``."""
        found = None
        for edge in self.status:
            if self._edge_x(edge, vertex) <= self.xy[vertex][0] + _EPS:
                found = edge
            else:
                break
        return found

    def _owes(self, edge: int | None) -> bool:
        return edge is not None and self.helper.get(edge) in self.merged

    # ------------------------------------------------------------ the sweep --
    def run(self) -> list[tuple[int, int]]:
        """Every diagonal needed to leave nothing but monotone pieces."""
        for vertex in self.order:
            previous, following = self.prev[vertex], self.next[vertex]
            turn = _cross(self.xy[previous], self.xy[vertex], self.xy[following])
            above_previous = self._above(vertex, previous)
            above_following = self._above(vertex, following)

            if above_previous and above_following:
                # Both neighbours are below: the face either starts here or
                # splits in two, and the interior angle is what says which.
                if turn > _EPS:
                    self._insert(vertex, vertex)
                else:
                    self._split(vertex)
            elif not above_previous and not above_following:
                if turn > _EPS:
                    self._end(vertex)
                else:
                    self._merge(vertex)
            else:
                self._regular(vertex, above_following)
        return self.diagonals

    def _split(self, vertex: int) -> None:
        left = self._left_of(vertex)
        if left is not None:
            self.diagonals.append((vertex, self.helper[left]))
            self.helper[left] = vertex
        self._insert(vertex, vertex)

    def _end(self, vertex: int) -> None:
        previous = self.prev[vertex]
        if self._owes(previous):
            self.diagonals.append((vertex, self.helper[previous]))
        self._remove(previous)

    def _merge(self, vertex: int) -> None:
        previous = self.prev[vertex]
        if self._owes(previous):
            self.diagonals.append((vertex, self.helper[previous]))
        self._remove(previous)
        left = self._left_of(vertex)
        if left is not None:
            if self._owes(left):
                self.diagonals.append((vertex, self.helper[left]))
            self.helper[left] = vertex
        self.merged.add(vertex)

    def _regular(self, vertex: int, interior_on_the_right: bool) -> None:
        if interior_on_the_right:
            # The boundary runs downwards through here, so the piece is to the
            # right of it and the edge that arrives is the one that closes.
            previous = self.prev[vertex]
            if self._owes(previous):
                self.diagonals.append((vertex, self.helper[previous]))
            self._remove(previous)
            self._insert(vertex, vertex)
        else:
            left = self._left_of(vertex)
            if left is not None:
                if self._owes(left):
                    self.diagonals.append((vertex, self.helper[left]))
                self.helper[left] = vertex


def _pieces(xy: np.ndarray, rings: Sequence[Sequence[int]],
            diagonals: Sequence[tuple[int, int]]) -> list[list[int]]:
    """Trace the faces bounded by the loops and the diagonals together.

    Each piece is the face to the *left* of a directed edge nobody has walked
    yet, and the walk turns as sharply as it can at every vertex, which is what
    keeps it on the boundary of one piece instead of cutting across it.  The
    outside of the whole face comes out as a walk of its own, wound the other
    way; it is dropped by its sign.
    """
    out: dict[int, list[int]] = {}
    for ring in rings:
        for i, vertex in enumerate(ring):
            out.setdefault(vertex, []).append(ring[(i + 1) % len(ring)])
    for a, b in diagonals:
        out.setdefault(a, []).append(b)
        out.setdefault(b, []).append(a)

    def heading(a: int, b: int) -> float:
        dx, dy = xy[b] - xy[a]
        return float(np.arctan2(dy, dx))

    fan: dict[int, tuple[list[float], list[int]]] = {}
    for vertex, neighbours in out.items():
        neighbours.sort(key=lambda other, v=vertex: heading(v, other))
        fan[vertex] = ([heading(vertex, other) for other in neighbours],
                       neighbours)

    faces: list[list[int]] = []
    unwalked = {(v, w) for v, ws in out.items() for w in ws}
    while unwalked:
        walk: list[int] = []
        edge = min(unwalked)
        while edge in unwalked:
            unwalked.discard(edge)
            walk.append(edge[0])
            here, there = edge
            # Turn as far clockwise as there is room for: of the edges leaving
            # `there`, the one just before the way we came.  Found by angle
            # rather than by looking the way back up, because a loop's edges are
            # one-way and only a diagonal can be walked from either end.
            angles, neighbours = fan[there]
            back = heading(there, here)
            at = np.searchsorted(angles, back)
            edge = (there, neighbours[int(at) - 1])
        if len(walk) >= 3 and _signed_area(xy[walk]) > 0.0:
            faces.append(walk)
    return faces


def _monotone_triangles(xy: np.ndarray,
                        piece: Sequence[int]) -> list[tuple[int, int, int]]:
    """Triangulate one y-monotone piece with the stack walk.

    The vertices are visited in the sweep's order and each one either closes off
    everything on the stack it can see or waits on it.  Linear, and the only
    arithmetic in it is the turn at a corner.
    """
    count = len(piece)
    order = sorted(range(count), key=lambda i: (-xy[piece[i]][1], xy[piece[i]][0]))
    top, bottom = order[0], order[-1]

    # Which side of the piece a vertex is on: from the top, its own order runs
    # down one chain and back up the other.
    left = set()
    walk = top
    while walk != bottom:
        left.add(walk)
        walk = (walk + 1) % count

    triangles: list[tuple[int, int, int]] = []

    def emit(u: int, v: int, w: int) -> None:
        """One triangle, wound the way the piece is.

        Deciding this from the coordinates rather than from which chain the
        vertex came off removes a whole class of sign mistake: the piece is
        counter-clockwise by the time it gets here, so every triangle in it is
        too, and the ones that are not are simply written the other way round.
        """
        a, b, c = piece[u], piece[v], piece[w]
        if _cross(xy[a], xy[b], xy[c]) >= 0.0:
            triangles.append((a, b, c))
        else:
            triangles.append((a, c, b))

    stack = [order[0], order[1]]
    for position, index in enumerate(order[2:-1], start=2):
        if (index in left) != (stack[-1] in left):
            # The other chain: everything waiting is visible from here.
            while len(stack) > 1:
                popped = stack.pop()
                emit(index, popped, stack[-1])
            stack = [order[position - 1], index]
        else:
            # The same chain: take what this vertex can see, which is as far
            # back as the corners keep turning the right way.
            popped = stack.pop()
            while stack:
                # The two on the stack and this vertex, in that order: the
                # triangle is inside the piece when they turn towards the chain
                # this vertex came down.  Left chain, left turn.
                turn = _cross(xy[piece[stack[-1]]], xy[piece[popped]],
                              xy[piece[index]])
                if (turn > _EPS) != (index in left):
                    break
                emit(index, popped, stack[-1])
                popped = stack.pop()
            stack.append(popped)
            stack.append(index)

    last = order[-1]
    while len(stack) > 1:
        popped = stack.pop()
        emit(last, popped, stack[-1])
    return triangles


def triangulate(points: np.ndarray,
                loops: Sequence[Sequence[int]]) -> list[tuple[int, int, int]]:
    """Cut one planar face into triangles, holes and all.

    ``points`` is the mesh's whole vertex array and ``loops`` are indices into
    it: the outer boundary first, then one loop per hole.  The triangles come
    back as indices into that same array.

    Every face here lies in a plane of constant z - they are the caps of prisms,
    and the walls between them are quads that need no cutting - so the work is
    done on x and y, and the winding of the outer loop is carried through to the
    triangles.  That is the difference between a cap whose normal points out of
    the part and one that points into it.
    """
    xy = np.asarray(points, dtype=float)[:, :2]
    rings = [list(map(int, loop)) for loop in loops]

    # Interior on the left of every directed edge: the outer loop
    # counter-clockwise, the holes clockwise.  The face's own winding is
    # remembered and put back at the end rather than imposed here.
    outer_is_ccw = _signed_area(xy[rings[0]]) > 0.0
    if not outer_is_ccw:
        rings[0] = rings[0][::-1]
    rings[1:] = [hole if _signed_area(xy[hole]) < 0.0 else hole[::-1]
                 for hole in rings[1:]]

    cleaned, stitches = [], []
    for ring in rings:
        kept, riders = _clean(ring, xy)
        cleaned.append(kept)
        for at, rides in riders.items():
            # The boundary edge the sweep will draw from `here` to `there` is
            # the one these points sit on; the fan puts them back on it and
            # turns that edge into an interior one, which is what pairs it.
            here, there = kept[at], kept[(at + 1) % len(kept)]
            for rider in rides:
                stitches.append((here, rider, there))
                here = rider

    diagonals = _Sweep(xy, cleaned).run()
    triangles: list[tuple[int, int, int]] = list(stitches)
    for piece in _pieces(xy, cleaned, diagonals):
        triangles.extend(_monotone_triangles(xy, piece))

    triangles = [t for t in triangles if len({*t}) == 3]
    if not outer_is_ccw:
        triangles = [(c, b, a) for a, b, c in triangles]
    return triangles
