# Sliding-Window Context Carry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve cross-chunk continuity when a chapter is split into multiple chunks, via two user-selectable carry mechanisms — a source-derived proper-noun protection list ("glossary") and a scene-gated prose tail — threaded into the body-producing LLM call.

**Architecture:** A per-run `carry_mode` (`"off"` / `"glossary"` / `"prose"` / `"both"`) chosen in the UI. **Glossary** is stateless: proper nouns are extracted from each chunk's *source* text (resume-trivial, no extra LLM calls) and injected as a "keep these exactly" instruction. **Prose** carries the last N words of the previous chunk's *output* into the next chunk, but only within a contiguous scene — scene breaks (detected in `epub_io` and carried as an out-of-text sentinel) reset the carry. Both feed a single delimited context block spliced into `build_translation_prompt` / `build_rewrite_prompt` / `build_summary_prompt` (whichever produces the saved body for the active mode).

**Tech Stack:** Python 3, regex (proper-noun heuristic — no new dependency), `bs4`/`ebooklib` (already used by `epub_io`), PyQt6, pytest.

## Global Constraints

- **Max line length 100; PEP 8.** `E221` suppressed. Run `pycodestyle --statistics *.py`.
- **Imports flow one way** (CLAUDE.md): `epub_io` imports `ebooklib`/`bs4` only — never Qt/app/worker/settings. `prompts` imports nothing. `worker` may import `epub_io`/`prompts`/`settings`.
- **Worker must never import Qt UI classes.**
- **Glossary is source-derived and stateless** — extracted per-chunk from the source; it requires **no** new resume state. Prose carry is within-chapter only, so resume (which restarts at a *chapter* boundary via `resume_from`/`prior_results`) needs no carry reconstruction either.
- **The scene-break sentinel must never reach a prompt or a written output file.** A test must assert this.
- **`epub_io` scene-marking is opt-in** (`mark_scene_breaks=False` default) so the common path and the app's chapter-list extraction are byte-for-byte unchanged.
- New per-run control follows the **inline** pattern of `_keyideas_lang_widget` in `app.py` (not a new `widgets.py` class).
- Carry attaches to the **body-producing call per mode**: `translate`→translation call; `summarise_rewrite` & `summarise_key_ideas`(es)→rewrite call; `summarise_only` & `summarise_key_ideas`(en)→summary call.
- Known pre-existing test failure to ignore: `tests/test_settings.py::TestOllamaTimeout::test_defaults_when_missing`.
- After any `worker.py`/`epub_io.py` edit touching a class boundary, run `grep -n "^class " *.py` and confirm expected classes remain (CLAUDE.md "Known historical issues" — `str_replace` has silently dropped `class` lines before).
- **Coordination with the language-level-detector plan:** these two plans are independently *designed* but not independently *mergeable* — both append a key to the same `_build_config()` dict literal, both add a row to `_add_options_group()`, both edit `worker.py` `run()`, `tests/test_worker.py`, and `CLAUDE.md`. Implement them **sequentially**; the second one rebases on the first and expects those shared spots to already have the other feature's line.

---

### Task 1: Proper-noun extraction (worker static helper)

A pure, dependency-free heuristic that pulls likely proper nouns from English source text. Lives beside the other text helpers (`_split_into_chunks`, `_strip_asterisk_markers`).

**Files:**
- Modify: `worker.py` (add static method to `ProcessingWorker`)
- Test: `tests/test_worker.py`

