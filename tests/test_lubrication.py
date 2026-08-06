"""The film, the regime it puts each contact in, and the friction that follows.

The point of these is that the model is *checked against its own physics* rather
than against whatever it happened to return the first time: the viscosity fit is
made to reproduce the two points it was built from, the film formula is made to
show the exponents it claims, and the temperature loop is made to agree with
itself at the answer it converges to.
"""
from __future__ import annotations

import pytest

from cycloidgen.analysis import analyse
from cycloidgen.analysis.efficiency import analyse_efficiency
from cycloidgen.analysis.lubrication import (
    BOUNDARY_LAMBDA,
    FULL_FILM_LAMBDA,
    TRACTION_COEFFICIENT,
    dynamic_viscosity_Pa_s,
    film_thickness_um,
    reduced_modulus_Pa,
)
from cycloidgen.analysis.thermal import CONVECTION_W_M2K, solve_operating_point
from cycloidgen.core.spec import DRY, LUBRICANTS, MATERIALS, Process, preset

RING = "Ring pin / disc flank"
OUT = "Output pin / disc hole"
CAM = "Disc bore / cam"


def _steel(ratio: int = 21, **over):
    """A machined steel drive, which is the only kind that can reach a film."""
    s = preset(ratio)
    s.process = Process.EDM
    s.disc_material = "Steel 4140 (hardened)"
    s.pin_material = "Bearing steel 100Cr6"
    s.shaft_material = "Steel 4140 (hardened)"
    s.housing_material = "Aluminium 7075-T6"
    for k, v in over.items():
        setattr(s, k, v)
    return s


# ------------------------------------------------------------------- viscosity


def test_the_viscosity_fit_reproduces_the_points_it_was_built_from():
    """Walther through two points has to pass through both of them, or the whole
    temperature story is being told by an extrapolation."""
    for lube in LUBRICANTS.values():
        if not lube.forms_a_film:
            continue
        for temp, quoted in ((40.0, lube.viscosity_40C_cSt),
                             (100.0, lube.viscosity_100C_cSt)):
            got = dynamic_viscosity_Pa_s(lube, temp) / (lube.density_g_cm3 * 1e-3)
            assert got == pytest.approx(quoted, rel=1e-6), (lube.name, temp)


def test_oil_thins_with_heat_and_a_dry_drive_has_no_viscosity_to_thin():
    lube = LUBRICANTS["Oil ISO VG 220 (gear)"]
    cold = dynamic_viscosity_Pa_s(lube, 20.0)
    hot = dynamic_viscosity_Pa_s(lube, 80.0)
    assert cold > 5 * hot > 0                      # an order of magnitude over 60 K
    assert dynamic_viscosity_Pa_s(LUBRICANTS[DRY], 20.0) == 0.0


# ------------------------------------------------------------------------ film


def test_the_film_formula_shows_the_exponents_it_claims():
    """Dowson-Hamrock is 0.7 on speed and -0.13 on load, and the asymmetry is the
    whole engineering point: entrainment builds film, load barely takes it away.
    A wiring mistake that swapped or dropped a group would still return a
    plausible number, so the number is not what is checked here."""
    base = {"eta_Pa_s": 0.05, "alpha_1_per_Pa": 22e-9, "e_prime_Pa": 2.2e11,
            "reduced_radius_m": 0.004, "entrainment_m_s": 0.25,
            "load_per_length_N_m": 1.2e5}
    h = film_thickness_um(**base)

    faster = film_thickness_um(**{**base, "entrainment_m_s": 0.5})
    assert faster / h == pytest.approx(2.0 ** 0.7, rel=1e-9)

    heavier = film_thickness_um(**{**base, "load_per_length_N_m": 2.4e5})
    assert heavier / h == pytest.approx(2.0 ** -0.13, rel=1e-9)

    # ...so doubling the load costs about 9%, and doubling the speed buys 62%
    assert heavier / h > 0.9
    assert faster / h > 1.6


def test_no_film_without_something_to_make_it_from():
    """Every group is a multiplier, so a zero anywhere is no film rather than a
    divide-by-zero or a number built out of a default."""
    ok = {"eta_Pa_s": 0.05, "alpha_1_per_Pa": 22e-9, "e_prime_Pa": 2.2e11,
          "reduced_radius_m": 0.004, "entrainment_m_s": 0.25,
          "load_per_length_N_m": 1.2e5}
    assert film_thickness_um(**ok) > 0
    for missing in ok:
        assert film_thickness_um(**{**ok, missing: 0.0}) == 0.0


