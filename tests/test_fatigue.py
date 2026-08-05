"""Fully reversed duty on the disc web and the output pins.

The interesting failures here are not arithmetic.  They are a check that reports
a comfortable margin because it silently fell back to a default, and a check that
answers for a material it has no data for - so most of these are about the
answer being *refused* in the right places.
"""
from __future__ import annotations

import math

import pytest

from cycloidgen.analysis import analyse
from cycloidgen.analysis.fatigue import (
    FINITE_LIFE_CYCLES,
    RELIABILITY_99,
    analyse_fatigue,
    endurance_limit,
    size_factor,
    surface_factor,
)
from cycloidgen.analysis.mass import analyse_mass
from cycloidgen.core.spec import MATERIALS, GearSpec, Process, preset


def _steel(ratio: int = 21, torque: float = 25.0) -> GearSpec:
    spec = preset(ratio)
    spec.process = Process.CNC
    spec.apply_process_defaults()
    spec.disc_material = "Steel 4140 (hardened)"
    spec.pin_material = "Bearing steel 100Cr6"
    spec.output_torque_Nm = torque
    return spec


def _run(spec):
    mass = analyse_mass(spec)
    return analyse_fatigue(spec, mass.web_shear_MPa, mass.min_web_mm)


# ------------------------------------------------------------- the factors


def test_surface_factor_is_never_better_than_polished():
    """The machined fit runs above 1 for soft metals, which would read as a
    finish that improves on the specimen it was measured against."""
    for material in MATERIALS.values():
        for process in Process:
            assert 0.0 < surface_factor(process, material.sigma_ultimate_MPa) <= 1.0


def test_a_rougher_process_is_never_kinder():
    """Fatigue cracks start at the surface, so the ranking of the processes is
    the one thing here that must not invert."""
    sut = MATERIALS["Steel 4140 (hardened)"].sigma_ultimate_MPa
    ground = surface_factor(Process.EDM, sut)
    machined = surface_factor(Process.CNC, sut)
    printed = max(surface_factor(p, sut) for p in (Process.FDM, Process.SLA, Process.SLS))
    assert ground > machined > printed


def test_size_factor_falls_with_section_and_is_capped():
    assert size_factor(2.0) == 1.0
    assert size_factor(50.0) < size_factor(10.0) < 1.0
    assert size_factor(300.0) > 0.0


# --------------------------------------------------- refusing to answer


def test_polymers_get_no_fatigue_number():
    """A Marin correction fitted to wrought metal, applied to a printed
    polymer, would be a confident answer with nothing behind it."""
    spec = preset(21)
    spec.disc_material = "PLA"
    spec.pin_material = "PLA"
    result = _run(spec)
    assert not result.modelled
    assert result.worst is None
    assert result.safety_factor == math.inf
    assert all(p.strength_MPa == 0.0 for p in result.parts)


def test_the_refusal_reaches_the_report_rather_than_passing_quietly():
    """An unanswered question has to be visible.  Silence reads as a pass."""
    spec = preset(21)
    spec.disc_material = "PLA"
    spec.pin_material = "PLA"
    codes = [f.code for f in analyse(spec).report.findings]
    assert "FATIGUE_NOT_MODELLED" in codes
    assert "FATIGUE_LIFE" not in codes


def test_every_material_with_a_fatigue_strength_has_an_ultimate_under_it():
    """Goodman divides by the ultimate, and the fatigue strength has to be the
    smaller of the two or the material is being claimed to last forever at a
    stress that breaks it in one pull."""
    for material in MATERIALS.values():
        assert material.sigma_ultimate_MPa >= material.sigma_yield_MPa
        if material.fatigue_strength_MPa is not None:
            assert 0.0 < material.fatigue_strength_MPa < material.sigma_ultimate_MPa


# ------------------------------------------------------------- the answer


def test_the_correction_only_ever_derates():
    """Every Marin factor is a knock-down.  A corrected strength above the
    specimen's own would mean one of them had been inverted."""
    spec = _steel()
    material = MATERIALS["Steel 4140 (hardened)"]
    corrected = endurance_limit(spec, 40.0, 10.0, material=material)
    assert 0.0 < corrected < material.fatigue_strength_MPa


