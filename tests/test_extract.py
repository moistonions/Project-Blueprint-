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


class _Seq:
    def __init__(self, batches):
        self.batches = list(batches)

    def parse(self, **_):
        return ExtractionResult(tasks=self.batches.pop(0))


def _t(quote, value, unit, page, comp="fuel prefilter", action="replace"):
    return ExtractedTask(asset_id="A", component=comp, action=action, page=page, source_quote=quote,
                         intervals=[Interval(value=value, unit=unit)])


def test_interval_from_table_header_on_same_page_is_kept():
    page = Page(84, "Every 500 operating hours or every 12 months\nChange the fuel prefilter")
    llm = _Seq([[_t("Change the fuel prefilter", 500, "hours", 84)]])
    [t] = extract_tasks(llm, model="m", pages=[page], kind=SourceKind.OEM, asset_id="A")
    assert [iv.value for iv in t.intervals] == [500]
    assert "same page" in t.review_note


def test_daily_on_page_does_not_rescue_vague_quote():
    page = Page(142, "Checks (daily)\nThe raw water filter must be regularly checked")
    llm = _Seq([[_t("The raw water filter must be regularly checked", 1, "days", 142, "raw water filter", "inspect")]])
    [t] = extract_tasks(llm, model="m", pages=[page], kind=SourceKind.OEM, asset_id="A")
    assert t.intervals == [] and t.needs_review


def test_merged_duplicate_keeps_its_quote():
    pages = [Page(1, "x" * 50), Page(2, "y" * 50)]
    llm = _Seq([
        [ExtractedTask(asset_id="A", component="engine oil level", action="inspect", page=1,
                       source_quote="check the oil level regularly")],
        [_t("Every 8 operating hours: check the oil level", 8, "hours", 2, "engine oil level", "inspect")],
    ])
    [t] = extract_tasks(llm, model="m", pages=pages, kind=SourceKind.OEM, asset_id="A", max_chars=60)
    assert [iv.value for iv in t.intervals] == [8]
    assert "Every 8 operating hours" in t.source_quote and "(p.2)" in t.source_quote