**Interfaces:**
- Produces: `ProcessingWorker.extract_proper_nouns(text: str) -> list[str]` — de-duplicated, order-preserved list of proper nouns. Multi-word capitalised spans always count; single capitalised words count only if they appear capitalised **more than once** (filters sentence-initial noise).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_worker.py — new class
class TestExtractProperNouns:
    def call(self, text):
        return ProcessingWorker.extract_proper_nouns(text)

    def test_multiword_name_captured(self):
        names = self.call("They met at New York Harbor before dawn.")
        assert "New York Harbor" in names

    def test_repeated_single_name_captured(self):
        names = self.call("Alice ran. Later, Alice returned home.")
        assert "Alice" in names

    def test_sentence_initial_common_word_filtered(self):
        # "The" and "Later" begin sentences once each → excluded
        names = self.call("The dog barked. Later it slept.")
        assert "The" not in names
        assert "Later" not in names

    def test_dedup_preserves_order(self):
        # Both names must recur so both survive the "singles need count ≥ 2"
        # rule; then assert uniqueness and first-appearance order.
        names = self.call("Paris is grand. Rome is old. Paris and Rome shine.")
        assert len(names) == len(set(names))  # de-duplicated
        assert names.index("Paris") < names.index("Rome")

    def test_empty_text(self):
        assert self.call("") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_worker.py::TestExtractProperNouns -v`
Expected: FAIL with `AttributeError: type object 'ProcessingWorker' has no attribute 'extract_proper_nouns'`

- [ ] **Step 3: Write minimal implementation**

In `worker.py`, add to `ProcessingWorker` next to `_strip_asterisk_markers`:

```python
    @staticmethod
    def extract_proper_nouns(text: str) -> list[str]:
        """Heuristic proper-noun list from English *source* text. Multi-word
        capitalised spans are always kept; single capitalised words are kept
        only when they occur capitalised more than once (filtering most
        sentence-initial noise). De-duplicated, order-preserved. No external
        dependency — reinforces the name-passthrough the prompts already ask
        for, so false negatives degrade gracefully."""
        singles = re.findall(r"\b[A-Z][a-zA-Z'’-]+\b", text)
        counts: dict[str, int] = {}
        for w in singles:
            counts[w] = counts.get(w, 0) + 1

        ordered: list[str] = []
        seen: set[str] = set()
        # Walk the text once so multi-word spans and qualifying singles keep
        # first-appearance order.
        for match in re.finditer(
            r"\b[A-Z][a-zA-Z'’-]+(?:\s+[A-Z][a-zA-Z'’-]+)*\b", text
        ):
            token = match.group(0)
            is_multiword = " " in token
            if not is_multiword and counts.get(token, 0) < 2:
                continue
            if token not in seen:
                seen.add(token)
                ordered.append(token)
        return ordered
```

Note: a multi-word span whose individual words also appear as singles is fine — the span is kept and the singles are independent entries only if they qualify on their own.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_worker.py::TestExtractProperNouns -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add worker.py tests/test_worker.py
git commit -m "feat: proper-noun extraction heuristic for glossary carry"
```

---

### Task 2: Context-block builder + prompt plumbing

A single delimited "continuity context" block, assembled from a name list and/or a prose tail, spliced into the three body-producing prompt builders just before the source/summary, with the operative instruction kept last.

**Files:**
- Modify: `prompts.py`
- Test: `tests/test_prompts.py`

**Interfaces:**
- Produces: `build_context_block(names: list[str] | None, prior_prose: str) -> str` — returns `""` when both inputs are empty; otherwise a labelled block ending with a newline.
- Modifies signatures (append keyword-only, default `""`): `build_translation_prompt(..., context_block: str = "")`, `build_rewrite_prompt(..., context_block: str = "")`, `build_summary_prompt(chapter_text, keep_pct, context_block: str = "")`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_prompts.py — new cases
from prompts import (
    build_context_block,
    build_translation_prompt,
    build_rewrite_prompt,
    build_summary_prompt,
)


class TestContextBlock:
    def test_empty_inputs_return_empty(self):
        assert build_context_block(None, "") == ""
        assert build_context_block([], "") == ""

    def test_names_listed(self):
        block = build_context_block(["Alice", "New York"], "")
        assert "Alice" in block and "New York" in block
        assert "do NOT translate" in block or "do not translate" in block.lower()

    def test_prose_tail_included(self):
        block = build_context_block(None, "…the end of the prior passage.")
        assert "the end of the prior passage" in block

    def test_translation_prompt_embeds_context_before_source(self):
        block = build_context_block(["Alice"], "")
        prompt = build_translation_prompt(
            "Hello.", "B1", 0, 5, context_block=block
        )
        assert "Alice" in prompt
        # context appears before the SOURCE TEXT section
        assert prompt.index("Alice") < prompt.index("SOURCE TEXT")

    def test_builders_accept_empty_context_unchanged(self):
        # default empty context must not inject the block label
        p = build_summary_prompt("Some text.", 50)
        assert "CONTINUITY CONTEXT" not in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_prompts.py::TestContextBlock -v`
Expected: FAIL with `ImportError: cannot import name 'build_context_block'`

- [ ] **Step 3: Write minimal implementation**

In `prompts.py`, add the builder and thread `context_block` into the three builders.

Add near the public builders:

```python
def build_context_block(names: list[str] | None, prior_prose: str) -> str:
    """Assemble a delimited continuity-context block from a proper-noun
    protection list and/or the tail of the previous chunk's output. Returns
    "" when both are empty. The block is read-only context — the builders
    that embed it keep the operative 'output only the new text' rule last."""
    names = names or []
    prior_prose = (prior_prose or "").strip()
    if not names and not prior_prose:
        return ""
    parts = [
        "CONTINUITY CONTEXT (read for consistency only — do NOT translate, "
        "repeat, summarise, or output this block):"
    ]
    if names:
        parts.append(
            "- Keep these names exactly as written: " + ", ".join(names) + "."
        )
    if prior_prose:
        parts.append(
            "- The preceding passage ended like this (continue smoothly, do "
            f"not repeat it): \"{prior_prose}\""
        )
    return "\n".join(parts) + "\n\n"
