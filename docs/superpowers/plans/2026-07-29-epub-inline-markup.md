# Inline Markup Must Not Shred Sentences — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `epub_io` splitting sentences (and words) at inline HTML markup, so the LLM receives whole sentences instead of fragments it fabricates text to bridge.

**Architecture:** Add a `_BLOCK_ELEMENTS` frozenset (the HTML block-level set, plus `<br>` and the document skeleton) and a `_flatten_inline(soup)` helper that replaces every non-block element with its text and calls `soup.smooth()`. Call it once in `extract_chapters` immediately after parsing, before any `get_text` — so the length filter, the title, and the scene-marked text all see the same flattened tree.

**Tech Stack:** Python 3.14, BeautifulSoup 4.15 (`html.parser`), ebooklib 0.20, pytest.

**Spec:** `docs/superpowers/specs/2026-07-29-epub-inline-markup-design.md`

## Global Constraints

- `epub_io.py` imports ebooklib / bs4 only — never Qt, `app`, `worker`, or `settings` (CLAUDE.md rule 1). This change adds **no** imports.
- Max line length 100. Lint gate: `pycodestyle --config=.pycodestyle --statistics <files>` must introduce **no new violations**. `epub_io.py` and `tests/test_epub_io.py` are both currently **clean** — they must stay clean. Never edit `.pycodestyle`. Note `.pycodestyle` sets `ignore = E221`, which REPLACES the default ignore list and so enables **both W503 and W504** — a multi-line boolean cannot break at its operators in either direction; use intermediate variables or early returns instead.
- Test suite: `python -m pytest tests/ -q`. Exactly one pre-existing failure is expected and is NOT ours: `test_settings.py::TestOllamaTimeout::test_defaults_when_missing`. Before this plan the suite is **338 passed, 1 failed**.
- After any edit touching a class boundary run `grep -n "^class " *.py` and compare against the CLAUDE.md list. This plan adds no classes.
- Python environment: uv venv — if anything needs installing use `uv pip install`, never bare `pip`. Nothing needs installing: `smooth()` is available under the existing `beautifulsoup4>=4.12` floor (4.15.0 installed).
- Stage the exact files each task lists. **Never** `git add -A` / `git add .` / `git commit -a` — `docs/todo.txt` and `.gitignore` are modified in the working tree and belong to the user.
- Chapter-count change is EXPECTED and accepted: exactly one book's `nav.xhtml` falls below `MIN_CHAPTER_CHARS` (209 → 190 chars). Library-wide 559 → 558 chapters. Do not add special-casing to prevent it.

---

### Task 1: `_flatten_inline` helper + `_BLOCK_ELEMENTS`

Pure tree transformation, unit-tested on hand-built HTML. No call site yet, so `extract_chapters` behaviour is unchanged after this task and the full suite must stay exactly at its baseline.

**Files:**
- Modify: `epub_io.py` (add both after the `_SEPARATOR_LINE` block, ~line 36, before `@dataclass class Chapter`)
- Test: `tests/test_epub_io.py` (append a new test class at the end of the file)

**Interfaces:**
- Consumes: `BeautifulSoup` (already imported at `epub_io.py:19`).
- Produces: `epub_io._BLOCK_ELEMENTS: frozenset[str]` and `epub_io._flatten_inline(soup) -> None` (mutates in place, returns None). Task 2 calls `_flatten_inline`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_epub_io.py`. The module already imports `epub_io` (line 10) and `BeautifulSoup` (line 7):

```python
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
```

- [ ] **Step 2: Run to verify the tests fail**

Run: `python -m pytest tests/test_epub_io.py::TestFlattenInline -v`
Expected: every test ERRORs with `AttributeError: module 'epub_io' has no attribute '_flatten_inline'` (and `_BLOCK_ELEMENTS`).

- [ ] **Step 3: Implement**

In `epub_io.py`, insert after the `_SEPARATOR_LINE` definition (which ends with `)` around line 36) and before `@dataclass`:

```python
# HTML block-level elements — the closed set from the HTML standard. Every
# element NOT in here is treated as inline and flattened by
# _flatten_inline(), so a tag we have never seen defaults to inline. That
# is the safe direction: missing an inline tag re-splits sentences,
# whereas treating a rare tag as inline merely joins adjacent text.
#
# Two deliberate additions to the standard block list:
#   <br>  — the standard calls it inline, but it is a line break the
#           author intended; flattening it would run verse together.
#   document skeleton and table internals — unwrapping these would merge
#           table cells or leak stylesheet text into the prose.
_BLOCK_ELEMENTS: frozenset[str] = frozenset({
    "address", "article", "aside", "blockquote", "canvas", "dd", "div",
    "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form",
    "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main",
    "nav", "noscript", "ol", "p", "pre", "section", "table", "tfoot",
    "ul", "video",
    "br", "html", "head", "body", "title", "script", "style", "meta",
    "link", "tr", "td", "th", "thead", "tbody", "caption", "col",
    "colgroup",
})


