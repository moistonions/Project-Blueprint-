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