```

Then add `context_block: str = ""` to each builder and insert it. For `build_translation_prompt`, insert the block right before the `SOURCE TEXT` line:

```python
        f"REMINDER — you are writing for a CEFR {level} reader. Apply the language guidance strictly.\n\n"
        f"{context_block}"
        f"SOURCE TEXT (English):\n{chunk_text}\n"
```

For `build_rewrite_prompt`, insert before the `SOURCE SUMMARY` line:

```python
        f"- This is chapter {chapter_index + 1}.\n\n"
        f"{context_block}"
        f"SOURCE SUMMARY (English):\n{summary}\n"
```

For `build_summary_prompt`, insert before the `CHAPTER TEXT` line:

```python
        "Output only the condensed text.\n\n"
        f"{context_block}"
        f"CHAPTER TEXT:\n{chapter_text}\n"
```

Update the three signatures to accept `context_block: str = ""` (keyword arg with default — existing positional callers are unaffected).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_prompts.py -v`
Expected: PASS (new cases pass; existing prompt tests unaffected by the default-empty context).

- [ ] **Step 5: Commit**

```bash
git add prompts.py tests/test_prompts.py
git commit -m "feat: continuity-context block + prompt plumbing"
```

---

### Task 3: Scene-break sentinel in epub_io (opt-in)

Detect scene breaks (`<hr>` and separator-only paragraphs) and represent them as an out-of-text sentinel in `Chapter.text`, only when explicitly requested.

**Files:**
- Modify: `epub_io.py`
- Test: `tests/test_epub_io.py`

**Interfaces:**
- Produces: module constant `SCENE_BREAK = "␞"` (SYMBOL FOR RECORD SEPARATOR — will never occur in book prose).
- Modifies: `extract_chapters(path, preview_chars=50, mark_scene_breaks=False)` — when `mark_scene_breaks` is True, `<hr>` elements and separator-only lines in `Chapter.text` become a lone `SCENE_BREAK` paragraph; default False leaves text byte-identical to today.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_epub_io.py — new cases
import epub_io


class TestSceneBreaks:
    def test_sentinel_constant_exists(self):
        assert epub_io.SCENE_BREAK == "␞"

    def test_mark_scene_breaks_default_off(self, tmp_path):
        # Build a tiny EPUB with an <hr> and assert no sentinel by default.
        path = _make_epub_with_hr(tmp_path)  # helper below
        chapters = epub_io.extract_chapters(str(path))
        assert epub_io.SCENE_BREAK not in chapters[0].text

    def test_mark_scene_breaks_inserts_sentinel(self, tmp_path):
        path = _make_epub_with_hr(tmp_path)
        chapters = epub_io.extract_chapters(str(path), mark_scene_breaks=True)
        assert epub_io.SCENE_BREAK in chapters[0].text
