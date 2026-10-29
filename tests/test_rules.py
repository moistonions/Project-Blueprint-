from blueprint.models import MatchBasis, Severity
from blueprint.rules import compare, match_tasks
from tests.helpers import task


def run(oem, vendor, tolerance=0.10):
    return compare(oem, vendor, asset_id="A1", vendor_name="V", tolerance=tolerance)


def types(findings):
    return sorted(f.type.value for f in findings)


def test_identical_schedules_produce_no_findings():
    oem = [task("oil filter", "replace", (500, "hours"))]
    assert run(oem, [task("oil filter", "change", (500, "hours"))]) == []


def test_missing_oem_task_is_critical():
    f = run([task("coupling alignment", "inspect", (12, "months"))], [])
    assert types(f) == ["missing_task"]
    assert f[0].severity == Severity.CRITICAL


def test_longer_within_tolerance_is_a_warning():
    f = run([task("fuel filter", "replace", (500, "hours"))], [task("fuel filter", "replace", (525, "hours"))])
    assert types(f) == ["longer_interval"]
    assert f[0].severity == Severity.WARNING


def test_longer_beyond_tolerance_is_critical():
    f = run([task("seal kit", "replace", (24, "months"))], [task("seal kit", "replace", (30, "months"))])
    assert types(f) == ["beyond_tolerance"]
    assert f[0].severity == Severity.CRITICAL


def test_tolerance_is_configurable():
    oem, vendor = [task("x", "inspect", (100, "hours"))], [task("x", "inspect", (108, "hours"))]
    assert types(run(oem, vendor, tolerance=0.10)) == ["longer_interval"]
    assert types(run(oem, vendor, tolerance=0.05)) == ["beyond_tolerance"]


def test_safety_critical_tasks_have_zero_tolerance():
    oem = [task("emergency stop", "test", (6, "months"), safety_critical=True)]
    f = run(oem, [task("e-stop", "test", (27, "weeks"))])
    assert types(f) == ["beyond_tolerance"]
    assert "zero tolerance" in f[0].message


def test_unit_conversion_rounding_is_not_a_gap():
    # 13 weeks (91 days) vs OEM 3 months (91.3 days)
    assert run([task("belt", "inspect", (3, "months"))], [task("belt", "inspect", (13, "weeks"))]) == []
    assert run([task("belt", "inspect", (90, "days"))], [task("belt", "inspect", (3, "months"))]) == []


def test_whichever_comes_first_checks_every_dimension():
    oem = [task("coolant", "replace", (3000, "hours"), (24, "months"))]
    f = run(oem, [task("coolant", "replace", (3000, "hours"), (36, "months"))])
    assert types(f) == ["beyond_tolerance"]
    assert "calendar" in f[0].message


def test_vendor_dropping_an_interval_basis_is_flagged():
    oem = [task("seal kit", "replace", (8000, "hours"), (24, "months"))]
    assert types(run(oem, [task("seal kit", "replace", (24, "months"))])) == ["missing_interval_basis"]


def test_vendor_task_without_interval_is_flagged():
    f = run([task("seal kit", "replace", (24, "months"))], [task("seal kit", "replace")])
    assert types(f) == ["missing_interval_basis"]


def test_part_number_mismatch_is_ambiguous_warning():
    oem = [task("crankcase breather filter", "replace", (1000, "hours"), parts=["SG-BF-40"])]
    f = run(oem, [task("crankcase breather filter", "replace", (1000, "hours"), parts=["SG-BF-41"])])
    assert types(f) == ["spec_mismatch"]
    assert f[0].severity == Severity.WARNING and "ambiguous" in f[0].message


def test_fluid_spec_mismatch_ignores_formatting():
    oem = [task("engine oil", "replace", (250, "hours"), spec="SAE 15W-40")]
    assert run(oem, [task("engine oil", "replace", (250, "hours"), spec="sae 15w40")]) == []
    f = run(oem, [task("engine oil", "replace", (250, "hours"), spec="SAE 10W-30")])
    assert types(f) == ["spec_mismatch"]


def test_needs_review_counts_as_failed_and_is_not_compared():
    oem = [task("hoses", "inspect", review_note="'as required'", needs_review=True)]
    f = run(oem, [])
    assert types(f) == ["needs_review"]
    assert f[0].severity == Severity.CRITICAL and "failed" in f[0].message


def test_vendor_extras_feed_the_rationale_agent():
    oem = [task("bearings", "lubricate", (2000, "hours"))]
    vendor = [task("bearings", "grease", (1000, "hours")), task("impeller", "clean", (6, "months"))]
    f = run(oem, vendor)
    assert types(f) == ["tightened_interval", "vendor_addition"]
    assert all(x.severity == Severity.INFO for x in f)


def test_match_stores_basis_and_confidence():
    oem = [task("hydraulic return filter", "replace", (1000, "hours"), parts=["12345"])]
    pairs, _, _ = match_tasks(oem, [task("hyd filters", "change", (1000, "hours"))])
    assert pairs[0].basis == MatchBasis.SIMILAR_NAME and 0.8 <= pairs[0].confidence < 1
    pairs, _, _ = match_tasks(oem, [task("pump seal", "replace", (1, "years"), parts=["12345"])])
    assert pairs[0].basis == MatchBasis.PART_NUMBER
    f = run(oem, [task("hyd filters", "change", (1100, "hours"))])
    assert f[0].match_basis == MatchBasis.SIMILAR_NAME and f[0].match_confidence


def test_single_word_components_need_exact_match():
    oem = [task("filter", "replace", (500, "hours"))]
    assert types(run(oem, [task("oil filter", "replace", (500, "hours"))])) == ["missing_task", "vendor_addition"]


def test_different_actions_do_not_match():
    f = run([task("belt", "replace", (12, "months"))], [task("belt", "inspect", (12, "months"))])
    assert types(f) == ["missing_task", "vendor_addition"]


def test_each_vendor_task_matches_at_most_once():
    oem = [task("fuel filter", "replace", (500, "hours")), task("fuel filter", "replace", (500, "hours"))]
    assert types(run(oem, [task("fuel filter", "replace", (500, "hours"))])) == ["missing_task"]


def test_best_candidate_wins():
    oem = [task("engine oil filter", "replace", (500, "hours"))]
    vendor = [task("engine oil cooler filter", "replace", (500, "hours")), task("oil filter, engine", "replace", (500, "hours"))]
    pairs, _, _ = match_tasks(oem, vendor)
    assert pairs[0].vendor is vendor[1] and pairs[0].basis == MatchBasis.TASK_KEY