def _flatten_inline(soup) -> None:
    """Replace inline elements with their text, in place.

    get_text(separator="\\n") inserts its separator between adjacent
    string nodes, so `<i>`/`<span>`/`<b>` inside a paragraph split the
    sentence — and sometimes a word ("hyper<i>text</i>") — across lines.
    Flattening them first keeps the sentence whole while leaving block
    structure alone.

    smooth() is required, not cosmetic: replace_with() leaves the new
    string as its own node, so without the merge the separator is still
    inserted and this function silently does nothing.
    """
    for tag in [t for t in soup.find_all(True)
                if t.name not in _BLOCK_ELEMENTS]:
        tag.replace_with(tag.get_text())
    soup.smooth()
```

Note the list comprehension is materialised **before** mutating — iterating
`find_all` lazily while replacing nodes would skip elements.

- [ ] **Step 4: Run the new tests, then the full suite + lint**

Run: `python -m pytest tests/test_epub_io.py::TestFlattenInline -v && python -m pytest tests/ -q && pycodestyle --config=.pycodestyle --statistics epub_io.py tests/test_epub_io.py`
Expected: the 8 new tests PASS; full suite **346 passed, 1 failed** (the pre-existing `test_settings` one only — 338 baseline + 8 new, with no previously-passing test broken); lint clean for both files.

- [ ] **Step 5: Commit**

```bash
git add epub_io.py tests/test_epub_io.py
git commit -m "feat(epub_io): _flatten_inline collapses inline markup

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Call it from `extract_chapters`

**Files:**
- Modify: `epub_io.py` (`extract_chapters`, the `for item in _spine_documents(book):` loop — the `BeautifulSoup(...)` line, ~line 133)
- Test: `tests/test_epub_io.py` (append a second class after `TestFlattenInline`)

**Interfaces:**
- Consumes: `_flatten_inline(soup)` from Task 1.
- Produces: `extract_chapters` returning chapter text with inline markup flattened. Nothing downstream changes signature.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_epub_io.py`. `_build_epub(tmp_path, docs)` is defined at line 14 and takes `docs` as a list of `(file_name, html)`; `BODY` (line 53) is 80 repetitions of "word " wrapped in `<p>`, giving > 200 chars so the document clears `MIN_CHAPTER_CHARS`:

```python
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
```

- [ ] **Step 2: Run to verify the failures**

Run: `python -m pytest tests/test_epub_io.py::TestExtractFlattensInlineMarkup -v`
Expected: `test_chapter_text_has_no_markup_split_lines`, `test_split_word_is_rejoined_in_chapter_text`, and `test_title_from_heading_is_not_truncated_by_markup` FAIL (the text still contains the markup-induced newlines). The two scene-break/parity tests already PASS — they pin behaviour that must not regress.

- [ ] **Step 3: Implement**

In `epub_io.extract_chapters`, the loop currently begins:

```python
    for item in _spine_documents(book):
        soup = BeautifulSoup(item.get_content(), "html.parser")
