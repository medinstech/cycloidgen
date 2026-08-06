"""Every parameter explains itself, and every explanation names a real one.

Both ends, the same way ``test_explain.py`` holds both ends of the check
explanations: a field added to the panel without guidance fails here, and so
does guidance for a field that no longer exists.
"""
from __future__ import annotations

import pytest

from cycloidgen.core.guide import PARAMETERS, guide
from cycloidgen.core.spec import GearSpec
from cycloidgen.ui.fields import CODE_FIELDS, GROUPS, codes_for_field

FIELD_NAMES = {f.name for _, fields in GROUPS for f in fields}


def test_every_parameter_in_the_panel_is_explained():
    """The whole point: forty-odd fields and nowhere to find out what they do."""
    assert not FIELD_NAMES - set(PARAMETERS), \
        f"shown but not explained: {sorted(FIELD_NAMES - set(PARAMETERS))}"


def test_every_explanation_is_of_a_parameter_that_exists():
    """A guide for a field that has been renamed away is dead text nobody sees."""
    assert not set(PARAMETERS) - FIELD_NAMES, \
        f"explained but not shown: {sorted(set(PARAMETERS) - FIELD_NAMES)}"


def test_every_explained_name_is_a_field_on_the_spec():
    """The panel writes these straight onto the spec, so a guide for something
    that is not a spec field is guidance for a control that cannot exist."""
    attributes = set(GearSpec.model_fields)
    assert not set(PARAMETERS) - attributes, \
        f"not on GearSpec: {sorted(set(PARAMETERS) - attributes)}"


def test_the_three_parts_are_filled_in_and_distinct():
    """``what``, ``choosing`` and ``trade`` answer three different questions, and
    the failure mode of a declaration like this is one paragraph copied about."""
    for name, g in PARAMETERS.items():
        assert len(g.what) > 40, name
        assert len(g.choosing) > 40, name
        assert g.what != g.choosing != g.trade, name
        if g.trade:
            assert len(g.trade) > 20, name


def test_the_parameters_with_no_trade_are_the_ones_that_really_have_none():
    """An empty ``trade`` is a claim - that this one only goes one way - and it
    is rare enough to be worth listing rather than leaving to drift."""
    one_way = {n for n, g in PARAMETERS.items() if not g.trade}
    assert one_way == set(), \
        ("every parameter here currently states a trade; if one genuinely has "
         f"none, add it to this test on purpose: {sorted(one_way)}")


def test_the_reverse_index_agrees_with_the_forward_one():
    """``codes_for_field`` is derived, and a derivation is only worth having
    while it stays in step with what it is derived from."""
    for code, names in CODE_FIELDS.items():
        for name in names:
            assert code in codes_for_field(name), (code, name)
    for name in FIELD_NAMES:
        for code in codes_for_field(name):
            assert name in CODE_FIELDS[code]


def test_a_parameter_that_moves_nothing_still_explains_itself():
    """Eleven fields have no check pointing at them - tolerances, the disc gap,
    the bearing designations. Those are exactly the ones a user has no other way
    to learn about, so they are the last ones that should be skipped."""
    unchecked = sorted(n for n in FIELD_NAMES if not codes_for_field(n))
    assert unchecked, "this test is guarding a case that no longer exists"
    for name in unchecked:
        assert guide(name) is not None, name


def test_lookup_of_something_that_is_not_a_parameter_is_not_an_error():
    assert guide("not_a_field") is None


@pytest.mark.parametrize("name", sorted(PARAMETERS))
def test_no_guidance_ends_mid_sentence(name):
    """Prose assembled from implicitly concatenated strings loses a space
    between the pieces about as often as anyone edits it."""
    g = PARAMETERS[name]
    for text in (g.what, g.choosing, g.trade):
        if text:
            assert text.strip().endswith((".", ".\"")), (name, text[-40:])
            assert "  " not in text, (name, "double space")
