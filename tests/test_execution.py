from datetime import date

from blueprint.execution import HourMeter, check_execution
from blueprint.models import Ticket
from tests.helpers import task


def tk(d, component, action="replace", meter=None):
    return Ticket(asset_id="A1", date=date.fromisoformat(d), component=component, action=action, meter_hours=meter)


def run(oem, tickets, as_of=None):
    return check_execution(oem, tickets, asset_id="A1", vendor_name=None, tolerance=0.10, as_of=as_of)


def test_usage_rate_from_meter_readings():
    m = HourMeter([tk("2025-01-01", "x", meter=1000), tk("2025-07-02", "x", meter=1600)])
    assert round(m.usage_rate()) == 100
    assert m.at(date(2025, 4, 2)) == 1300


def test_on_time_task_has_no_gap():
    oem = [task("oil filter", "replace", (6, "months"))]
    assert run(oem, [tk("2025-01-01", "oil filter"), tk("2025-06-30", "oil filter")]) == []


def test_late_completion_is_flagged():
    oem = [task("oil filter", "replace", (6, "months"))]
    f = run(oem, [tk("2025-01-01", "oil filter"), tk("2025-09-01", "oil filter")])
    assert len(f) == 1 and "done late on 2025-09-01" in f[0].message


def test_skipped_task_is_flagged_as_of_latest_ticket():
    oem = [task("belt", "inspect", (6, "months"))]
    tickets = [tk("2025-01-01", "belt", "inspect"), tk("2025-10-01", "battery", "inspect")]
    f = run(oem, tickets)
    assert len(f) == 1 and "not done since last done 2025-01-01" in f[0].message


def test_hours_trigger_uses_meter_whichever_first():
    oem = [task("oil filter", "replace", (250, "hours"), (12, "months"))]
    tickets = [tk("2025-01-01", "oil filter", meter=1000), tk("2025-04-01", "oil filter", meter=1400)]
    f = run(oem, tickets)
    assert len(f) == 1 and "400 running hours" in f[0].message


def test_safety_critical_execution_has_zero_tolerance():
    oem = [task("e-stop", "test", (6, "months"), safety_critical=True)]
    tickets = [tk("2025-01-01", "e-stop", "test"), tk("2025-07-20", "e-stop", "test")]
    assert len(run(oem, tickets)) == 1
    oem[0].safety_critical = False
    assert run(oem, tickets) == []