```

Add this helper at module top of `tests/test_epub_io.py` (reuse the existing EPUB-building style already in that file if one is present; otherwise):

```python
def _make_epub_with_hr(tmp_path):
    from ebooklib import epub
    book = epub.EpubBook()
    book.set_identifier("id1")
    book.set_title("T")
    book.set_language("en")
    c = epub.EpubHtml(title="Ch1", file_name="c1.xhtml", lang="en")
    c.set_content(
        "<html><body><p>" + "word " * 60 + "</p><hr/><p>" +
        "word " * 60 + "</p></body></html>"
    )
    book.add_item(c)
    book.spine = ["nav", c]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    out = tmp_path / "t.epub"
    epub.write_epub(str(out), book)
    return out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_epub_io.py::TestSceneBreaks -v`
Expected: FAIL with `AttributeError: module 'epub_io' has no attribute 'SCENE_BREAK'`

- [ ] **Step 3: Write minimal implementation**

In `epub_io.py`, add the constant near `MIN_CHAPTER_CHARS`:

```python
# Out-of-prose marker for a scene break. The Unicode "symbol for record
# separator" never occurs in book text, so it round-trips safely and is
# stripped before any prompt or output write (see worker._split_into_chunks_with_scenes).
SCENE_BREAK = "␞"
```

Add a separator-line regex and a marking step. Add near the top imports:

```python
import re

_SEPARATOR_LINE = re.compile(r"^\s*(?:\*\s*){2,}\*?\s*$|^\s*[⁂*–—\-]{3,}\s*$")
```

In `extract_chapters`, change the signature and the per-document body:

```python
def extract_chapters(path: str, preview_chars: int = 50,
                     mark_scene_breaks: bool = False) -> list[Chapter]:
    """Read *path* and return its chapters in document order.

    When *mark_scene_breaks* is True, scene breaks (<hr> elements and
    separator-only lines like '* * *') are represented in Chapter.text as a
    lone SCENE_BREAK paragraph, for the worker's scene-gated prose carry.
    Default False keeps text byte-identical to a plain extraction."""
    book = epub.read_epub(path)
    toc_map = _flatten_toc(book.toc)
    chapters: list[Chapter] = []
    idx = 0
    for item in book.get_items():
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")
        if mark_scene_breaks:
            for hr in soup.find_all("hr"):
                hr.replace_with(f"\n{SCENE_BREAK}\n")
        text = soup.get_text(separator="\n").strip()
        if mark_scene_breaks:
            text = _mark_separator_lines(text)
        if len(text) > MIN_CHAPTER_CHARS:
            title = _resolve_title(item.get_name(), soup, toc_map, preview_chars)
            chapters.append(Chapter(idx, item.get_name(), title, text))
            idx += 1
    return chapters
```

Add the helper:

```python
def _mark_separator_lines(text: str) -> str:
    """Replace separator-only lines ('* * *', '⁂', '———') with SCENE_BREAK."""
    out = []
    for line in text.split("\n"):
        out.append(SCENE_BREAK if _SEPARATOR_LINE.match(line) else line)
    return "\n".join(out)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_epub_io.py -v`
Expected: PASS (existing extraction tests unaffected — default is off).

- [ ] **Step 5: Class-boundary guard + commit**

Run: `grep -n "^class " *.py` → Expected: `epub_io.py: class Chapter` present.

```bash
git add epub_io.py tests/test_epub_io.py
git commit -m "feat: opt-in scene-break sentinel in epub_io"
```

---

### Task 4: Scene-aware chunk splitter

Splits a chapter into `(chunk_text, starts_new_scene)` pairs, reusing the existing tested `_split_into_chunks` per scene segment and stripping all sentinels.

**Files:**
- Modify: `worker.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: `ProcessingWorker._split_into_chunks` (unchanged), `epub_io.SCENE_BREAK`.
- Produces: `ProcessingWorker._split_into_chunks_with_scenes(text, max_words=2000) -> list[tuple[str, bool]]`. `starts_new_scene` is True only for the first chunk of a scene segment after the first segment. No chunk text contains `SCENE_BREAK`.

- [ ] **Step 1: Write the failing test**