```

Add the flatten call immediately after the parse, so the length filter, the
title, and the scene-marked text all read the same tree:

```python
    for item in _spine_documents(book):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        # Before ANY get_text: inline markup otherwise splits sentences
        # and words across lines. Doing it once here keeps the length
        # filter, the title, and the marked text consistent with each
        # other — flattening per-read would let them disagree and break
        # the app/worker index parity selected_chapters relies on.
        _flatten_inline(soup)
```

Change nothing else in the function.

- [ ] **Step 4: Run tests + lint**

Run: `python -m pytest tests/ -q && pycodestyle --config=.pycodestyle --statistics epub_io.py tests/test_epub_io.py`
Expected: **351 passed, 1 failed** (the pre-existing `test_settings` one — 346 after Task 1 plus the 5 new here). All six pre-existing `test_epub_io.py` classes still green — especially `TestSceneBreaks::test_marking_keeps_indices_and_titles_stable`. Lint clean.

- [ ] **Step 5: Verify against the real library**

This is the acceptance check the unit tests cannot give. Run:

```bash
python - <<'PYEOF'
import glob
import epub_io
tot = chaps = 0
for b in sorted(glob.glob("books/*.epub")):
    try:
        chs = epub_io.extract_chapters(b, 50)
    except Exception as exc:
        print(f"FAILED {b}: {exc}")
        continue
    chaps += len(chs)
    for c in chs:
        tot += sum(1 for ln in c.text.split("\n")
                   if ln.strip() and (ln.strip()[0].islower()
                                      or ln.strip() in {".", ",", "?", "!"}))
print(f"chapters={chaps}  fragment_lines={tot}")
PYEOF
```

Expected: **no book raises**, `chapters=558` (one fewer than today's 559 — a `nav.xhtml` correctly dropping below `MIN_CHAPTER_CHARS`), and `fragment_lines` around **16,277**, down from 34,002. The residual is hard-wrapped source text, which is explicitly out of scope. If a book raises, stop and report — do not add a try/except to `epub_io`.

- [ ] **Step 6: Commit**

```bash
git add epub_io.py tests/test_epub_io.py
git commit -m "fix(epub_io): flatten inline markup so sentences arrive whole

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Documentation

**Files:**
- Modify: `CLAUDE.md` (file-map row for `epub_io.py`)
- Modify: `README.md` (file-tree entry for `epub_io.py`)
- Modify: `docs/todo.txt` (mark the in-progress item done)

**Interfaces:** none — docs only.

- [ ] **Step 1: CLAUDE.md — file map**

The `epub_io.py` row currently reads:

```
| `epub_io.py` | EPUB → ordered `Chapter` list (titles via TOC→heading→preview); opt-in `mark_scene_breaks` scene-break sentinel; shared by app & worker | For chapter extraction/title logic |
```

Replace the description cell with:

```
EPUB → ordered `Chapter` list (titles via TOC→heading→preview); inline markup flattened so sentences are not split across lines; opt-in `mark_scene_breaks` scene-break sentinel; shared by app & worker
```

- [ ] **Step 2: README.md — file tree**

The `epub_io.py` entry currently reads:

```markdown
├── epub_io.py            EPUB → ordered Chapter list (titles from the book's
│                         TOC — NCX and/or EPUB3 nav — then headings, then a
│                         text preview; scene breaks)
```

Replace with:

```markdown
├── epub_io.py            EPUB → ordered Chapter list (titles from the book's
│                         TOC — NCX and/or EPUB3 nav — then headings, then a
│                         text preview; inline markup flattened; scene breaks)
```

- [ ] **Step 3: docs/todo.txt**

Replace the line:

```
- epub_io.py:140 shreds sentences at inline markup  -> IN PROGRESS
```

with:

```
- epub_io.py shreds sentences at inline markup  -> DONE
```

Leave the remaining lines of that entry, and the separate hard-wrapped-source entry below it, untouched.

- [ ] **Step 4: Verify**

Run: `python -m pytest tests/ -q && grep -c "inline markup" CLAUDE.md README.md`
Expected: 351 passed, 1 pre-existing failure; each file reports at least 1.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md README.md docs/todo.txt
git commit -m "docs: epub_io flattens inline markup

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
