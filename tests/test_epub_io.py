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


def _build_epub(tmp_path, docs, toc=None, spine_names=None):
    """docs: list of (file_name, html). Returns the written .epub path.

    spine_names reorders the spine (reading order) independently of docs
    (manifest order); default keeps the two aligned."""
    book = epub.EpubBook()
    book.set_identifier("id123")
    book.set_title("Fixture Book")
    book.set_language("en")
    items = {}
    for name, html in docs:
        it = epub.EpubHtml(title=name, file_name=name, lang="en")
        it.content = html
        book.add_item(it)
        items[name] = it
    # An explicit toc is passed verbatim; otherwise leave the TOC empty so
    # title resolution falls back to <h1> headings. (tuple(items) would
    # round-trip into a TOC that maps each doc to its *filename*, since the
    # EpubHtml items here carry title=name — which would shadow the headings.)
    book.toc = toc if toc is not None else ()
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    order = spine_names if spine_names is not None else [n for n, _ in docs]
    book.spine = ["nav"] + [items[n] for n in order]
    out = tmp_path / "fixture.epub"
    epub.write_epub(str(out), book)
    return str(out)


def _make_epub_with_hr(tmp_path, hr_first=False):
    """EPUB with one chapter containing an <hr/> scene break. hr_first puts
    the <hr> before any text, so a mutate-soup-first extraction would leak
    the sentinel into the preview-fallback title."""
    body = "<p>" + "word " * 60 + "</p><hr/><p>" + "word " * 60 + "</p>"
    if hr_first:
        body = "<hr/>" + body
    return _build_epub(tmp_path, [("c1.xhtml", body)])


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

    def test_follows_spine_order_not_manifest_order(self, tmp_path):
        # Publisher EPUBs may list front matter last in the manifest even
        # though the spine puts it first (books/mattering_too). Reading
        # order is defined by the spine, and extraction must follow it.
        path = _build_epub(
            tmp_path,
            docs=[
                ("chap_01.xhtml", f"<h1>One</h1>{BODY}"),
                ("chap_02.xhtml", f"<h1>Two</h1>{BODY}"),
                ("intro.xhtml", f"<h1>Intro</h1>{BODY}"),
            ],
            spine_names=["intro.xhtml", "chap_01.xhtml", "chap_02.xhtml"],
        )
        chapters = extract_chapters(path)
        assert [c.title for c in chapters] == ["Intro", "One", "Two"]
        assert [c.index for c in chapters] == [0, 1, 2]

    def test_falls_back_to_manifest_when_spine_unresolvable(self, tmp_path):
        # A malformed spine (idrefs that resolve to nothing) must not lose
        # the book — extraction falls back to manifest order.
        path = _build_epub(tmp_path, [
            ("chap_01.xhtml", f"<h1>One</h1>{BODY}"),
            ("chap_02.xhtml", f"<h1>Two</h1>{BODY}"),
        ])
        book = epub.read_epub(path)
        book.spine = [("ghost", "yes")]
        docs = epub_io._spine_documents(book)
        assert [d.get_name() for d in docs] == \
            ["chap_01.xhtml", "chap_02.xhtml", "nav.xhtml"]

    def test_uses_toc_title_when_present(self, tmp_path):
        toc = (epub.Link("chap_01.xhtml", "Chapter From TOC", "c1"),)
        path = _build_epub(
            tmp_path, [("chap_01.xhtml", f"<h1>Heading</h1>{BODY}")], toc=toc
        )
        assert extract_chapters(path)[0].title == "Chapter From TOC"


class TestSceneBreaks:
    def test_sentinel_constant_exists(self):
        assert epub_io.SCENE_BREAK == "␞"

    def test_mark_scene_breaks_default_off(self, tmp_path):
        # Build a tiny EPUB with an <hr> and assert no sentinel by default.
        path = _make_epub_with_hr(tmp_path)
        chapters = epub_io.extract_chapters(str(path))
        assert epub_io.SCENE_BREAK not in chapters[0].text

    def test_mark_scene_breaks_inserts_sentinel(self, tmp_path):
        path = _make_epub_with_hr(tmp_path)
        chapters = epub_io.extract_chapters(str(path), mark_scene_breaks=True)
        assert epub_io.SCENE_BREAK in chapters[0].text

    def test_marking_keeps_indices_and_titles_stable(self, tmp_path):
        # hr before any text: the naive approach (mutate soup first) would
        # leak the sentinel into the preview-fallback title, and the length
        # change could flip the MIN_CHAPTER_CHARS filter — misaligning the
        # worker's (marked) indices against the app's (unmarked) list.
        path = _make_epub_with_hr(tmp_path, hr_first=True)
        plain = epub_io.extract_chapters(str(path))
        marked = epub_io.extract_chapters(str(path), mark_scene_breaks=True)
        assert [(c.index, c.title) for c in marked] == \
            [(c.index, c.title) for c in plain]
        assert all(epub_io.SCENE_BREAK not in c.title for c in marked)

    def test_separator_only_lines_become_sentinels(self):
        marked = epub_io._mark_separator_lines("before\n* * *\n———\nafter")
        assert marked == f"before\n{epub_io.SCENE_BREAK}\n{epub_io.SCENE_BREAK}\nafter"

    def test_prose_lines_are_untouched(self):
        text = "a *starred* word\n- a list item"
        assert epub_io._mark_separator_lines(text) == text