```python
class TestSplitWithScenes:
    def _para(self, n):
        return " ".join(["word"] * n)

    def call(self, text, max_words=2000):
        return ProcessingWorker._split_into_chunks_with_scenes(text, max_words)

    def test_no_sentinel_behaves_like_plain_split(self):
        text = "\n\n".join([self._para(800)] * 3)
        pairs = self.call(text, max_words=2000)
        # same chunk count as the plain splitter, none marked new-scene
        assert len(pairs) == 2
        assert all(flag is False for _, flag in pairs)

    def test_scene_break_marks_next_chunk(self):
        from epub_io import SCENE_BREAK
        text = f"{self._para(50)}\n\n{SCENE_BREAK}\n\n{self._para(50)}"
        pairs = self.call(text, max_words=2000)
        assert len(pairs) == 2
        assert pairs[0][1] is False
        assert pairs[1][1] is True

    def test_sentinel_never_in_chunk_text(self):
        from epub_io import SCENE_BREAK
        text = f"{self._para(50)}\n\n{SCENE_BREAK}\n\n{self._para(50)}"
        for chunk, _ in self.call(text):
            assert SCENE_BREAK not in chunk
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_worker.py::TestSplitWithScenes -v`
Expected: FAIL with `AttributeError: ... no attribute '_split_into_chunks_with_scenes'`

- [ ] **Step 3: Write minimal implementation**

In `worker.py`, add next to `_split_into_chunks`:

```python
    @staticmethod
    def _split_into_chunks_with_scenes(
        text: str, max_words: int = 2000
    ) -> list[tuple[str, bool]]:
        """Split *text* into (chunk, starts_new_scene) pairs. Scene breaks
        (epub_io.SCENE_BREAK paragraphs) hard-segment the text; within each
        segment the existing word-budget splitter applies. starts_new_scene
        is True only for the first chunk of a segment after the first.
        SCENE_BREAK never appears in returned chunk text."""
        from epub_io import SCENE_BREAK
        segments = [s for s in text.split(SCENE_BREAK) if s.strip()] or [text]
        out: list[tuple[str, bool]] = []
        for seg_idx, segment in enumerate(segments):
            for chunk_idx, chunk in enumerate(
                ProcessingWorker._split_into_chunks(segment, max_words)
            ):
                out.append((chunk, chunk_idx == 0 and seg_idx > 0))
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_worker.py::TestSplitWithScenes -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add worker.py tests/test_worker.py
git commit -m "feat: scene-aware chunk splitter"
```

---

### Task 5: Wire carry into the worker pipeline

Read `carry_mode`, extract chapters with scene-marking when prose carry is on, switch the chunk loop to the scene-aware splitter, and assemble + inject the context block per chunk into the right body call. This is the integration task; it ends with the full app exercising the feature.

**Files:**
- Modify: `worker.py` (`run()` chapter/chunk loop)
- Test: `tests/test_worker.py` (context-assembly helper extracted for testability)

**Interfaces:**
- Consumes: `extract_proper_nouns` (Task 1), `build_context_block` (Task 2), `_split_into_chunks_with_scenes` (Task 4), `epub_io.extract_chapters(..., mark_scene_breaks=...)` (Task 3).
- Produces: `ProcessingWorker._carry_context(carry_mode, source_chunk, prior_output, starts_new_scene, tail_words=120) -> str` — returns the context block string (possibly `""`) for one chunk.

- [ ] **Step 1: Write the failing test for the assembly helper**

```python
class TestCarryContext:
    def call(self, mode, src, prior, new_scene):
        return ProcessingWorker._carry_context(mode, src, prior, new_scene)

    def test_off_returns_empty(self):
        assert self.call("off", "Alice went home.", "prev output", False) == ""

    def test_glossary_includes_names_not_prose(self):
        block = self.call("glossary", "Alice met Bob today and Alice left.",
                          "prev output text", False)
        assert "Alice" in block
        assert "prev output text" not in block

    def test_prose_includes_tail_not_names(self):
        block = self.call("prose", "Alice met Bob and Alice waved.",
                          "the prior passage ended here", False)
        assert "the prior passage ended here" in block
        assert "Alice" not in block

    def test_prose_suppressed_on_new_scene(self):
        block = self.call("prose", "text", "prior passage", True)
        assert block == ""

    def test_both_includes_names_and_prose(self):
        block = self.call("both", "Alice and Alice again.", "prior tail here", False)
        assert "Alice" in block and "prior tail here" in block
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_worker.py::TestCarryContext -v`
Expected: FAIL with `AttributeError: ... no attribute '_carry_context'`

- [ ] **Step 3: Add the assembly helper**

In `worker.py`, add to `ProcessingWorker`:

