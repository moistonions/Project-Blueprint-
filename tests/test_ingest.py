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
