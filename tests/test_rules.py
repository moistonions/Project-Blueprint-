from blueprint.models import FindingType, Severity
from blueprint.rules import compare, match_tasks
from tests.helpers import task


def run(oem, vendor):
    return compare(oem, vendor, asset_id="A1", vendor_name="V")


def types(findings):
    return sorted(f.type for f in findings)


def test_identical_schedules_produce_no_findings():
    oem = [task("oil filter", "replace", (500, "hours"))]
    assert run(oem, [task("oil filter", "change", (500, "hours"))]) == []


def test_missing_oem_task_is_critical():
    f = run([task("coupling alignment", "inspect", (12, "months"))], [])
    assert types(f) == [FindingType.MISSING_TASK]
    assert f[0].severity == Severity.CRITICAL


def test_extended_interval_is_critical():
    f = run([task("seal kit", "replace", (24, "months"))], [task("seal kit", "replace", (30, "months"))])
    assert types(f) == [FindingType.EXTENDED_INTERVAL]
    assert f[0].severity == Severity.CRITICAL


def test_unit_conversion_between_weeks_and_months():
    # 13 weeks (91 days) vs OEM 3 months (91.3 days) is within tolerance, not a gap
    assert run([task("belt", "inspect", (3, "months"))], [task("belt", "inspect", (13, "weeks"))]) == []
    # 1 year vs OEM 6 months is extended
    f = run([task("belt", "inspect", (6, "months"))], [task("belt", "inspect", (1, "years"))])
    assert types(f) == [FindingType.EXTENDED_INTERVAL]


def test_vendor_dropping_an_interval_basis_is_flagged():
    # OEM: 8000 h OR 24 months. Vendor tracks only months -> hours limit is unmonitored.
    oem = [task("seal kit", "replace", (8000, "hours"), (24, "months"))]
    f = run(oem, [task("seal kit", "replace", (24, "months"))])
    assert types(f) == [FindingType.MISSING_INTERVAL_BASIS]


def test_vendor_task_without_interval_is_flagged():
    f = run([task("seal kit", "replace", (24, "months"))], [task("seal kit", "replace")])
    assert types(f) == [FindingType.MISSING_INTERVAL_BASIS]


def test_vendor_extras_feed_the_rationale_agent():
    oem = [task("bearings", "lubricate", (2000, "hours"))]
    vendor = [task("bearings", "grease", (1000, "hours")), task("impeller", "clean", (6, "months"))]
    f = run(oem, vendor)
    assert types(f) == [FindingType.TIGHTENED_INTERVAL, FindingType.VENDOR_ADDITION]
    assert all(x.severity == Severity.INFO for x in f)


def test_match_by_part_number_when_names_differ():
    oem = [task("mechanical seal assembly", "replace", (24, "months"), parts=["SK-100-01"])]
    vendor = [task("pump seal", "replace", (24, "months"), parts=["sk-100-01"])]
    pairs, missing, extra = match_tasks(oem, vendor)
    assert len(pairs) == 1 and not missing and not extra


def test_match_by_similar_component_name():
    oem = [task("hydraulic return filter", "replace", (1000, "hours"))]
    vendor = [task("hydraulic return filters", "replace", (1000, "hours"))]
    assert run(oem, vendor) == []


def test_different_actions_do_not_match():
    oem = [task("belt", "replace", (12, "months"))]
    f = run(oem, [task("belt", "inspect", (12, "months"))])
    assert types(f) == [FindingType.MISSING_TASK, FindingType.VENDOR_ADDITION]


def test_each_vendor_task_matches_at_most_once():
    oem = [task("filter", "replace", (500, "hours")), task("filter", "replace", (500, "hours"))]
    f = run(oem, [task("filter", "replace", (500, "hours"))])
    assert types(f) == [FindingType.MISSING_TASK]
