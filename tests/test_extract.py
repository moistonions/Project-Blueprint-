from blueprint.extract import _windows, extract_tasks, interval_in_quote
from blueprint.ingest import Page
from blueprint.models import ExtractedTask, ExtractionResult, Interval, SourceKind


def test_interval_must_be_written_in_quote():
    assert interval_in_quote(50, "In a period of 50 operation hours")
    assert interval_in_quote(1, "Once a week")
    assert interval_in_quote(1, "checked annually")
    assert interval_in_quote(2, "roughly every 2 months")
    assert not interval_in_quote(2, "Charge battery regularly.")
    assert not interval_in_quote(1, "the oil level has to be checked regularly")
    assert not interval_in_quote(5, "every 50 hours")


def test_oversized_page_is_split_across_windows():
    windows = _windows([Page(1, "x" * 2500)], max_chars=1000)
    assert len(windows) >= 3 and all(w.startswith("[page 1]") for w in windows)


class _OneShot:
    def parse(self, **_):
        return ExtractionResult(tasks=[ExtractedTask(
            asset_id="A", component="engine oil level", action="inspect",
            intervals=[Interval(value=1, unit="days")],
            source_quote="the oil level has to be checked regularly", page=53,
        )])


def test_unstated_interval_removed_and_flagged():
    [t] = extract_tasks(_OneShot(), model="m", pages=[Page(53, "text")], kind=SourceKind.OEM, asset_id="A")
    assert t.intervals == [] and t.needs_review
    assert "1 days" in t.review_note
