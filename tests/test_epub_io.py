"""
tests/test_epub_io.py
---------------------
Unit tests for epub_io: TOC flattening, title resolution, end-to-end
chapter extraction against a built EPUB fixture, and index-based selection.
"""
from bs4 import BeautifulSoup
from ebooklib import epub

import epub_io
from epub_io import Chapter, extract_chapters, select_chapters


def _build_epub(tmp_path, docs, toc=None):
    """docs: list of (file_name, html). Returns the written .epub path."""
    book = epub.EpubBook()
    book.set_identifier("id123")
    book.set_title("Fixture Book")
    book.set_language("en")
    items = []
    for name, html in docs:
        it = epub.EpubHtml(title=name, file_name=name, lang="en")
        it.content = html
        book.add_item(it)
        items.append(it)
    # An explicit toc is passed verbatim; otherwise leave the TOC empty so
    # title resolution falls back to <h1> headings. (tuple(items) would
    # round-trip into a TOC that maps each doc to its *filename*, since the
    # EpubHtml items here carry title=name — which would shadow the headings.)
    book.toc = toc if toc is not None else ()
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + items
    out = tmp_path / "fixture.epub"
    epub.write_epub(str(out), book)
    return str(out)


BODY = "<p>" + ("word " * 80) + "</p>"  # > 200 chars of text


class TestFlattenToc:
    def test_maps_basename_to_title(self):
        toc = (epub.Link("chap_01.xhtml", "The Beginning", "c1"),)
        assert epub_io._flatten_toc(toc)["chap_01.xhtml"] == "The Beginning"

    def test_strips_anchor_and_path(self):
        toc = (epub.Link("text/chap_01.xhtml#frag", "Anchored", "c1"),)
        assert epub_io._flatten_toc(toc)["chap_01.xhtml"] == "Anchored"

    def test_walks_nested_sections(self):
        nested = ((epub.Section("Part I"),
                   (epub.Link("chap_02.xhtml", "Deep Title", "c2"),)),)
        assert epub_io._flatten_toc(nested)["chap_02.xhtml"] == "Deep Title"


class TestResolveTitle:
    def test_prefers_toc(self):
        soup = BeautifulSoup("<h1>Heading</h1>", "html.parser")
        title = epub_io._resolve_title(
            "chap_01.xhtml", soup, {"chap_01.xhtml": "TOC Title"}, 50
        )
        assert title == "TOC Title"

    def test_falls_back_to_heading(self):
        soup = BeautifulSoup("<h2>My Heading</h2><p>body</p>", "html.parser")
        assert epub_io._resolve_title("x.xhtml", soup, {}, 50) == "My Heading"

    def test_falls_back_to_text_preview(self):
        soup = BeautifulSoup("<p>Once upon a midnight dreary</p>", "html.parser")
        assert epub_io._resolve_title("x.xhtml", soup, {}, 10) == "Once upon"


class TestExtractChapters:
    def test_extracts_and_indexes_contiguously(self, tmp_path):
        path = _build_epub(tmp_path, [
            ("chap_01.xhtml", f"<h1>One</h1>{BODY}"),
            ("chap_02.xhtml", f"<h1>Two</h1>{BODY}"),
        ])
        chapters = extract_chapters(path)
        assert [c.index for c in chapters] == [0, 1]
        assert [c.title for c in chapters] == ["One", "Two"]

    def test_skips_tiny_documents(self, tmp_path):
        path = _build_epub(tmp_path, [
            ("cover.xhtml", "<p>x</p>"),                 # < 200 chars → skipped
            ("chap_01.xhtml", f"<h1>Real</h1>{BODY}"),
        ])
        chapters = extract_chapters(path)
        assert len(chapters) == 1
        assert chapters[0].title == "Real"
        assert chapters[0].index == 0

    def test_uses_toc_title_when_present(self, tmp_path):
        toc = (epub.Link("chap_01.xhtml", "Chapter From TOC", "c1"),)
        path = _build_epub(
            tmp_path, [("chap_01.xhtml", f"<h1>Heading</h1>{BODY}")], toc=toc
        )
        assert extract_chapters(path)[0].title == "Chapter From TOC"


class TestSelectChapters:
    CH = [Chapter(i, f"c{i}.xhtml", f"T{i}", "body") for i in range(4)]

    def test_none_returns_all(self):
        assert select_chapters(self.CH, None) == self.CH

    def test_filters_and_preserves_order(self):
        out = select_chapters(self.CH, [2, 0])
        assert [c.index for c in out] == [0, 2]

    def test_ignores_unknown_indices(self):
        out = select_chapters(self.CH, [1, 99])
        assert [c.index for c in out] == [1]
