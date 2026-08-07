"""The check explanations, and whether they still describe the checks.

An explanation that has drifted from the check it explains is worse than none:
it is a confident answer to the wrong question.  So the codes are not listed by
hand here - they are parsed out of the calls that raise them, which means adding
a check without explaining it fails, and deleting one without removing its entry
fails too.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from cycloidgen.core.explain import EXPLANATIONS, explain, margin
from cycloidgen.core.validate import Finding, Severity

ROOT = Path(__file__).resolve().parent.parent / "cycloidgen"


def _emitted_codes() -> dict[str, str]:
    """Every code the application can raise, and the file it comes from.

    Found by parsing for ``<report>.add(Severity.X, "CODE", ...)`` rather than
    by running designs: no set of specs exercises every branch, and the ones
    that stay unexercised are exactly the ones whose explanation nobody would
    notice was missing.
    """
    found: dict[str, str] = {}
    sources = [ROOT / "core" / "validate.py", *(ROOT / "analysis").glob("*.py")]
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "add"
                    and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)):
                found.setdefault(node.args[1].value, path.name)
    return found


def test_the_parser_finds_the_checks_at_all():
    """If this breaks, every test below is asserting against an empty set."""
    codes = _emitted_codes()
    assert len(codes) > 30
    assert "UNDERCUT" in codes and "OVERTEMP" in codes


def test_every_check_the_app_can_raise_is_explained():
    missing = sorted(set(_emitted_codes()) - set(EXPLANATIONS))
    assert not missing, f"no explanation for {', '.join(missing)}"


def test_no_explanation_describes_a_check_that_no_longer_exists():
    stale = sorted(set(EXPLANATIONS) - set(_emitted_codes()))
    assert not stale, f"explained but never raised: {', '.join(stale)}"


def test_every_explanation_answers_all_three_questions():
    for code, detail in EXPLANATIONS.items():
        assert detail.title and not detail.title.endswith("."), code
        assert detail.tests, code
        assert len(detail.why) > 60, f"{code}: 'why' is a restatement, not a reason"
        assert len(detail.fix) > 30, f"{code}: 'fix' does not say what to change"
        assert detail.keep in ("below", "above", ""), code


def test_the_readme_lists_every_check_the_app_can_raise():
    """The README is the shop window, and a checklist that is quietly missing a
    quarter of its entries is worse than one that admits to being a sample.

    Both directions, as everywhere else here: a check added without being listed
    fails, and a code that only the README believes in fails too.
    """
    readme = (ROOT.parent / "README.md").read_text(encoding="utf-8")
    # Only the Checks section, not the whole file.  Elsewhere the README quotes
    # environment variables and Win32 constants, which are shaped exactly like
    # check codes; scanning everything would mean an exception list that grows
    # every time the prose mentions one.
    section = re.search(r"^## Checks$(.*?)^## ", readme, re.M | re.S)
    assert section, "the README no longer has a Checks section"
    listed = set(re.findall(r"`([A-Z][A-Z0-9_]{3,})`", section.group(1)))
    codes = set(EXPLANATIONS)
    assert not codes - listed, f"not in the README: {sorted(codes - listed)}"
    assert not listed - codes, \
        f"the README names checks that do not exist: {sorted(listed - codes)}"


_UNITS = ["zero", "one", "two", "three", "four", "five", "six", "seven",
          "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
          "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = {name: (i + 2) * 10 for i, name in enumerate(
    ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty",
     "ninety"])}


def _spelled(word: str) -> int:
    """"forty-two" -> 42.  Raises rather than guessing, which is the point."""
    word = word.lower()
    if word in _UNITS:
        return _UNITS.index(word)
    tens, _, unit = word.partition("-")
    return _TENS[tens] + (_UNITS.index(unit) if unit else 0)


def test_the_readme_says_how_many_checks_there_are_and_is_right():
    """The list above is held to the code; the *count* beside it was not.

    So the README claimed fifty-five checks at the top of the page and
    fifty-three at the head of the section listing them - two numbers, in one
    document, about one thing, and neither of them anybody's job.  A number in
    prose is a claim like any other; this is the one that makes it checkable.
    """
    readme = (ROOT.parent / "README.md").read_text(encoding="utf-8")
    section = re.search(r"^## Checks$\s*(.*?)^## ", readme, re.M | re.S)
    assert section, "the README no longer has a Checks section"

    claims = {
        "the summary at the top":
            re.search(r"\*\*([A-Za-z-]+) checks that explain themselves\.\*\*",
                      readme),
        "the head of the Checks section":
            re.match(r"([A-Za-z-]+) of them\.", section.group(1)),
    }
    for where, found in claims.items():
        assert found, f"{where} no longer states a count"
        assert _spelled(found.group(1)) == len(EXPLANATIONS), where


def test_every_explained_check_can_also_point_at_its_parameters():
    """The two declarations are separate on purpose - one names engineering, the
    other names widgets - but a check that tells you what to change and then
    cannot show you where to change it is half an answer."""
    from cycloidgen.ui.fields import CODE_FIELDS

    unroutable = sorted(set(EXPLANATIONS) - set(CODE_FIELDS))
    assert not unroutable, f"explained but not routed to a field: {unroutable}"


# ------------------------------------------------------------------- margins


def _finding(code: str, value: float | None, limit: float | None) -> Finding:
    return Finding(Severity.WARNING, code, "", value, limit)


def test_a_margin_is_how_many_times_over_the_limit_you_are():
    # UNDERCUT wants to stay below: a pin at half the critical radius is 2x clear
    assert margin(_finding("UNDERCUT", 2.0, 4.0)) == pytest.approx(2.0)
    # PIN_OVERLAP wants to stay above: a pitch twice the limit is 2x clear
    assert margin(_finding("PIN_OVERLAP", 8.0, 4.0)) == pytest.approx(2.0)


def test_a_ratio_that_would_mislead_is_not_offered():
    """A clearance measured at -0.4 mm is a real reading and a useless
    denominator; a reading with no limit is not a multiple of anything."""
    assert margin(_finding("PROFILE_INTERFERENCE", -0.4, 0.0)) is None
    assert margin(_finding("MASS", 379.0, None)) is None
    assert margin(_finding("TORSIONAL_STIFFNESS", 3.2, None)) is None
    assert margin(_finding("UNDERCUT", 0.0, 4.0)) is None


def test_an_unknown_code_explains_nothing_rather_than_raising():
    assert explain("NO_SUCH_CHECK") is None
    assert margin(_finding("NO_SUCH_CHECK", 1.0, 2.0)) is None


def test_the_explanations_are_reachable_from_a_real_report():
    """The end the user actually meets: analyse a design, and every finding it
    produces can say what it was testing."""
    from cycloidgen.analysis import analyse
    from cycloidgen.core.spec import preset

    report = analyse(preset(15)).report
    assert report.findings
    for finding in report.findings:
        assert explain(finding.code) is not None, finding.code
