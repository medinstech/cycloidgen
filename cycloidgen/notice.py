"""What this tool does not claim, in one place.

Four things say it and they have to say the same thing: the strip along the
bottom of the window, the box that asks before an export is written, the About
dialog, and the ``NOTICE.txt`` that goes into the folder with the parts.  Four
copies of a disclaimer is three chances for one of them to soften.

It is worth being exact about *what* is unverified, because two different things
are:

* **The numbers.** They are first-principles estimates from stated models with
  stated limits.  Nothing in them has been fitted to a measurement - see the
  calibration entry in the roadmap - so a stiffness or an efficiency here is an
  argument, not a datum.
* **The geometry.** The parts come out of the same idealised model. Profiles,
  fits and clearances are computed, not proven: no tolerance stack has been run,
  no part has been made from these files and measured. A STEP file that looks
  finished is the easiest thing here to mistake for a drawing that has been
  checked, which is exactly why the geometry is named as well as the numbers.

The text is plain rather than rich, so that the same string can be a label, a
message box, a file and a line on a terminal.  Whoever shows it decides how it
looks; nobody gets to decide what it says.
"""
from __future__ import annotations

__all__ = ["FULL", "HEADLINE", "SHORT", "file_text"]

#: The two words that have to land even if nothing else is read.
HEADLINE = "Not verified output"

#: One line, for somewhere that has one line: the strip under the window.
SHORT = ("Preliminary sizing and unproven geometry - not a certification. "
         "Validate a prototype before anything load-bearing depends on it.")

#: The whole of it, for a dialog or a file.  Wrapped by whoever displays it.
FULL = (
    "The numbers are preliminary sizing estimates from stated models with "
    "stated limits, not a certification - and the exported geometry is not a "
    "checked drawing. Profiles, fits and clearances come out of the same "
    "idealised model as the analysis: no tolerance stack has been proven, and "
    "nothing here has been calibrated against measured hardware.\n\n"
    "Treat every part as a starting point to review, and validate against a "
    "physical prototype before anything load-bearing depends on it.")


def file_text(description: str = "") -> str:
    """``NOTICE.txt``, as it lands in the folder beside the parts.

    It carries the version that wrote it for the same reason every other file
    here does: these numbers are a model's output, the model changes between
    releases, and a folder of parts that cannot say which build made it cannot
    be checked against the changelog either.
    """
    import textwrap

    from . import __version__

    lines = [HEADLINE.upper(), "=" * len(HEADLINE), ""]
    if description:
        lines += [description, ""]
    # Wrapped here rather than left to whatever opens it: this is the one copy
    # that gets printed, pasted into an email and read in Notepad, none of which
    # will wrap it for the reader.
    lines += ["\n\n".join(textwrap.fill(paragraph, 78)
                          for paragraph in FULL.split("\n\n")),
              "",
              f"Written by cycloidgen {__version__}.",
              "https://github.com/medinstech/cycloidgen"]
    return "\n".join(lines) + "\n"