class TestSelectChapters:
    CH = [Chapter(i, f"c{i}.xhtml", f"T{i}", "body") for i in range(4)]

    def test_none_returns_all(self):
        assert select_chapters(self.CH, None) == self.CH

    def test_returns_chapters_in_given_order(self):
        out = select_chapters(self.CH, [2, 0])
        assert [c.index for c in out] == [2, 0]

    def test_sorted_indices_keep_document_order(self):
        # app.py sends sorted indices; its behaviour must stay identical.
        out = select_chapters(self.CH, [0, 2])
        assert [c.index for c in out] == [0, 2]

    def test_ignores_unknown_indices(self):
        out = select_chapters(self.CH, [1, 99])
        assert [c.index for c in out] == [1]


class TestNavOnlyTitles:
    def test_nav_only_epub_resolves_real_names(self, tmp_path):
        """ebooklib >= 0.20 parses the EPUB3 nav TOC into book.toc, so a
        book with an EMPTY NCX still gets real chapter names through the
        existing TOC -> heading -> preview chain. Pin it: if a future
        ebooklib regresses this, the title would fall back to a text
        preview ('word word word ...') and this test fails."""
        book = epub.EpubBook()
        book.set_identifier("id123")
        book.set_title("Fixture Book")
        book.set_language("en")
        c1 = epub.EpubHtml(file_name="c1.xhtml", lang="en")
        c1.content = BODY                      # no headings, no <title>
        book.add_item(c1)
        nav = epub.EpubHtml(file_name="nav.xhtml", lang="en")
        nav.content = (
            '<nav epub:type="toc"><ol>'
            '<li><a href="c1.xhtml">Real Name</a></li></ol></nav>'
        )
        nav.properties.append("nav")
        book.add_item(nav)
        book.add_item(epub.EpubNcx())          # NCX present but empty
        book.spine = [c1]
        path = tmp_path / "navonly.epub"
        epub.write_epub(str(path), book)

        chapters = extract_chapters(str(path))
        assert [c.title for c in chapters] == ["Real Name"]

    def test_nav_title_wins_over_ncx(self, tmp_path):
        """When a book ships BOTH an NCX and a nav TOC with conflicting
        titles, ebooklib 0.20 hands us the NAV title in book.toc. Spec
        section 5 asks this precedence be pinned — it is the surprising
        half of the amendment, and a future ebooklib flipping it would
        silently change every chapter name in such books."""
        book = epub.EpubBook()
        book.set_identifier("id123")
        book.set_title("Fixture Book")
        book.set_language("en")
        c1 = epub.EpubHtml(file_name="c1.xhtml", lang="en")
        c1.content = BODY                      # no headings, no <title>
        book.add_item(c1)
        nav = epub.EpubHtml(file_name="nav.xhtml", lang="en")
        nav.content = (
            '<nav epub:type="toc"><ol>'
            '<li><a href="c1.xhtml">Nav Name</a></li></ol></nav>'
        )
        nav.properties.append("nav")
        book.add_item(nav)
        book.toc = (epub.Link("c1.xhtml", "NCX Name", "c1"),)
        book.add_item(epub.EpubNcx())          # writes 'NCX Name' to toc.ncx
        book.spine = [c1]
        path = tmp_path / "both.epub"
        epub.write_epub(str(path), book)

        chapters = extract_chapters(str(path))
        assert [c.title for c in chapters] == ["Nav Name"]