```python
    @staticmethod
    def _carry_context(
        carry_mode: str,
        source_chunk: str,
        prior_output: str,
        starts_new_scene: bool,
        tail_words: int = 120,
    ) -> str:
        """Build the per-chunk continuity-context block for *carry_mode*
        ("off"/"glossary"/"prose"/"both"). Names come from the source chunk;
        prose tail comes from the previous chunk's output and is suppressed at
        a scene boundary or when there is no prior output."""
        from prompts import build_context_block
        names = (
            ProcessingWorker.extract_proper_nouns(source_chunk)
            if carry_mode in ("glossary", "both") else []
        )
        prose = ""
        if (carry_mode in ("prose", "both")
                and prior_output and not starts_new_scene):
            prose = " ".join(prior_output.split()[-tail_words:])
        return build_context_block(names, prose)
```

- [ ] **Step 4: Run helper test to verify it passes**

Run: `pytest tests/test_worker.py::TestCarryContext -v`
Expected: PASS

- [ ] **Step 5: Integrate into `run()`**

In `worker.py` `run()`:

(a) Read the mode near the other cfg reads (after `mode = cfg.get("mode", ...)`):

```python
        carry_mode = cfg.get("carry_mode", "off")
```

(b) Change the chapter extraction call to mark scene breaks only when prose carry is active:

```python
        all_chapters = epub_io.extract_chapters(
            epub_path, preview_chars,
            mark_scene_breaks=carry_mode in ("prose", "both"),
        )
```

(c) Replace the per-chapter chunking. Change:

```python
            chunks = self._split_into_chunks(text, self._chunk_size)
            n_chunks = len(chunks)
```

to:

```python
            chunk_pairs = self._split_into_chunks_with_scenes(
                text, self._chunk_size
            )
            chunks = [c for c, _ in chunk_pairs]
            scene_flags = [flag for _, flag in chunk_pairs]
            n_chunks = len(chunks)
```

(d) Inside `for chunk_idx, chunk in enumerate(chunks):`, immediately after `chunk_label = ...`, assemble the context for this chunk:

```python
                prior_output = spanish_parts[-1] if spanish_parts else ""
                context_block = self._carry_context(
                    carry_mode, chunk, prior_output, scene_flags[chunk_idx],
                )
```

(e) Pass `context_block=context_block` into each body-producing builder call. The four call sites and their target builders:

- `translate` branch — `build_translation_prompt(chunk, level, idx, creativity, context_block=context_block)`
- `summarise_only` branch — `build_summary_prompt(chunk, keep_pct, context_block=context_block)`
- `summarise_key_ideas` branch — this branch's `build_summary_prompt` call runs **before** the es/en split, so it is shared. Do **not** unconditionally add context to it (that would double-inject on the es path, which also injects on the rewrite). Make the summary call conditional, and add context to the rewrite call only:
  - shared summary call: `build_summary_prompt(chunk, keep_pct, context_block=(context_block if summary_lang == "en" else ""))`
  - es path rewrite call: `build_rewrite_prompt(summary, level, idx, creativity, context_block=context_block)`
- `summarise_rewrite` (else) branch — context goes to the **rewrite** call: `build_rewrite_prompt(summary, level, idx, creativity, context_block=context_block)` (leave the summary call plain).

Apply each by editing the corresponding `_ollama_call(... build_*_prompt(...) ...)` line to add the `context_block=context_block` keyword argument.

- [ ] **Step 6: Add config passthrough in app + resume (so the run actually receives carry_mode)**

This step is completed fully in Task 6 (UI). For now, confirm `run()` defaults `carry_mode` to `"off"` so the pipeline is correct before the UI exists, and run the worker tests:

Run: `pytest tests/test_worker.py -v`
Expected: PASS

Run: `grep -n "^class " *.py` → Expected: `worker.py: class ProcessingWorker(QThread)` present.

- [ ] **Step 7: Commit**

```bash
git add worker.py tests/test_worker.py
git commit -m "feat: wire scene-gated carry into the worker pipeline"
```

---

### Task 6: UI control + config + resume passthrough

A per-run selector (off / glossary / prose / both) in the Options group, threaded through config and resume, following the inline `_keyideas_lang_widget` pattern.

**Files:**
- Modify: `app.py` (`_add_options_group`, `_build_config`; verify `_on_resume`)

**Interfaces:**
- Consumes: `carry_mode` read by `worker.run()` (Task 5).
- Produces: `_build_config()` includes `"carry_mode": <"off"|"glossary"|"prose"|"both">`.