def test_reliability_is_taken_off_and_not_forgotten():
    """The published strengths are means: without this factor the answer is
    'half of them last this long', which is not what a safety factor says."""
    spec = _steel()
    material = MATERIALS["Steel 1045"]
    corrected = endurance_limit(spec, 20.0, 10.0, material=material)
    ka = surface_factor(spec.process, material.sigma_ultimate_MPa)
    kb = size_factor(10.0)
    assert corrected == pytest.approx(
        ka * kb * RELIABILITY_99 * material.fatigue_strength_MPa, rel=1e-9)


def test_shear_is_weaker_than_bending():
    spec = _steel()
    material = MATERIALS["Steel 1045"]
    bending = endurance_limit(spec, 20.0, 10.0, material=material, loading="bending")
    shear = endurance_limit(spec, 20.0, 10.0, material=material, loading="shear")
    assert 0.0 < shear < bending


def test_heat_costs_fatigue_strength():
    spec = _steel()
    material = MATERIALS["Steel 1045"]
    cool = endurance_limit(spec, 20.0, 10.0, material=material)
    hot = endurance_limit(spec, 220.0, 10.0, material=material)
    assert hot < cool


def test_the_running_temperature_is_the_one_used():
    """Not the ambient.  The drive heats itself and the strength follows the
    temperature it actually reaches."""
    spec = _steel()
    analysis = analyse(spec)
    assert analysis.fatigue.temperature_C == pytest.approx(
        analysis.thermal.temperature_C)
    assert analysis.fatigue.temperature_C > spec.ambient_temp_C


def test_load_drives_it_the_right_way_and_the_check_can_fail():
    """A check that cannot fail is not a check.  Torque up until it does."""
    easy = _run(_steel(torque=25.0))
    hard = _run(_steel(torque=260.0))
    assert hard.safety_factor < easy.safety_factor
    assert hard.safety_factor < 1.0 < easy.safety_factor
    assert not hard.ok and easy.ok


def test_failing_fatigue_is_an_error_in_the_report():
    codes = {f.code: f.severity for f in analyse(_steel(torque=260.0)).report.findings}
    assert "FATIGUE_LIFE" in codes
    assert codes["FATIGUE_LIFE"].name == "ERROR"


def test_the_web_stress_is_the_one_the_static_check_used():
    """Two checks on one ligament that disagreed about how hard it is working
    would be a bug nobody could see from the outside."""
    spec = _steel()
    mass = analyse_mass(spec)
    result = analyse_fatigue(spec, mass.web_shear_MPa, mass.min_web_mm)
    web = next(p for p in result.parts if p.part == "disc web")
    assert web.alternating_MPa == pytest.approx(mass.web_shear_MPa)


def test_the_cycle_count_is_per_input_revolution():
    """Once per input revolution is the whole basis of the check, so the rate
    has to be the input speed and not the output's."""
    spec = _steel()
    result = _run(spec)
    assert result.cycles_per_hour == pytest.approx(spec.input_rpm * 60.0)
    assert result.hours_to_ten_million == pytest.approx(
        1e7 / (spec.input_rpm * 60.0))


def test_aluminium_is_reported_on_a_finite_life_basis():
    """It has no endurance limit.  Saying so is the difference between a margin
    and a margin that expires."""
    spec = _steel()
    spec.disc_material = "Aluminium 7075-T6"
    spec.pin_material = "Aluminium 7075-T6"
    result = _run(spec)
    assert result.modelled
    assert result.finite_life_basis
    assert result.finite_life_cycles == FINITE_LIFE_CYCLES


def test_steel_is_not():
    result = _run(_steel())
    assert result.modelled and not result.finite_life_basis


def test_the_design_search_will_not_hand_back_a_pin_that_cracks():
    """It used to.  Output pins are cantilevers off the carrier plate and the
    search buys compactness with thin ones - before this constraint went in,
    every design it returned for these requirements had pins between 0.11 and
    0.99 on fatigue, and the worst of them were past yield in bending as well.
    Nothing in the app looked at output pin bending at all until this check."""
    from test_design import _steel_requirements

    from cycloidgen.design import Objective
    from cycloidgen.design.optimize import optimise

    result = optimise(_steel_requirements(objective=Objective.COMPACT),
                      effort="quick")
    assert result.best
    for candidate in result.best:
        assert candidate.analysis.fatigue.ok, (
            f"{candidate.spec.output_pin_count} pins of "
            f"{candidate.spec.output_pin_diameter} mm came back at "
            f"{candidate.analysis.fatigue.safety_factor:.2f}")


def test_the_analysis_carries_it():
    analysis = analyse(_steel())
    assert analysis.fatigue is not None
    assert analysis.fatigue.worst is not None
