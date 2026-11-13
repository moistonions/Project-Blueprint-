from blueprint.ingest import Page, chunk_pages, read_pages


def test_read_text_file():
    pages = read_pages("notes.txt", b"hello")
    assert pages == [Page(1, "hello")]


def test_chunks_respect_size_and_keep_page_numbers():
    pages = [Page(1, "\n\n".join(["a" * 300] * 10)), Page(2, "short")]
    chunks = chunk_pages(pages, max_chars=1000, overlap=100)
    assert all(len(c.text) <= 1000 for c in chunks)
    assert chunks[-1].page == 2 and chunks[-1].text == "short"
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_unsupported_type_rejected():
    import pytest

    with pytest.raises(ValueError):
        read_pages("x.docx", b"")


def test_text_export_split_on_page_headers():
    text = "Cover\n" + "".join(f"Seite/Page {n} - Chapter\nbody {n}\n\n" for n in range(2, 7))
    pages = read_pages("manual.txt", text.encode())
    assert [p.number for p in pages] == [1, 2, 3, 4, 5, 6]
    assert "body 4" in pages[3].text


def test_form_feeds_split_pages():
    assert [p.number for p in read_pages("m.txt", b"a\fb\fc")] == [1, 2, 3]


def test_text_without_page_markers_stays_one_page():
    assert len(read_pages("m.txt", b"see page 4 for details\n\nnothing else")) == 1
