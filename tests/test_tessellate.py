"""Cutting a face into triangles: the shapes, not the gearbox.

``tests/test_viz.py`` puts every face of every preset through this and asks the
same three questions of each.  What is here is the awkward cases, written out by
hand so that a failure says which property broke rather than which ratio.

The three questions, everywhere: the triangles cover the face's own area, no
directed edge appears twice - which is a fold - and the unpaired edges are
exactly as many as the loops have sides, which is the boundary being where it
was left.  Those three together are what makes a part watertight once its points
are shared.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from cycloidgen.viz.tessellate import triangulate


def _area(points: np.ndarray, triangles) -> float:
    total = 0.0
    for a, b, c in triangles:
        p, q, r = points[a], points[b], points[c]
        total += 0.5 * ((q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]))
    return total


def _edges(triangles):
    return [e for a, b, c in triangles for e in ((a, b), (b, c), (c, a))]


def _check(points: np.ndarray, loops, area: float):
    """Every property that matters, for one face.  Returns the triangles."""
    triangles = triangulate(points, loops)
    assert _area(points, triangles) == pytest.approx(area, abs=1e-9)

    directed = _edges(triangles)
    assert len(set(directed)) == len(directed), "a directed edge twice is a fold"
    boundary = [e for e in directed if (e[1], e[0]) not in set(directed)]
    assert len(boundary) == sum(len(loop) for loop in loops)

    allowed = {int(v) for loop in loops for v in loop}
    assert {v for t in triangles for v in t} <= allowed
    return triangles


def _circle(cx: float, cy: float, r: float, n: int, clockwise: bool = False):
    step = -1 if clockwise else 1
    return np.array([[cx + r * math.cos(t), cy + r * math.sin(t), 0.0]
                     for t in np.linspace(0, 2 * math.pi, n, endpoint=False)[::step]])


# --------------------------------------------------------------- the shapes --


def test_a_square_with_a_square_hole():
    points = np.array([[0, 0, 0], [4, 0, 0], [4, 4, 0], [0, 4, 0],
                       [1, 1, 0], [1, 3, 0], [3, 3, 0], [3, 1, 0]], float)
    _check(points, [[0, 1, 2, 3], [4, 5, 6, 7]], 16.0 - 4.0)


def test_a_concave_outline_with_no_holes_at_all():
    """An L: the corner at the notch is the one a fan from any vertex gets wrong."""
    points = np.array([[0, 0, 0], [3, 0, 0], [3, 1, 0], [1, 1, 0],
                       [1, 3, 0], [0, 3, 0]], float)
    _check(points, [[0, 1, 2, 3, 4, 5]], 5.0)


def test_the_face_keeps_its_own_winding():
    """A cap's normal is decided by the order its loop was emitted in.

    Both faces of a part are the same outline; what tells the top from the
    bottom is which way round it is written, and a triangulation that imposed
    its own would turn one of them inside out.
    """
    points = np.array([[0, 0, 0], [3, 0, 0], [3, 1, 0], [1, 1, 0],
                       [1, 3, 0], [0, 3, 0]], float)
    forwards = triangulate(points, [[0, 1, 2, 3, 4, 5]])
    backwards = triangulate(points, [[5, 4, 3, 2, 1, 0]])
    assert _area(points, forwards) == pytest.approx(5.0)
    assert _area(points, backwards) == pytest.approx(-5.0)


def test_an_annulus_is_cut_without_a_seam():
    """A hole with no vertex of the outer loop anywhere near it."""
    points = np.vstack([_circle(0, 0, 5, 24), _circle(0, 0, 2, 12, clockwise=True)])
    area = (0.5 * 24 * 25 * math.sin(2 * math.pi / 24)
            - 0.5 * 12 * 4 * math.sin(2 * math.pi / 12))
    _check(points, [list(range(24)), list(range(24, 36))], area)


def test_thirteen_holes_in_a_ring():
    """The case that decided how this is written.

    Bridging each hole to the outer loop by a channel of no width is the other
    standard way to do this, and it cuts every one of these faces correctly -
    but two channels that face each other put a triangle from each side on the
    same pair of points, and the *merged* mesh is folded.  A plate with a ring
    of holes in it is where that happens, and the 59:1 ring-output drive has
    one.
    """
    loops, blocks, at = [list(range(48))], [_circle(0, 0, 10, 48)], 48
    for i in range(13):
        angle = 2 * math.pi * i / 13
        blocks.append(_circle(7 * math.cos(angle), 7 * math.sin(angle), 1, 12,
                              clockwise=True))
        loops.append(list(range(at, at + 12)))
        at += 12
    area = (0.5 * 48 * 100 * math.sin(2 * math.pi / 48)
            - 13 * 0.5 * 12 * math.sin(2 * math.pi / 12))
    _check(np.vstack(blocks), loops, area)


def test_a_hole_touching_the_outer_loop_at_a_row_of_its_own_height():
    """Horizontal edges, which a sweep has to order rather than special-case."""
    points = np.array([[0, 0, 0], [6, 0, 0], [6, 4, 0], [0, 4, 0],
                       [2, 1, 0], [2, 3, 0], [4, 3, 0], [4, 1, 0]], float)
    _check(points, [[0, 1, 2, 3], [4, 5, 6, 7]], 24.0 - 4.0)


# ------------------------------------------------------- degenerate points --


def test_a_loop_that_repeats_a_point_keeps_it_on_the_boundary():
    """What the housing bore does forty-four times.

    The bore is drawn as a bore arc and a pocket arc per pin, and the two meet
    at a point each computes for itself - the same point to fourteen decimal
    places.  To a sweep that is an edge with no length, no left and no right.
    Dropping it is not an option either: the wall below has a quad on it, and a
    boundary the wall keeps and the cap does not is a hole in the part.
    """
    points = np.array([[0, 0, 0], [4, 0, 0], [4, 4, 0],
                       [4, 4, 0], [0, 4, 0]], float)   # a point, twice
    points[3, 0] += 1e-15
    triangles = _check(points, [[0, 1, 2, 3, 4]], 16.0)
    assert any(2 in t and 3 in t for t in triangles), "the repeat lost its edge"


def test_a_loop_that_repeats_its_first_point_last():
    """The same thing where the loop closes, which the walk cannot see."""
    points = np.array([[0, 0, 0], [4, 0, 0], [4, 4, 0], [0, 4, 0],
                       [0, 0, 0]], float)
    points[4, 1] += 1e-15
    _check(points, [[0, 1, 2, 3, 4]], 16.0)


# ------------------------------------------------------------- reproducible --


def test_the_same_face_is_cut_the_same_way_twice():
    """The property the whole module exists for.

    Not a tautology: the version this replaced asked a filter whose failures
    were a property of the build, and the same design came out with holes in it
    on one platform and not on another.
    """
    points = np.vstack([_circle(0, 0, 5, 37), _circle(1, 1, 1.5, 9, clockwise=True)])
    loops = [list(range(37)), list(range(37, 46))]
    assert triangulate(points, loops) == triangulate(points, loops)


def test_a_face_of_three_points_is_one_triangle():
    """Which corner it starts from is nobody's business; the area is."""
    points = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float)
    (triangle,) = triangulate(points, [[0, 1, 2]])
    assert set(triangle) == {0, 1, 2}
    assert _area(points, [triangle]) == pytest.approx(0.5)
