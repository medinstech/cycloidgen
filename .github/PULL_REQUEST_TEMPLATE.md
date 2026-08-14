<!-- Thanks. CONTRIBUTING.md is short and worth the two minutes. -->

## What this changes, and why

<!-- The reason, not the diff. One reason per pull request. -->

## Does it change any computed number?

<!--
  Anything in core/, analysis/ or design/ probably does. If so, say which
  quantity moved, by how much, on what design, and why the new value is the
  right one. A silent change to a number somebody has already built hardware
  against is the worst thing this repository can ship.
-->

- [ ] No computed number changes
- [ ] It does, and it is described above

## How it is verified

<!--
  Numbers here are verified rather than asserted: computed a second way,
  cross-checked against a brute-force version, measured from the manufactured
  geometry rather than assumed from the input. What is the second way of getting
  your answer?
-->

## Checklist

- [ ] `python -m pytest -q` passes
- [ ] `ruff check .` passes
- [ ] Comments explain *why*, and the hand-aligned style of the file is intact
- [ ] If a file was added to an export bundle, it is declared in
      `cycloidgen/export/manifest.py`
- [ ] No change to the brand assets in `cycloidgen/ui/assets/` or the Medinstech
      name (see NOTICE). The app icon there is not brand — change it by
      re-running `tools/make_icon.py`, not by editing a PNG
