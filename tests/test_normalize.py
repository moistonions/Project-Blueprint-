import pytest

from blueprint.normalize import Dimension, canonical_action, interval_map, task_key
from tests.helpers import task


@pytest.mark.parametrize(
    "raw,expected",
    [("Replace", "replace"), ("change", "replace"), ("replacing", "replace"), ("Check", "inspect"),
     ("greasing", "lubricate"), ("inspected", "inspect"), ("flush and refill", "flush")],
)
def test_canonical_action(raw, expected):
    assert canonical_action(raw) == expected


def test_task_key_ignores_word_order_and_synonyms():
    assert task_key(task("Engine Oil Filter", "Change")) == task_key(task("filter, engine oil", "replace"))


def test_interval_map_normalizes_and_keeps_tightest():
    t = task("x", "inspect", (3, "months"), (2, "months"), (500, "hours"), (10, "miles"))
    m = interval_map(t)
    assert m[Dimension.CALENDAR] == pytest.approx(365.25 / 6)
    assert m[Dimension.USAGE] == 500
    assert m[Dimension.DISTANCE] == pytest.approx(16.09344)


def test_parse_and_format_intervals_round_trip():
    from blueprint.normalize import format_intervals, parse_intervals

    ivs = parse_intervals("250 h or 6 mo; 1.5 years")
    assert format_intervals(ivs) == "250 hours; 6 months; 1.5 years"
    assert parse_intervals(format_intervals(ivs)) == ivs
    with pytest.raises(ValueError):
        parse_intervals("as required")


def test_component_similarity_rules():
    from blueprint.normalize import component_similarity

    assert component_similarity("coolant", "engine coolant") == 1.0
    assert component_similarity("hyd filters", "hydraulic return filter") == 1.0
    assert component_similarity("filter", "oil filter") < 0.8