def test_the_softer_material_makes_the_easier_film():
    """A printed disc deflects more, spreads the load and builds *more* film for
    it - which cuts the opposite way from every strength check in the app, and
    still does not save it, because its roughness is worse by far more."""
    steel = reduced_modulus_Pa(MATERIALS["Bearing steel 100Cr6"],
                               MATERIALS["Steel 4140 (hardened)"])
    printed = reduced_modulus_Pa(MATERIALS["Bearing steel 100Cr6"], MATERIALS["PLA"])
    assert steel > 20 * printed


# ---------------------------------------------------------------------- regime


def test_entrainment_is_half_the_sliding_speed_at_a_fixed_pin():
    """The physically important line in the module. A fixed pin does not move, so
    the mean of the two surface speeds is half their difference - the contact is
    dragged rather than rolled, and that is most of why a rolling pin is worth
    having."""
    lub = analyse(_steel()).lubrication
    for contact in lub.sliding:
        assert contact.entrainment_m_s == pytest.approx(
            contact.sliding_speed_m_s / 2.0)


def test_roughness_decides_the_regime_and_the_lubricant_cannot_rescue_it():
    """Same drive, same oil, three finishes. This is the model's main claim: on
    these contacts the surface is the lever and the grade is not."""
    got = {}
    for rq in (5.0, 0.4, 0.05):
        s = _steel(lubricant="Oil ISO VG 220 (gear)", surface_roughness_um=rq)
        got[rq] = analyse(s).lubrication[RING]

    assert got[5.0].lambda_ratio < BOUNDARY_LAMBDA
    assert got[5.0].regime == "boundary"
    assert got[0.05].lambda_ratio > FULL_FILM_LAMBDA
    assert got[0.05].regime == "full film"
    assert got[0.05].separated and not got[5.0].separated

    # Roughness is nowhere in the film formula, so at a fixed temperature the
    # three build the *same* film and differ only in what it is measured
    # against.  They do not run at a fixed temperature, which is the point: the
    # rough one sits in boundary, loses more, gets hotter, and thins its own oil,
    # so it ends up with a thinner film as well as more roughness to clear.
    same = [analyse_efficiency(_steel(lubricant="Oil ISO VG 220 (gear)",
                                      surface_roughness_um=rq),
                               temperature_C=60.0).lubrication[RING].film_um
            for rq in (5.0, 0.4, 0.05)]
    assert same[0] == pytest.approx(same[1]) == pytest.approx(same[2])
    assert got[5.0].film_um < got[0.05].film_um


def test_a_printed_drive_cannot_reach_a_film_with_any_lubricant_sold():
    """Not a defect in the model - it is why drives that have to last are not
    printed with fixed pins. Every grade in the table, and none of them clear a
    layered flank."""
    for name in LUBRICANTS:
        s = preset(21)                                   # FDM, 15 um Rq
        s.lubricant = name
        ring = analyse(s).lubrication[RING]
        assert ring.lambda_ratio < 0.1, name
        assert ring.regime == "boundary", name


def test_a_contact_that_rolls_has_no_film_to_report():
    """The same answer PV gives for a rolling contact: not a thick film, no film
    question. Reporting a number here would invite it to be compared with one."""
    s = _steel(ring_pins_are_rollers=True, output_pins_are_rollers=True,
               lubricant="Oil ISO VG 220 (gear)")
    lub = analyse(s).lubrication
    for name in (RING, OUT):
        assert not lub[name].slides
        assert lub[name].regime == "rolling"
        assert lub[name].film_um == 0.0
    assert {c.name for c in lub.sliding} == set()         # cam bearing fitted too
    assert lub.governing is None


def test_the_gap_is_a_ceiling_on_the_film():
    """A journal's film cannot be thicker than the room the parts leave each
    other, and the concentrated-contact formula does not know that: as the fit
    closes up its reduced radius runs to metres and the film it predicts runs off
    with it. The cap is what keeps the conforming contacts honest."""
    s = _steel(lubricant="Oil ISO VG 220 (gear)", cam_bearing_fitted=False,
               surface_roughness_um=0.05, hole_clearance=0.004)
    cam = analyse(s).lubrication[CAM]
    radial_gap_um = 1000.0 * s.hole_clearance / 2.0
    assert cam.film_um == pytest.approx(radial_gap_um)     # pinned at the gap

    # open the fit up and the film comes off the ceiling and is computed again
    s.hole_clearance = 0.4
    loose = analyse(s).lubrication[CAM]
    assert loose.film_um < 1000.0 * s.hole_clearance / 2.0


# ------------------------------------------------------------------- friction


def test_dry_is_exactly_the_number_the_design_states():
    """The invariant that matters most: a design that says nothing about
    lubrication gets the answer it got before any of this existed."""
    s = preset(21)
    assert s.lubricant == DRY
    lub = analyse(s).lubrication
    for contact in lub.sliding:
        assert contact.mu == s.friction_coefficient
        assert contact.film_um == 0.0 and contact.lambda_ratio == 0.0

    s.friction_coefficient = 0.2
    assert analyse(s).lubrication[RING].mu == 0.2


