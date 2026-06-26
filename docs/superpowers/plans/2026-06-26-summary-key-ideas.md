# Summary with Key Ideas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fourth processing mode, "Summary with key ideas", that produces a condensed summary plus 1–5 per-chapter key ideas (bullet + ≤2-sentence explanation) and, when ≥2 chapters are processed, a book-wide key-ideas synthesis — in English or Spanish (CEFR level) chosen per run.

**Architecture:** Reuse the existing summary pipelines (`summarise_only` for English, `summarise_rewrite` for Spanish). After a chapter's summary is assembled, one extra LLM call extracts its key ideas, which are embedded in the chapter body. After the chapter loop, one post-loop LLM call (excluded from the progress bar, like TTS) synthesises book-wide ideas from the per-chapter ideas stored in the result bodies — making it resume-safe. New prompt builders and localized header constants live in `prompts.py`; mode wiring follows CLAUDE.md's "Adding a new processing mode" checklist.

**Tech Stack:** Python 3, PyQt6 (UI, stubbed in tests), Ollama HTTP API, pytest. No new dependencies.

## Global Constraints

- **IMPLEMENTER MODEL REQUIREMENT (MANDATORY):** Every task in this plan MUST be implemented by **Opus 4.8** (`claude-opus-4-8`). Do not delegate any task to a smaller/cheaper model. If dispatching subagents, each subagent MUST run on Opus 4.8.
- Mode id string: `"summarise_key_ideas"` (exact).
- Config keys added: `summary_lang` (`"en"` | `"es"`), and this mode computes `target_lang` from `summary_lang`.
- Per-chapter key ideas: **at least 1, at most 5**. Book-wide synthesis: **5–7** ideas. Each idea = a `- ` bullet + an explanation of **≤ 2 sentences**.
- Localized headers (single source of truth in `prompts.py`):
  - chapter: `{"en": "Key ideas", "es": "Ideas clave"}`
  - book: `{"en": "Key ideas of the book", "es": "Ideas clave del libro"}`
- All colours come from `bookweaver.json` via `settings.py` — never hardcode hex.
- `ProcessingWorker` must never import Qt UI classes. `prompts.py` has no Qt dependency.
- `_ollama_call` must always be passed `temperature` explicitly.
- Max line length 100; `E221` (aligned assignments) suppressed.
- After any edit touching a class boundary, run `grep -n "^class " *.py` and confirm the expected class list in CLAUDE.md's "Known historical issues".
- Run the full suite with `pytest -q` after each task. One **pre-existing** failure is expected and unrelated: `test_settings.py::TestOllamaTimeout::test_defaults_when_missing`. No other failures are acceptable.

---

### Task 1: Localized headers + `build_key_ideas_prompt` in `prompts.py`

**Files:**
- Modify: `prompts.py` (add constants + new builder after `build_rewrite_prompt`)
- Test: `tests/test_prompts.py`

**Interfaces:**
- Consumes: existing `_LEVEL_GUIDANCE`.
- Produces:
  - `KEY_IDEAS_HEADER: dict[str, str]` and `BOOK_KEY_IDEAS_HEADER: dict[str, str]`.
  - `build_key_ideas_prompt(summary_text: str, lang: str, level: str = "B2") -> str`.
  - Note: `creativity` is intentionally **not** a parameter — key-idea extraction is factual; creativity already influences output via the `temperature` passed at the call site. (Refinement of spec §5; recorded here deliberately.)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_prompts.py` (update the import line to include the new names):

```python
from prompts import (
    _LEVEL_GUIDANCE,
    _creativity_instruction,
    build_rewrite_prompt,
    build_summary_prompt,
    build_key_ideas_prompt,
    KEY_IDEAS_HEADER,
    BOOK_KEY_IDEAS_HEADER,
)


class TestKeyIdeasHeaders:
    def test_chapter_headers_present(self):
        assert KEY_IDEAS_HEADER["en"] == "Key ideas"
        assert KEY_IDEAS_HEADER["es"] == "Ideas clave"

    def test_book_headers_present(self):
        assert BOOK_KEY_IDEAS_HEADER["en"] == "Key ideas of the book"
        assert BOOK_KEY_IDEAS_HEADER["es"] == "Ideas clave del libro"