- [ ] **Step 1: Add the inline selector widget**

In `app.py` `_add_options_group`, after the chunk-size row block (after `ol.addLayout(chunk_row)`), add:

```python
        carry_row = QHBoxLayout()
        carry_row.addWidget(QLabel("Cross-chunk continuity:"))
        self._carry_combo = QComboBox()
        for label, value in [
            ("Off", "off"),
            ("Names only (protect proper nouns)", "glossary"),
            ("Prose tail (scene-gated)", "prose"),
            ("Both", "both"),
        ]:
            self._carry_combo.addItem(label, userData=value)
        self._carry_combo.setCurrentIndex(0)
        self._carry_combo.setToolTip(
            "Only affects chapters split into multiple chunks. 'Names' "
            "reinforces proper-noun consistency; 'Prose tail' carries the "
            "end of the previous chunk for smoother transitions, reset at "
            "scene breaks."
        )
        carry_row.addWidget(self._carry_combo)
        carry_row.addStretch()
        ol.addLayout(carry_row)
```

(`QComboBox` and `QLabel` are already imported in `app.py`.)

- [ ] **Step 2: Add the config field**

In `_build_config`, add to the returned dict:

```python
            "carry_mode": self._carry_combo.currentData(),
```

- [ ] **Step 3: Confirm resume passthrough**

`_on_resume` rebuilds config via `**self._resume_state["config"]`, so `carry_mode` rides along automatically. Read `_on_resume` to confirm no explicit field list overrides it. No code change expected.

- [ ] **Step 4: Manual smoke test (multi-chunk chapter, prose mode)**

Run the app, pick an EPUB with a long chapter (forces ≥2 chunks), set chunk size low (e.g. 800) to guarantee splitting, choose "Both", and run `translate` mode. In the log, confirm the run completes and the output reads continuously across the chunk seam. Then open the output `.txt` and confirm the scene-break sentinel `␞` (U+241E) appears nowhere.

```bash
grep -c $'␞' path/to/output_ES_*.txt   # expected: 0
```

- [ ] **Step 5: Run the full suite + class guard**

Run: `pytest -q` → Expected: PASS except the known `test_settings` pre-existing failure.
Run: `grep -n "^class " *.py` → Expected: all CLAUDE.md classes present.

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "feat: cross-chunk continuity selector in UI"
```

---

### Task 7: Documentation

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Document the feature**

Add to `CLAUDE.md`:
- Under the Pipeline config-keys table: a `carry_mode` row (`str`, one of `off`/`glossary`/`prose`/`both`, default `off`; only affects multi-chunk chapters).
- A short "Cross-chunk continuity" subsection explaining: glossary = stateless per-chunk source proper-noun protection (resume-trivial); prose = scene-gated tail of the previous chunk's output; scene breaks come from `epub_io`'s opt-in `mark_scene_breaks` sentinel which is stripped before any prompt/output; carry attaches to the body-producing call per mode.
- Update the `epub_io` and `prompts` rows of the File map if helpful (new `mark_scene_breaks` param; new `build_context_block`).

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document cross-chunk continuity carry"
```

---

## Self-Review

- **Spec coverage:** glossary = source name-protection list (Task 1, assembled Task 5); scene-gated prose (Tasks 3–5); UI per-run selector off/glossary/prose/both (Task 6); applies to all modes via per-mode body-call attach (Task 5 step 5); sentinel never leaks (Task 4 test + Task 6 step 4 grep). Covered.
- **Placeholder scan:** concrete regexes, concrete `tail_words=120`, concrete sentinel `␞`, concrete per-mode attach points enumerated. No TODOs.
- **Type consistency:** `_split_into_chunks_with_scenes` returns `list[tuple[str, bool]]` consumed in Task 5 as `(chunks, scene_flags)`; `_carry_context(carry_mode, source_chunk, prior_output, starts_new_scene)` signature matches its test and its `run()` call site; `build_context_block(names, prior_prose)` signature matches `_carry_context`'s call and Task 2's tests; `context_block=` keyword matches all three builder signatures.
- **Resume:** glossary is stateless (re-derived from source); prose is within-chapter and resume restarts at a chapter boundary — no carry state added to `_resume_state`. Consistent with the Global Constraints.