def test_a_full_film_contact_costs_the_traction_coefficient_and_no_more():
    s = _steel(lubricant="Oil ISO VG 220 (gear)", surface_roughness_um=0.02)
    ring = analyse(s).lubrication[RING]
    assert ring.separated
    assert ring.mu == pytest.approx(TRACTION_COEFFICIENT)


def test_the_additive_is_the_lever_where_the_film_is_out_of_reach():
    """Neither grease forms a film on a printed flank, so viscosity buys nothing
    and the boundary coefficient buys everything. This is the design advice the
    module exists to make quantitative."""
    plain, ep = (preset(21), preset(21))
    plain.lubricant = "Grease NLGI 2 (lithium/mineral)"
    ep.lubricant = "Grease NLGI 2 (EP, moly)"

    a_plain, a_ep = analyse(plain), analyse(ep)
    assert not a_plain.lubrication.forms_a_film
    assert not a_ep.lubrication.forms_a_film
    assert a_ep.lubrication[RING].mu < 0.6 * a_plain.lubrication[RING].mu
    assert a_ep.efficiency.efficiency > a_plain.efficiency.efficiency + 0.05


def test_the_governing_contact_is_the_one_with_the_least_to_spare():
    lub = analyse(_steel(lubricant="Oil ISO VG 220 (gear)")).lubrication
    worst = lub.governing
    assert worst is not None
    assert worst.lambda_ratio == min(c.lambda_ratio for c in lub.sliding)


# ------------------------------------------------- the loop temperature closes


def test_the_operating_point_agrees_with_itself():
    """The fixed point, checked the only way worth checking it: take the answer,
    re-run the losses at that temperature, and the temperature has to come back.
    Friction heats the oil, the hot oil stops holding the surfaces apart, and
    that is more friction - so an answer that does not close is a guess."""
    s = _steel(lubricant="Oil ISO VG 220 (gear)", surface_roughness_um=0.08)
    eff, therm = solve_operating_point(s)

    again = analyse_efficiency(s, temperature_C=therm.temperature_C)
    settled = s.ambient_temp_C + again.total_loss_W / (
        CONVECTION_W_M2K * s.cooling_area_mm2 * 1e-6)
    assert settled == pytest.approx(therm.temperature_C, abs=1.0)
    assert eff.lubrication.temperature_C > s.ambient_temp_C


def test_running_hot_costs_film_and_the_cold_answer_is_the_optimistic_one():
    """Evaluating friction at ambient answers for a drive on its first
    revolution. The running answer is the one that has to hold."""
    s = _steel(lubricant="Oil ISO VG 220 (gear)", surface_roughness_um=0.08)
    cold = analyse_efficiency(s, temperature_C=s.ambient_temp_C)
    eff, therm = solve_operating_point(s)

    assert therm.temperature_C > s.ambient_temp_C
    assert eff.lubrication[RING].film_um < cold.lubrication[RING].film_um
    assert eff.efficiency <= cold.efficiency


def test_a_dry_design_skips_the_loop_because_there_is_nothing_to_iterate():
    """No viscosity means no temperature dependence, so one pass is the exact
    answer and iterating would only be a slower way to reach it."""
    s = preset(21)
    eff, therm = solve_operating_point(s)
    once = analyse_efficiency(s)
    assert eff.efficiency == once.efficiency
    assert eff.lubrication.temperature_C == s.ambient_temp_C
    assert therm.temperature_C > s.ambient_temp_C          # it still gets hot


# ---------------------------------------------------------------------- checks


def test_the_regime_is_reported_on_every_design():
    for spec in (preset(21), _steel(lubricant="Oil ISO VG 220 (gear)")):
        codes = [f.code for f in analyse(spec).report.findings]
        assert codes.count("LUBRICATION_REGIME") == 1


def test_a_lubricant_that_does_not_separate_the_surfaces_says_so():
    """A warning rather than an error: the drive runs, and the oil is still worth
    having. What is wrong is the expectation that it is holding the parts apart."""
    s = preset(21)
    s.lubricant = "Oil ISO VG 220 (gear)"
    finding = next(f for f in analyse(s).report.findings
                   if f.code == "LUBRICATION_REGIME")
    assert finding.severity.name == "WARNING"
    assert "boundary lubrication" in finding.message
    assert finding.value < 1.0

    clean = _steel(lubricant="Oil ISO VG 220 (gear)", surface_roughness_um=0.02)
    ok = next(f for f in analyse(clean).report.findings
              if f.code == "LUBRICATION_REGIME")
    assert ok.severity.name == "INFO"
    assert "full film" in ok.message