class TestBuildKeyIdeasPrompt:
    SUMMARY = "Alice met a rabbit and followed it underground."

    def test_summary_text_present(self):
        assert self.SUMMARY in build_key_ideas_prompt(self.SUMMARY, "en")

    def test_english_header_in_prompt(self):
        assert "Key ideas" in build_key_ideas_prompt(self.SUMMARY, "en")

    def test_spanish_header_in_prompt(self):
        assert "Ideas clave" in build_key_ideas_prompt(self.SUMMARY, "es", "B2")

    def test_at_most_five_rule_present(self):
        p = build_key_ideas_prompt(self.SUMMARY, "en")
        assert "FIVE" in p or "five" in p

    def test_at_least_one_rule_present(self):
        p = build_key_ideas_prompt(self.SUMMARY, "en")
        assert "AT LEAST ONE" in p or "at least one" in p.lower()

    def test_two_sentence_limit_present(self):
        assert "2 sentences" in build_key_ideas_prompt(self.SUMMARY, "en")

    def test_spanish_applies_cefr_guidance(self):
        p = build_key_ideas_prompt(self.SUMMARY, "es", "B1")
        assert _LEVEL_GUIDANCE["B1"] in p

    def test_english_does_not_inject_spanish_guidance(self):
        p = build_key_ideas_prompt(self.SUMMARY, "en")
        assert _LEVEL_GUIDANCE["B1"] not in p

    def test_proper_noun_rule_present(self):
        assert "proper noun" in build_key_ideas_prompt(self.SUMMARY, "en").lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_prompts.py::TestBuildKeyIdeasPrompt tests/test_prompts.py::TestKeyIdeasHeaders -v`
Expected: FAIL with `ImportError: cannot import name 'build_key_ideas_prompt'`.

- [ ] **Step 3: Implement constants + builder in `prompts.py`**

Add after `build_rewrite_prompt` (end of file):

```python
# ──────────────────────────────────────────────────────────────
#  KEY-IDEAS HEADERS  (single source of truth — used by the prompt
#  builders for instruction text and by the worker for rendering
#  and extraction)
# ──────────────────────────────────────────────────────────────
KEY_IDEAS_HEADER: dict[str, str] = {"en": "Key ideas", "es": "Ideas clave"}
BOOK_KEY_IDEAS_HEADER: dict[str, str] = {
    "en": "Key ideas of the book",
    "es": "Ideas clave del libro",
}


def _key_ideas_lang_line(lang: str, level: str) -> str:
    """Shared language directive for the key-idea builders."""
    if lang == "es":
        guidance = _LEVEL_GUIDANCE.get(level, _LEVEL_GUIDANCE["B2"])
        return (
            f"Write entirely in Spanish at CEFR {level}.\n"
            f"LANGUAGE GUIDANCE: {guidance}"
        )
    return "Write entirely in English."