class TestFlattenInline:
    """Inline markup must not split a sentence — or a word — into lines.

    soup.get_text(separator="\\n") puts its separator between adjacent
    string nodes, so <i>/<span>/<b> inside a paragraph used to shred the
    text sent to the LLM. Block structure must survive untouched.
    """

    def call(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        epub_io._flatten_inline(soup)
        return soup.get_text(separator="\n").strip()

    def plain(self, html: str) -> str:
        return BeautifulSoup(html, "html.parser").get_text(
            separator="\n").strip()

    def test_sentence_split_by_italic_is_rejoined(self):
        html = "<p>I said, and signed <i>I want to throw my shit</i>.</p>"
        assert self.plain(html) == "I said, and signed \nI want to throw my shit\n."
        assert self.call(html) == "I said, and signed I want to throw my shit."

    def test_word_split_by_markup_is_rejoined(self):
        # Without soup.smooth() the replaced string stays a separate node
        # and the newline survives — this test is what catches that.
        assert self.call("<p>hyper<i>text</i> rules.</p>") == "hypertext rules."

    def test_paragraphs_still_separate(self):
        assert self.call("<p>One.</p><p>Two.</p>") == "One.\nTwo."

    def test_br_still_breaks_the_line(self):
        # <br> is "inline" per the HTML spec but is a break the author
        # intended; flattening it would run poetry and addresses together.
        assert self.call("<p>Line one<br/>Line two</p>") == "Line one\nLine two"

    def test_scene_separator_inside_inline_tag_keeps_its_own_line(self):
        assert self.call("<p>a</p><p><i>* * *</i></p><p>b</p>") == "a\n* * *\nb"

    def test_nested_inline_tags_flatten_once(self):
        assert self.call("<p>x <span>y <b>z</b></span> w</p>") == "x y z w"

    def test_heading_split_by_markup_is_whole(self):
        assert self.call("<h1>Conscious <i>Leadership</i> Now</h1>") == \
            "Conscious Leadership Now"

    def test_block_elements_include_br_and_skeleton(self):
        for name in ("p", "div", "br", "hr", "li", "body", "script"):
            assert name in epub_io._BLOCK_ELEMENTS
        for name in ("i", "b", "span", "em", "a", "sup"):
            assert name not in epub_io._BLOCK_ELEMENTS


class TestExtractFlattensInlineMarkup:
    """End-to-end: the text handed to the worker must not be shredded."""

    def test_chapter_text_has_no_markup_split_lines(self, tmp_path):
        html = (
            "<html><body>"
            "<p>She read <i>The Long Goodbye</i> twice.</p>"
            f"{BODY}"
            "</body></html>"
        )
        path = _build_epub(tmp_path, [("c1.xhtml", html)])
        text = extract_chapters(path)[0].text
        assert "She read The Long Goodbye twice." in text
        assert "The Long Goodbye\n" not in text

    def test_split_word_is_rejoined_in_chapter_text(self, tmp_path):
        html = f"<html><body><p>hyper<i>text</i> matters.</p>{BODY}</body></html>"
        path = _build_epub(tmp_path, [("c1.xhtml", html)])
        assert "hypertext matters." in extract_chapters(path)[0].text

    def test_title_from_heading_is_not_truncated_by_markup(self, tmp_path):
        # Before the fix the heading extracted as 'Conscious \nLeadership...'
        # and the title came out cut at the markup boundary.
        html = (
            "<html><body><h1>Conscious <i>Leadership</i> Now</h1>"
            f"{BODY}</body></html>"
        )
        path = _build_epub(tmp_path, [("c1.xhtml", html)])
        assert extract_chapters(path)[0].title == "Conscious Leadership Now"

    def test_scene_break_marking_still_works_through_inline_markup(self, tmp_path):
        html = (
            "<html><body><p>before</p><p><i>* * *</i></p><p>after</p>"
            f"{BODY}</body></html>"
        )
        path = _build_epub(tmp_path, [("c1.xhtml", html)])
        marked = extract_chapters(path, mark_scene_breaks=True)[0].text
        assert epub_io.SCENE_BREAK in marked

    def test_marked_and_plain_reads_still_agree_on_index_and_title(self, tmp_path):
        # The parity that selected_chapters depends on: app.py extracts
        # unmarked, worker.py extracts marked, and the two must line up.
        html = (
            "<html><body><h1>Chapter <i>One</i></h1>"
            "<p>text with <span>inline</span> markup.</p>"
            f"{BODY}</body></html>"
        )
        path = _build_epub(tmp_path, [("c1.xhtml", html)])
        plain = extract_chapters(path)
        marked = extract_chapters(path, mark_scene_breaks=True)
        assert [(c.index, c.title) for c in plain] == \
            [(c.index, c.title) for c in marked]