def build_key_ideas_prompt(
    summary_text: str,
    lang: str,
    level: str = "B2",
) -> str:
    """
    Return a prompt asking the LLM to extract 1–5 key ideas from
    *summary_text*, each a bullet plus a ≤2-sentence explanation, written
    in *lang* (`"en"` or `"es"` at CEFR *level*). Output begins with the
    localized chapter header so the worker can render and later locate it.
    """
    header = KEY_IDEAS_HEADER.get(lang, KEY_IDEAS_HEADER["en"])
    return (
        "You are a precise literary analyst. Identify the key ideas or key "
        "moments of the following chapter summary.\n\n"
        "RULES:\n"
        "- Identify AT LEAST ONE and AT MOST FIVE key ideas. Only include an "
        "idea if it is genuinely important; never pad to reach five.\n"
        f"- Begin your output with this exact header line on its own: {header}\n"
        "- Then list each idea as a bullet starting with '- '. After the idea "
        "statement, add a short explanation of NO MORE THAN 2 sentences.\n"
        f"- {_key_ideas_lang_line(lang, level)}\n"
        "- Do NOT translate proper nouns: keep character, place, and "
        "organisation names exactly as written.\n"
        "- Output ONLY the header and the bullet list — no other commentary.\n\n"
        f"CHAPTER SUMMARY:\n{summary_text}\n"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_prompts.py -q`
Expected: PASS (all prompt tests green).

- [ ] **Step 5: Commit**

```bash
git add prompts.py tests/test_prompts.py
git commit -m "feat: add key-ideas headers and build_key_ideas_prompt

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `build_book_key_ideas_prompt` in `prompts.py`

**Files:**
- Modify: `prompts.py` (add builder after `build_key_ideas_prompt`)
- Test: `tests/test_prompts.py`

**Interfaces:**
- Consumes: `_key_ideas_lang_line` (Task 1), `_LEVEL_GUIDANCE`.
- Produces: `build_book_key_ideas_prompt(chapter_ideas_text: str, lang: str, level: str = "B2") -> str`.
- Note: this builder does **NOT** emit the book header line. The worker applies `BOOK_KEY_IDEAS_HEADER[lang]` as the appended result entry's **title** (rendered as a heading by every writer), so emitting it in the body too would double the heading. (Refinement of spec §6, recorded deliberately.)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_prompts.py` (extend the import to include `build_book_key_ideas_prompt`):

```python
class TestBuildBookKeyIdeasPrompt:
    IDEAS = "Key ideas\n- Alice is curious.\n- The rabbit leads her on."

    def test_ideas_text_present(self):
        assert self.IDEAS in build_book_key_ideas_prompt(self.IDEAS, "en")

    def test_book_wide_range_present(self):
        p = build_book_key_ideas_prompt(self.IDEAS, "en")
        assert "5" in p and "7" in p

    def test_two_sentence_limit_present(self):
        assert "2 sentences" in build_book_key_ideas_prompt(self.IDEAS, "en")

    def test_does_not_emit_book_header_line(self):
        # The header is applied as the entry title by the worker, not the body.
        p = build_book_key_ideas_prompt(self.IDEAS, "en")
        assert "Begin your output" not in p

    def test_spanish_applies_cefr_guidance(self):
        p = build_book_key_ideas_prompt(self.IDEAS, "es", "C1")
        assert _LEVEL_GUIDANCE["C1"] in p

    def test_english_writes_in_english(self):
        assert "Write entirely in English." in build_book_key_ideas_prompt(self.IDEAS, "en")
```

Update the import block at the top of `tests/test_prompts.py`:

```python
from prompts import (
    _LEVEL_GUIDANCE,
    _creativity_instruction,
    build_rewrite_prompt,
    build_summary_prompt,
    build_key_ideas_prompt,
    build_book_key_ideas_prompt,
    KEY_IDEAS_HEADER,
    BOOK_KEY_IDEAS_HEADER,
)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_prompts.py::TestBuildBookKeyIdeasPrompt -v`
Expected: FAIL with `ImportError: cannot import name 'build_book_key_ideas_prompt'`.

- [ ] **Step 3: Implement the builder in `prompts.py`**

Add after `build_key_ideas_prompt`:

```python
def build_book_key_ideas_prompt(
    chapter_ideas_text: str,
    lang: str,
    level: str = "B2",
) -> str:
    """
    Return a prompt that synthesises the most important book-wide ideas
    (5–7) from *chapter_ideas_text* (the concatenated per-chapter key-idea
    sections). Each idea is a bullet plus a ≤2-sentence explanation, in
    *lang*. The book header is NOT emitted here — the worker applies it as
    the result entry's title.
    """
    return (
        "You are a precise literary analyst. Below are the key ideas collected "
        "from every chapter of a book. Synthesise the MOST IMPORTANT ideas "
        "across the whole book.\n\n"
        "RULES:\n"
        "- Identify between 5 and 7 of the most important, book-wide ideas. "
        "Merge related chapter ideas; do not simply repeat them verbatim.\n"
        "- List each idea as a bullet starting with '- '. After the idea "
        "statement, add a short explanation of NO MORE THAN 2 sentences.\n"
        f"- {_key_ideas_lang_line(lang, level)}\n"
        "- Do NOT translate proper nouns.\n"
        "- Output ONLY the bullet list — no header line, no other commentary.\n\n"
        f"PER-CHAPTER KEY IDEAS:\n{chapter_ideas_text}\n"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_prompts.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add prompts.py tests/test_prompts.py
git commit -m "feat: add build_book_key_ideas_prompt

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Register mode in `settings.TARGET_LANG`

**Files:**
- Modify: `settings.py:263-267` (the `TARGET_LANG` dict)
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `TARGET_LANG["summarise_key_ideas"] == "es"` (default; the app overrides the effective language per run via `summary_lang`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_settings.py` (a new test method; place it near other `TARGET_LANG` assertions if present, otherwise add a small class):

```python
class TestTargetLangKeyIdeas:
    def test_summarise_key_ideas_default_es(self):
        from settings import TARGET_LANG
        assert TARGET_LANG["summarise_key_ideas"] == "es"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_settings.py::TestTargetLangKeyIdeas -v`
Expected: FAIL with `KeyError: 'summarise_key_ideas'`.

- [ ] **Step 3: Add the dict entry**

In `settings.py`, change the `TARGET_LANG` block to:

```python
TARGET_LANG = {
    "summarise_rewrite":   "es",
    "translate":           "es",
    "summarise_only":      "en",
    "summarise_key_ideas": "es",
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_settings.py::TestTargetLangKeyIdeas -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add settings.py tests/test_settings.py
git commit -m "feat: register summarise_key_ideas in TARGET_LANG

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Worker helpers — key-ideas extraction & collection

**Files:**
- Modify: `worker.py` (add two static methods near `_strip_asterisk_markers`)
- Test: `tests/test_worker.py`

**Interfaces:**
- Produces:
  - `ProcessingWorker._extract_key_ideas(body: str, header: str) -> str` — returns the substring of `body` from the first occurrence of `header` onward; returns the whole `body` unchanged if `header` is absent (defensive fallback).
  - `ProcessingWorker._collect_chapter_ideas(results: list[tuple[str, str]], header: str) -> str` — joins `_extract_key_ideas(body, header)` for every `(title, body)` in `results` with `"\n\n"`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_worker.py`:

```python
class TestExtractKeyIdeas:
    def test_returns_section_from_header(self):
        body = "Summary prose here.\n\nKey ideas\n- One.\n- Two."
        out = ProcessingWorker._extract_key_ideas(body, "Key ideas")
        assert out == "Key ideas\n- One.\n- Two."

    def test_missing_header_returns_whole_body(self):
        body = "Just a summary, no ideas section."
        out = ProcessingWorker._extract_key_ideas(body, "Key ideas")
        assert out == body

    def test_spanish_header(self):
        body = "Resumen.\n\nIdeas clave\n- Uno."
        out = ProcessingWorker._extract_key_ideas(body, "Ideas clave")
        assert out == "Ideas clave\n- Uno."


class TestCollectChapterIdeas:
    def test_joins_sections_only(self):
        results = [
            ("Chapter 1", "Prose A.\n\nKey ideas\n- A1."),
            ("Chapter 2", "Prose B.\n\nKey ideas\n- B1."),
        ]
        out = ProcessingWorker._collect_chapter_ideas(results, "Key ideas")
        assert out == "Key ideas\n- A1.\n\nKey ideas\n- B1."

    def test_empty_results_returns_empty_string(self):
        assert ProcessingWorker._collect_chapter_ideas([], "Key ideas") == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_worker.py::TestExtractKeyIdeas tests/test_worker.py::TestCollectChapterIdeas -v`
Expected: FAIL with `AttributeError: ... has no attribute '_extract_key_ideas'`.

- [ ] **Step 3: Implement the helpers in `worker.py`**

Insert immediately **before** `_strip_asterisk_markers` (keep both as `@staticmethod`):

```python
    @staticmethod
    def _extract_key_ideas(body: str, header: str) -> str:
        """Return the key-ideas section of *body* (from the first occurrence
        of *header* to the end), or the whole *body* if *header* is absent.
        Reads from result bodies so it is correct on fresh and resumed runs."""
        idx = body.find(header)
        return body[idx:] if idx != -1 else body

    @staticmethod
    def _collect_chapter_ideas(
        results: list[tuple[str, str]], header: str
    ) -> str:
        """Concatenate every chapter's key-ideas section for the book-wide
        synthesis prompt."""
        return "\n\n".join(
            ProcessingWorker._extract_key_ideas(body, header)
            for _, body in results
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_worker.py::TestExtractKeyIdeas tests/test_worker.py::TestCollectChapterIdeas -v`
Expected: PASS.

- [ ] **Step 5: Verify class boundaries intact**

Run: `grep -n "^class " worker.py`
Expected: `worker.py:` shows `class ProcessingWorker(QThread)` (unchanged).

- [ ] **Step 6: Commit**

```bash
git add worker.py tests/test_worker.py
git commit -m "feat: add key-ideas extraction/collection helpers to worker

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Worker pipeline integration for `summarise_key_ideas`

**Files:**
- Modify: `worker.py` (`run()` — imports, `summary_lang`, `steps_per_chapter`, the per-chapter branch, the chapter title, the post-loop synthesis, `lang_label`)
- No new unit test (this is Ollama-driven orchestration; the testable units are covered in Tasks 1–4). Verified by the full suite still passing, a clean `grep`, and a syntax/import check.

**Interfaces:**
- Consumes: `build_summary_prompt`, `build_rewrite_prompt` (existing); `build_key_ideas_prompt`, `build_book_key_ideas_prompt`, `KEY_IDEAS_HEADER`, `BOOK_KEY_IDEAS_HEADER` (Tasks 1–2); `_extract_key_ideas`, `_collect_chapter_ideas` (Task 4).
- Config consumed: `summary_lang` (default `"es"`).

- [ ] **Step 1: Extend the prompts import**

In `worker.py`, change the import line (currently line 20):

```python
from prompts import (
    build_summary_prompt,
    build_rewrite_prompt,
    build_translation_prompt,
    build_key_ideas_prompt,
    build_book_key_ideas_prompt,
    KEY_IDEAS_HEADER,
    BOOK_KEY_IDEAS_HEADER,
)
```

- [ ] **Step 2: Read `summary_lang` and fix `steps_per_chapter`**

After the line `mode = cfg.get("mode", "summarise_rewrite")  # or "translate"` add:

```python
        summary_lang = cfg.get("summary_lang", "es")
```

Replace the existing `steps_per_chapter` line:

```python
        steps_per_chapter = 1 if mode in ("translate", "summarise_only") else 2
```

with:

```python
        if mode == "summarise_key_ideas":
            # summary (+ rewrite for Spanish) + 1 key-ideas call per chapter
            steps_per_chapter = 3 if summary_lang == "es" else 2
        elif mode in ("translate", "summarise_only"):
            steps_per_chapter = 1
        else:
            steps_per_chapter = 2
```

- [ ] **Step 3: Add the per-chapter branch inside the chunk loop**

In the chunk loop, the current `if mode == "translate": ... elif mode == "summarise_only": ... else: (summarise→rewrite)` chain builds `spanish_parts`. Add a dedicated branch for the new mode **before** the final `else`. Insert this new `elif` after the `summarise_only` branch (after its `spanish_parts.append(summary)` block):

```python
                elif mode == "summarise_key_ideas":
                    # Summary path mirrors English (summarise_only) or Spanish
                    # (summarise→rewrite) depending on summary_lang. Key ideas
                    # are extracted once per chapter, after the chunk loop.
                    self.log.emit(
                        f"\n── Chapter {chunk_label}/{len(chapters)}: summarising…",
                        "info",
                    )
                    summary = self._ollama_call(
                        model,
                        build_summary_prompt(chunk, keep_pct),
                        label=f"Summary {chunk_label}",
                        temperature=temperature,
                    )
                    if summary is None:
                        self.completed_results = results
                        self.failed_at_chapter = idx
                        self.finished.emit(False, "")
                        return

                    if summary_lang == "es":
                        if self._abort:
                            self.completed_results = results
                            self.failed_at_chapter = idx
                            self.log.emit("⛔  Aborted by user.", "warning")
                            self.finished.emit(False, "")
                            return
                        self.log.emit(
                            f"── Chapter {chunk_label}/{len(chapters)}: "
                            f"rewriting in Spanish ({level}, "
                            f"creativity {creativity}/10)…",
                            "info",
                        )
                        rewritten = self._ollama_call(
                            model,
                            build_rewrite_prompt(summary, level, idx, creativity),
                            label=f"Rewrite {chunk_label}",
                            temperature=temperature,
                        )
                        if rewritten is None:
                            self.completed_results = results
                            self.failed_at_chapter = idx
                            self.finished.emit(False, "")
                            return
                        spanish_parts.append(self._strip_asterisk_markers(rewritten))
                    else:
                        spanish_parts.append(summary)
```

- [ ] **Step 4: Add the per-chapter key-ideas call after the chunk loop**

The code after the chunk loop currently is:

```python
            step += steps_per_chapter
            self.progress.emit(step, total_steps)
            ch_title = f"Chapter {idx + 1}" if mode == "summarise_only" else f"Capítulo {idx + 1}"
            results.append((ch_title, "\n\n".join(spanish_parts)))
```

Replace those four lines with:

```python
            chapter_body = "\n\n".join(spanish_parts)

            # For the key-ideas mode, append a key-ideas section to the body.
            if mode == "summarise_key_ideas":
                self.log.emit(
                    f"── Chapter {idx + 1}/{len(chapters)}: extracting key ideas…",
                    "info",
                )
                ideas = self._ollama_call(
                    model,
                    build_key_ideas_prompt(chapter_body, summary_lang, level),
                    label=f"Key ideas {idx + 1}",
                    temperature=temperature,
                )
                if ideas is None:
                    self.completed_results = results
                    self.failed_at_chapter = idx
                    self.finished.emit(False, "")
                    return
                ideas = (
                    self._strip_asterisk_markers(ideas)
                    if summary_lang == "es" else ideas
                )
                chapter_body = f"{chapter_body}\n\n{ideas.strip()}"

            step += steps_per_chapter
            self.progress.emit(step, total_steps)
            if mode == "summarise_only" or (
                mode == "summarise_key_ideas" and summary_lang == "en"
            ):
                ch_title = f"Chapter {idx + 1}"
            else:
                ch_title = f"Capítulo {idx + 1}"
            results.append((ch_title, chapter_body))
```

Then update the two lines that follow (the per-chapter file write) to use `chapter_body` instead of `"\n\n".join(spanish_parts)`:

```python
            self.completed_results = results[:]
            if "txt" in out_formats:
                self._write_chapter_file(
                    out_folder, stem, level,
                    chapter.index, chapter.title,
                    chapter_body,
                )
            self.log.emit(f"✅  Chapter {idx + 1} done.", "success")
```

- [ ] **Step 5: Add the post-loop book synthesis (before `# ── write output ──`)**

Immediately **after** the chapter `for` loop ends and **before** `out_folder.mkdir(...)`, insert:

```python
        # ── book-wide key ideas (only if ≥ 2 chapters were processed) ──
        if mode == "summarise_key_ideas" and len(results) >= 2:
            ch_header = KEY_IDEAS_HEADER.get(summary_lang, KEY_IDEAS_HEADER["en"])
            book_header = BOOK_KEY_IDEAS_HEADER.get(
                summary_lang, BOOK_KEY_IDEAS_HEADER["en"]
            )
            self.log.emit("\n🧩  Synthesising book-wide key ideas…", "info")
            ideas_text = self._collect_chapter_ideas(results, ch_header)
            book = self._ollama_call(
                model,
                build_book_key_ideas_prompt(ideas_text, summary_lang, level),
                label="Book key ideas",
                temperature=temperature,
            )
            if book:
                book_body = (
                    self._strip_asterisk_markers(book)
                    if summary_lang == "es" else book
                ).strip()
                results.append((book_header, book_body))
                self.completed_results = results[:]
                if "txt" in out_formats:
                    # index len(all_chapters) keeps the NN prefix after the
                    # last chapter; title is the localized book header.
                    self._write_chapter_file(
                        out_folder, stem, level,
                        len(all_chapters), book_header, book_body,
                    )
                self.log.emit("🧩  Book-wide key ideas added.", "success")
            else:
                self.log.emit(
                    "Book key-ideas synthesis failed; continuing without it.",
                    "warning",
                )
```

- [ ] **Step 6: Update `lang_label`**

Replace the existing line:

```python
        lang_label = "English summary" if mode == "summarise_only" else f"Spanish {level}"
```

with:

```python
        if mode == "summarise_only" or (
            mode == "summarise_key_ideas" and summary_lang == "en"
        ):
            lang_label = "English summary"
        else:
            lang_label = f"Spanish {level}"
```

- [ ] **Step 7: Syntax + class-boundary + full-suite check**

Run:
```bash
python -c "import ast; ast.parse(open('worker.py').read()); print('worker.py OK')"
grep -n "^class " worker.py
pytest -q
```
Expected: `worker.py OK`; `grep` shows `class ProcessingWorker(QThread)`; `pytest -q` shows all green except the one pre-existing `test_defaults_when_missing` failure.

- [ ] **Step 8: Commit**

```bash
git add worker.py
git commit -m "feat: wire summarise_key_ideas pipeline + book synthesis in worker

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: UI wiring in `app.py`

**Files:**
- Modify: `app.py` (`_add_summarisation_group`, `_on_mode_changed`, `_selected_mode`, `_build_config`, and a new `_summary_target_lang()` helper)
- No unit test (the Qt app is not unit-tested per CLAUDE.md). Verified by an import check under the test stubs and the full suite.

**Interfaces:**
- Produces in config: `mode == "summarise_key_ideas"`, `summary_lang` (`"en"`/`"es"`), and `target_lang` computed from `summary_lang` for this mode.

- [ ] **Step 1: Add the radio button + language toggle**

In `_add_summarisation_group`, after the existing `self._mode_summarise_only` radio is created and added, add a fourth radio and register it. Change the mode-creation block to include:

```python
        self._mode_key_ideas = QRadioButton("Summary with key ideas")
        self._mode_group.addButton(self._mode_key_ideas)
        mode_row.addWidget(self._mode_key_ideas)
```

(Add `mode_row.addWidget(self._mode_key_ideas)` **before** `mode_row.addStretch()`.)

Then, after the `self._summarise_only_note` widget is added to `sl` (and before the toggle-wiring loop), add the language toggle:

```python
        # language toggle — only visible for the key-ideas mode
        self._keyideas_lang_widget = QWidget()
        kl = QHBoxLayout(self._keyideas_lang_widget)
        kl.setContentsMargins(0, 0, 0, 0)
        kl.addWidget(QLabel("Key-ideas output language:"))
        self._keyideas_lang_group = QButtonGroup(self)
        self._keyideas_lang_es = QRadioButton("Spanish (CEFR level)")
        self._keyideas_lang_en = QRadioButton("English")
        self._keyideas_lang_es.setChecked(True)
        self._keyideas_lang_group.addButton(self._keyideas_lang_es)
        self._keyideas_lang_group.addButton(self._keyideas_lang_en)
        kl.addWidget(self._keyideas_lang_es)
        kl.addWidget(self._keyideas_lang_en)
        kl.addStretch()
        self._keyideas_lang_widget.setVisible(False)
        sl.addWidget(self._keyideas_lang_widget)
```

Then update the toggle-wiring loop to include the new mode radio and to rebuild the voice combo when the language toggle flips:

```python
        for btn in (
            self._mode_summarise,
            self._mode_translate,
            self._mode_summarise_only,
            self._mode_key_ideas,
        ):
            btn.toggled.connect(lambda _: self._on_mode_changed())
        for btn in (self._keyideas_lang_es, self._keyideas_lang_en):
            btn.toggled.connect(lambda _: self._on_mode_changed())
```

- [ ] **Step 2: Add the `_summary_target_lang` helper and update `_selected_mode`**

Add a helper method (near `_selected_mode`):

```python
    def _summary_target_lang(self) -> str:
        """Effective output language for the key-ideas mode."""
        return "en" if self._keyideas_lang_en.isChecked() else "es"
```

Update `_selected_mode`:

```python
    def _selected_mode(self) -> str:
        if self._mode_translate.isChecked():
            return "translate"
        if self._mode_summarise_only.isChecked():
            return "summarise_only"
        if self._mode_key_ideas.isChecked():
            return "summarise_key_ideas"
        return "summarise_rewrite"
```

- [ ] **Step 3: Update `_on_mode_changed` visibility**

Replace the body of `_on_mode_changed` with:

```python
    def _on_mode_changed(self) -> None:
        """Show/hide controls based on selected processing mode."""
        translate = self._mode_translate.isChecked()
        summarise_only = self._mode_summarise_only.isChecked()
        key_ideas = self._mode_key_ideas.isChecked()
        # Reduction depth applies to every mode except full translation.
        self._summarisation_widget.setVisible(not translate)
        self._translate_note.setVisible(translate)
        self._summarise_only_note.setVisible(summarise_only)
        self._keyideas_lang_widget.setVisible(key_ideas)
        # The voice combo is built in a later group than the mode radios.
        if hasattr(self, "_voice_combo"):
            self._rebuild_voice_combo()
```

- [ ] **Step 4: Compute `target_lang` for the new mode**

In `_build_config`, replace the trailing `"target_lang": TARGET_LANG[mode],` entry with:

```python
            "summary_lang": self._summary_target_lang(),
            "target_lang": (
                self._summary_target_lang()
                if mode == "summarise_key_ideas" else TARGET_LANG[mode]
            ),
```

- [ ] **Step 5: Point `_rebuild_voice_combo` at the effective language**

In `_rebuild_voice_combo`, replace:

```python
        lang = TARGET_LANG[self._selected_mode()]
```

with:

```python
        mode = self._selected_mode()
        lang = (
            self._summary_target_lang()
            if mode == "summarise_key_ideas" else TARGET_LANG[mode]
        )
```

- [ ] **Step 6: Import + class-boundary + full-suite check**

Run:
```bash
python -c "import ast; ast.parse(open('app.py').read()); print('app.py OK')"
grep -n "^class " app.py
pytest -q
```
Expected: `app.py OK`; `grep` shows `class BookWeaverApp(QMainWindow)`; suite green except the one pre-existing failure.

- [ ] **Step 7: Commit**

```bash
git add app.py
git commit -m "feat: add Summary with key ideas mode + language toggle to UI

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Document the new mode in `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md` (the "What this project does" list, the pipeline config-keys table, the per-chapter / after-all-chapters sections, and `steps_per_chapter`)

**Interfaces:** none (documentation only).

- [ ] **Step 1: Add the mode to "What this project does"**

Add a fourth bullet to the processing-modes list:

```markdown
- **Summary with key ideas** — condenses each chapter (in English, or in Spanish
  at the chosen CEFR level via Summarise → Rewrite), then appends 1–5 key ideas
  (each a bullet plus a ≤2-sentence explanation). After all chapters, if ≥2 were
  processed, a book-wide "Key ideas of the book" synthesis is appended. Output
  language is chosen per run. Uses `build_summary_prompt`,
  `build_key_ideas_prompt`, and `build_book_key_ideas_prompt`.
```

- [ ] **Step 2: Update the pipeline config-keys table**

Add rows to the "Config keys relevant to the pipeline" table:

```markdown
| `mode` | `str` | `"summarise_rewrite"` (default), `"translate"`, `"summarise_only"`, or `"summarise_key_ideas"` |
| `summary_lang` | `str` | `"en"` or `"es"` — only used by `summarise_key_ideas`; selects the output language and (for `"es"`) drives the Summarise → Rewrite path. `target_lang` equals this for the mode. |
```

(Replace the existing `mode` row with the version above.)

- [ ] **Step 3: Document the pipeline behaviour**

Under "Per chunk", add a bullet describing the new mode's chunk handling:

```markdown
   - **`summarise_key_ideas`** (per chunk: 1 call for English, 2 for Spanish):
     - English → `build_summary_prompt` (saved as English).
     - Spanish → `build_summary_prompt` → `build_rewrite_prompt`.
     After the chunk loop, one `build_key_ideas_prompt` call per chapter appends
     a localized "Key ideas / Ideas clave" section (1–5 bullets) to the body.
```

After the "After all chapters (optional MP3)" section, add:

```markdown
### After all chapters (book-wide key ideas)

In `summarise_key_ideas` mode, if ≥2 chapters were processed, the worker makes
one `build_book_key_ideas_prompt` call over the per-chapter key-idea sections
(extracted from the result bodies, so it is resume-safe) and appends a final
"Key ideas of the book / Ideas clave del libro" entry to `results`. Like TTS,
this post-loop call is excluded from `total_steps` and reported via log only; a
failure is logged but never fails the run.
```

- [ ] **Step 4: Update the `steps_per_chapter` note**

In the "Progress bar" section, replace the `steps_per_chapter` sentence with:

```markdown
where `steps_per_chapter` is **2** in `summarise_rewrite` mode, **1** in
`translate` and `summarise_only` modes, and for `summarise_key_ideas` **2**
(English: summary + key ideas) or **3** (Spanish: summary + rewrite + key
ideas). The book-wide synthesis call is excluded (post-loop, log-only).
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document Summary with key ideas mode in CLAUDE.md

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- §3 language choice → Tasks 5 (worker path), 6 (toggle). ✓
- §4 UI → Task 6. ✓
- §5 prompts → Tasks 1, 2. ✓
- §6 headers → Task 1. ✓
- §7 pipeline (per-chapter ideas, post-loop synthesis, steps, lang_label) → Task 5. ✓
- §8 TARGET_LANG → Task 3. ✓
- §9 filenames (reuse `_ES_` scheme) → unchanged; covered by Task 5 reusing `_write_chapter_file`/writers. ✓
- §10 resume → no new code; key ideas live in bodies (Task 5), synthesis reads bodies (Task 4 helper). ✓
- §11 testing → Tasks 1–4 add tests; Tasks 5–6 are integration, covered by suite + checks. ✓
- §12 CLAUDE.md → Task 7. ✓

**Placeholder scan:** No TBD/TODO/"add error handling"/"similar to" — every code step shows full code. ✓

**Type consistency:** `build_key_ideas_prompt(summary_text, lang, level)`, `build_book_key_ideas_prompt(chapter_ideas_text, lang, level)`, `_extract_key_ideas(body, header)`, `_collect_chapter_ideas(results, header)`, `_summary_target_lang()` — names/signatures match across Tasks 1–6. Header constants `KEY_IDEAS_HEADER` / `BOOK_KEY_IDEAS_HEADER` consistent throughout. `summary_lang` config key consistent (app produces, worker consumes). ✓

**Deviations from spec (deliberate, recorded in-task):**
- Key-idea builders omit the `creativity` parameter (creativity already reaches the model via `temperature`). — Task 1.
- The book header is applied as the result entry's title rather than embedded in the body, to avoid a doubled heading. — Task 2 / Task 5.