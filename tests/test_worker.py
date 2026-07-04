"""
tests/test_worker.py
--------------------
Unit tests for the testable parts of worker.py.

Coverage
--------
- creativity_to_temperature()   boundary values, monotonicity, return type
- ProcessingWorker._write_txt() file content via tmp filesystem
- ProcessingWorker._write_epub() basic file creation (and txt fallback)
- ProcessingWorker._ollama_call() mocked httpx — success, empty response,
                                   HTTP error, connection error
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import epub_io
from worker import ProcessingWorker
from settings import creativity_to_temperature


# ──────────────────────────────────────────────────────────────
#  _split_into_chunks
# ──────────────────────────────────────────────────────────────
class TestSplitIntoChunks:
    def call(self, text, max_words=2000):
        return ProcessingWorker._split_into_chunks(text, max_words)

    def _para(self, n_words):
        return " ".join(["word"] * n_words)

    def test_short_text_returns_single_chunk(self):
        text = self._para(100)
        assert self.call(text) == [text]

    def test_long_text_splits_into_multiple_chunks(self):
        # 3 paragraphs of 800 words each → should split into 2 chunks at 2000 limit
        paras = [self._para(800)] * 3
        text = "\n\n".join(paras)
        chunks = self.call(text, max_words=2000)
        assert len(chunks) == 2

    def test_no_chunk_exceeds_max_words_by_more_than_one_paragraph(self):
        # Each paragraph is 300 words; limit 1000 words
        paras = [self._para(300)] * 10
        text = "\n\n".join(paras)
        chunks = self.call(text, max_words=1000)
        for chunk in chunks:
            # A single paragraph (300w) may push a chunk over if it fills exactly,
            # but no chunk should be more than one paragraph over the limit.
            assert len(chunk.split()) <= 1300

    def test_rejoining_chunks_preserves_all_words(self):
        paras = [self._para(500)] * 6
        text = "\n\n".join(paras)
        chunks = self.call(text, max_words=1000)
        rejoined_words = sum(len(c.split()) for c in chunks)
        assert rejoined_words == len(text.split())

    def test_empty_string_returns_single_chunk(self):
        result = self.call("")
        assert result == [""]

    def test_exactly_max_words_stays_single_chunk(self):
        text = self._para(2000)
        chunks = self.call(text, max_words=2000)
        assert len(chunks) == 1

    def test_single_paragraph_larger_than_max_not_split(self):
        # Can't split within a paragraph — it must be returned as-is
        text = self._para(3000)
        chunks = self.call(text, max_words=2000)
        assert len(chunks) == 1
        assert len(chunks[0].split()) == 3000

    def test_blank_lines_stripped_from_paragraph_boundaries(self):
        text = "para one\n\n\n\npara two"
        chunks = self.call(text, max_words=2000)
        assert len(chunks) == 1
        assert "para one" in chunks[0]
        assert "para two" in chunks[0]


# ──────────────────────────────────────────────────────────────
#  _strip_asterisk_markers
# ──────────────────────────────────────────────────────────────
class TestStripAsteriskMarkers:
    def call(self, text):
        return ProcessingWorker._strip_asterisk_markers(text)

    def test_removes_single_word_markers(self):
        assert self.call("Hola, *James*.") == "Hola, James."

    def test_removes_multi_word_markers(self):
        assert self.call("*New York* era oscura.") == "New York era oscura."

    def test_removes_multiple_markers(self):
        assert self.call("*James* fue a *Londres*.") == "James fue a Londres."

    def test_leaves_plain_text_unchanged(self):
        assert self.call("Sin asteriscos aquí.") == "Sin asteriscos aquí."

    def test_does_not_remove_double_asterisks(self):
        # **bold** markdown should be left alone
        assert self.call("**bold**") == "**bold**"

    def test_empty_string(self):
        assert self.call("") == ""

    def test_asterisk_not_closed(self):
        # Unclosed asterisk — should not be touched
        assert self.call("*solo") == "*solo"

    def test_does_not_span_newlines(self):
        # A marker that spans a newline is not a name marker
        result = self.call("*James\nWatson*")
        assert result == "*James\nWatson*"


# ──────────────────────────────────────────────────────────────
#  Helper: build a minimal ProcessingWorker without Qt signals
#  firing (we construct via __new__ + manual init to avoid
#  QThread.__init__ requiring a QApplication).
# ──────────────────────────────────────────────────────────────
def _make_worker(config: dict | None = None) -> ProcessingWorker:
    """
    Construct a ProcessingWorker with a minimal config dict.
    QThread is stubbed in conftest.py so no QApplication is needed.
    Signals are replaced with MagicMock so tests don't need an event loop.
    """
    cfg = config or {
        "epub_path": "/tmp/fake.epub",
        "level": "B2",
        "keep_pct": 40,
        "model": "gemma3:27b",
        "out_format": "txt",
        "out_folder": "/tmp",
        "creativity": 5,
        "meta_title": "Test Book",
        "meta_creator": "Test Author",
        "meta_language": "es",
        "meta_contributor": "",
    }
    w = ProcessingWorker(cfg)
    # Replace Qt signals with plain mocks so emit() calls don't need a loop.
    w.log = MagicMock()
    w.log.emit = MagicMock()
    w.progress = MagicMock()
    w.progress.emit = MagicMock()
    w.finished = MagicMock()
    w.finished.emit = MagicMock()
    return w


# ──────────────────────────────────────────────────────────────
#  _write_txt
# ──────────────────────────────────────────────────────────────
class TestWriteTxt:
    RESULTS = [
        ("Capítulo 1", "Era una noche oscura."),
        ("Capítulo 2", "El lobo aullaba a la luna."),
    ]
    META = {
        "title": "Mi Libro",
        "creator": "Jane Doe",
        "language": "es",
        "contributor": "",
    }

    def test_file_is_created(self, tmp_path):
        w = _make_worker()
        out = w._write_txt(self.RESULTS, tmp_path, "mi_libro", "B2", self.META)
        assert out.exists()

    def test_filename_contains_stem_level(self, tmp_path):
        w = _make_worker()
        out = w._write_txt(self.RESULTS, tmp_path, "mi_libro", "C1", self.META)
        assert "mi_libro" in out.name
        assert "C1" in out.name

    def test_extension_is_txt(self, tmp_path):
        w = _make_worker()
        out = w._write_txt(self.RESULTS, tmp_path, "test", "B2", self.META)
        assert out.suffix == ".txt"

    def test_title_in_output(self, tmp_path):
        w = _make_worker()
        out = w._write_txt(self.RESULTS, tmp_path, "test", "B2", self.META)
        content = out.read_text(encoding="utf-8")
        assert "Mi Libro" in content

    def test_author_in_output(self, tmp_path):
        w = _make_worker()
        out = w._write_txt(self.RESULTS, tmp_path, "test", "B2", self.META)
        content = out.read_text(encoding="utf-8")
        assert "Jane Doe" in content

    def test_all_chapter_bodies_in_output(self, tmp_path):
        w = _make_worker()
        out = w._write_txt(self.RESULTS, tmp_path, "test", "B2", self.META)
        content = out.read_text(encoding="utf-8")
        for _, body in self.RESULTS:
            assert body in content

    def test_all_chapter_titles_in_output(self, tmp_path):
        w = _make_worker()
        out = w._write_txt(self.RESULTS, tmp_path, "test", "B2", self.META)
        content = out.read_text(encoding="utf-8")
        for title, _ in self.RESULTS:
            assert title in content

    def test_empty_title_does_not_crash(self, tmp_path):
        w = _make_worker()
        meta = {**self.META, "title": "", "creator": ""}
        out = w._write_txt(self.RESULTS, tmp_path, "test", "B2", meta)
        assert out.exists()

    def test_single_chapter(self, tmp_path):
        w = _make_worker()
        results = [("Capítulo 1", "Una sola frase.")]
        out = w._write_txt(results, tmp_path, "test", "B2", self.META)
        content = out.read_text(encoding="utf-8")
        assert "Una sola frase." in content

    def test_encoding_utf8_special_chars(self, tmp_path):
        w = _make_worker()
        results = [("Capítulo 1", "¿Cómo estás? ¡Bien, gracias! — Ñoño.")]
        out = w._write_txt(results, tmp_path, "test", "B2", self.META)
        content = out.read_text(encoding="utf-8")
        assert "¿Cómo estás?" in content


# ──────────────────────────────────────────────────────────────
#  _write_epub
# ──────────────────────────────────────────────────────────────
class TestWriteEpub:
    RESULTS = [("Capítulo 1", "Había una vez una princesa.")]
    META = {
        "title": "Cuento",
        "creator": "Autor",
        "language": "es",
        "contributor": "Translator",
    }

    def test_epub_file_created(self, tmp_path):
        pytest.importorskip("ebooklib")
        from ebooklib import epub as ebooklib_epub
        w = _make_worker()
        out = w._write_epub(
            self.RESULTS, tmp_path, "cuento", "B2", self.META, ebooklib_epub
        )
        assert out.exists()

    def test_epub_extension(self, tmp_path):
        pytest.importorskip("ebooklib")
        from ebooklib import epub as ebooklib_epub
        w = _make_worker()
        out = w._write_epub(
            self.RESULTS, tmp_path, "cuento", "B2", self.META, ebooklib_epub
        )
        assert out.suffix == ".epub"

    def test_epub_filename_contains_stem_and_level(self, tmp_path):
        pytest.importorskip("ebooklib")
        from ebooklib import epub as ebooklib_epub
        w = _make_worker()
        out = w._write_epub(
            self.RESULTS, tmp_path, "cuento", "C1", self.META, ebooklib_epub
        )
        assert "cuento" in out.name
        assert "C1" in out.name

    def test_fallback_to_txt_on_epub_write_failure(self, tmp_path):
        """If ebooklib raises, _write_epub must fall back to a .txt file."""
        w = _make_worker()
        broken_epub = MagicMock()
        broken_epub.EpubBook.side_effect = RuntimeError("simulated failure")
        out = w._write_epub(
            self.RESULTS, tmp_path, "cuento", "B2", self.META, broken_epub
        )
        assert out.suffix == ".txt"
        assert out.exists()

    def test_html_special_chars_escaped_in_epub(self, tmp_path):
        """
        Body text containing <, >, & should be escaped so the XHTML is valid.
        The raw chars must not appear unescaped inside the EPUB.
        """
        pytest.importorskip("ebooklib")
        from ebooklib import epub as ebooklib_epub
        import zipfile

        results = [("Capítulo 1", "Tom & Jerry said <hello> to each other.")]
        w = _make_worker()
        out = w._write_epub(
            results, tmp_path, "test", "B2", self.META, ebooklib_epub
        )
        # EPUB is a ZIP — check xhtml content inside
        with zipfile.ZipFile(out) as zf:
            xhtml_files = [n for n in zf.namelist() if n.endswith(".xhtml")]
            assert xhtml_files, "No XHTML files found inside EPUB"
            content = zf.read(xhtml_files[0]).decode("utf-8")
        # Raw ampersand inside text content should be escaped
        # (note: &amp; in XHTML is correct; raw & is not)
        assert "Tom &amp; Jerry" in content or "Tom & Jerry" not in content


# ──────────────────────────────────────────────────────────────
#  _ollama_call  (httpx.Client mocked throughout)
#
#  httpx is imported lazily *inside* _ollama_call, so we cannot
#  patch "worker.httpx".  We patch "httpx.Client" directly instead.
# ──────────────────────────────────────────────────────────────
class TestOllamaCall:
    def _mock_response(self, text: str, status: int = 200) -> MagicMock:
        resp = MagicMock()
        resp.status_code = status
        resp.json.return_value = {"response": text}
        resp.raise_for_status = MagicMock()
        if status >= 400:
            resp.raise_for_status.side_effect = Exception(f"HTTP {status}")
        return resp

    def _patched_client(self, mock_resp):
        """Return a context-manager patch that injects mock_resp into httpx.Client."""
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=mock_client)
        cm.__exit__ = MagicMock(return_value=False)
        return patch("httpx.Client", return_value=cm), mock_client

    def test_successful_call_returns_text(self):
        w = _make_worker()
        mock_resp = self._mock_response("Este es el resultado.")
        p, _ = self._patched_client(mock_resp)
        with p:
            result = w._ollama_call("gemma3:27b", "Test prompt", label="T1", temperature=0.7)
        assert result == "Este es el resultado."

    def test_empty_response_returns_none(self):
        w = _make_worker()
        mock_resp = self._mock_response("")
        p, _ = self._patched_client(mock_resp)
        with p:
            result = w._ollama_call("gemma3:27b", "Test prompt", label="T1", temperature=0.7)
        assert result is None

    def test_whitespace_only_response_returns_none(self):
        w = _make_worker()
        mock_resp = self._mock_response("   \n\n   ")
        p, _ = self._patched_client(mock_resp)
        with p:
            result = w._ollama_call("gemma3:27b", "Test prompt", label="T1", temperature=0.7)
        assert result is None

    def test_http_error_returns_none(self):
        w = _make_worker()
        mock_resp = self._mock_response("", status=500)
        p, _ = self._patched_client(mock_resp)
        with p:
            result = w._ollama_call("gemma3:27b", "Test prompt", label="T1", temperature=0.7)
        assert result is None

    def test_connection_error_returns_none(self):
        w = _make_worker()
        with patch("httpx.Client", side_effect=ConnectionError("refused")):
            result = w._ollama_call("gemma3:27b", "Test prompt", label="T1", temperature=0.7)
        assert result is None

    def test_connection_error_emits_log(self):
        w = _make_worker()
        with patch("httpx.Client", side_effect=ConnectionError("refused")):
            w._ollama_call("gemma3:27b", "Test prompt", label="T1", temperature=0.7)
        w.log.emit.assert_called()
        args = w.log.emit.call_args[0]
        assert args[1] == "error"

    def test_temperature_passed_to_ollama(self):
        w = _make_worker()
        mock_resp = self._mock_response("ok")
        p, mock_client = self._patched_client(mock_resp)
        with p:
            w._ollama_call("gemma3:27b", "prompt", temperature=0.75)
        payload = mock_client.post.call_args[1]["json"]
        assert payload["options"]["temperature"] == 0.75

    def test_model_name_passed_to_ollama(self):
        w = _make_worker()
        mock_resp = self._mock_response("ok")
        p, mock_client = self._patched_client(mock_resp)
        with p:
            w._ollama_call("llama3.3:70b", "prompt", temperature=0.7)
        payload = mock_client.post.call_args[1]["json"]
        assert payload["model"] == "llama3.3:70b"

    def test_response_is_stripped(self):
        w = _make_worker()
        mock_resp = self._mock_response("  stripped text  ")
        p, _ = self._patched_client(mock_resp)
        with p:
            result = w._ollama_call("gemma3:27b", "prompt", temperature=0.7)
        assert result == "stripped text"


class TestChapterBlock:
    def test_block_matches_legacy_format(self):
        block = ProcessingWorker._chapter_block("Capítulo 1", "Hola mundo.")
        assert block == f"\n{'=' * 60}\nCapítulo 1\n{'=' * 60}\n\nHola mundo.\n\n"

    def test_title_and_body_present(self):
        block = ProcessingWorker._chapter_block("My Title", "Some body text")
        assert "My Title" in block
        assert "Some body text" in block


class TestRunChapterSelection:
    """Regression pin for the chapter-selection contract in run().

    When selected_chapters is a SUBSET, only those chapters are processed,
    and each per-chapter filename uses chapter.index + 1 (the FULL-list
    position), NOT the filtered-list position. So selecting full-list
    indices [0, 2] must yield files '01 - …' and '03 - …' (never '01'/'02').
    """

    def test_subset_uses_fulllist_index_for_filenames(self, tmp_path):
        chapters = [
            epub_io.Chapter(0, "c0.xhtml", "Alpha", "alpha text"),
            epub_io.Chapter(1, "c1.xhtml", "Beta", "beta text"),
            epub_io.Chapter(2, "c2.xhtml", "Gamma", "gamma text"),
        ]
        w = _make_worker({
            "epub_path": str(tmp_path / "mybook.epub"),
            "out_format": ["txt"],
            "out_folder": str(tmp_path),
            "mode": "translate",
            "level": "B2",
            "keep_pct": 40,
            "model": "m",
            "creativity": 5,
            "chunk_size": 2000,
            "selected_chapters": [0, 2],
        })
        with patch.object(ProcessingWorker, "_ollama_call", return_value="texto"), \
                patch.object(epub_io, "extract_chapters", return_value=chapters):
            w.run()

        # 1. The per-chapter subfolder exists and holds EXACTLY 2 files.
        chapters_dir = tmp_path / "mybook_ES_B2_chapters"
        assert chapters_dir.is_dir()
        files = sorted(p.name for p in chapters_dir.glob("*.txt"))
        assert len(files) == 2

        # 2. Filenames use chapter.index + 1 → '01 - ' and '03 - '
        #    (filtered position would wrongly give '01'/'02').
        assert files[0].startswith("01 - ")
        assert files[1].startswith("03 - ")

        # 3. Exactly two chapters were assembled into the results.
        assert len(w.completed_results) == 2

        # 4. The run finished cleanly with success=True.
        w.finished.emit.assert_called()
        assert w.finished.emit.call_args[0][0] is True


class TestSafeFilename:
    def test_replaces_path_separators(self):
        assert "/" not in ProcessingWorker._safe_filename("a/b")
        assert "\\" not in ProcessingWorker._safe_filename("a\\b")

    def test_collapses_whitespace(self):
        assert ProcessingWorker._safe_filename("a   b\tc") == "a b c"

    def test_caps_length(self):
        assert len(ProcessingWorker._safe_filename("x" * 200)) <= 80

    def test_empty_falls_back(self):
        assert ProcessingWorker._safe_filename("   ") == "untitled"


class TestWriteChapterFile:
    def test_creates_subfolder_and_numbered_file(self, tmp_path):
        w = _make_worker()
        out = w._write_chapter_file(tmp_path, "mybook", "B2", 2, "The Title", "Body.")
        assert out.parent.name == "mybook_ES_B2_chapters"
        assert out.name == "03 - The Title.txt"
        assert out.exists()

    def test_file_contains_block(self, tmp_path):
        w = _make_worker()
        out = w._write_chapter_file(tmp_path, "b", "B2", 0, "T", "Hello body")
        text = out.read_text(encoding="utf-8")
        assert "T" in text and "Hello body" in text

    def test_index_zero_is_one_padded(self, tmp_path):
        w = _make_worker()
        out = w._write_chapter_file(tmp_path, "b", "B2", 0, "First", "x")
        assert out.name.startswith("01 - ")


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

    def test_sentinel_only_input_leaks_no_sentinel(self):
        # A chapter whose marked text is nothing but sentinels/whitespace
        # must still never emit SCENE_BREAK (fallback path).
        from epub_io import SCENE_BREAK
        text = f"{SCENE_BREAK}\n\n{SCENE_BREAK}"
        for chunk, _ in self.call(text):
            assert SCENE_BREAK not in chunk


class TestRejoinWithSceneBreaks:
    def call(self, parts, flags):
        return ProcessingWorker._rejoin_with_scene_breaks(parts, flags)

    def test_no_flags_is_plain_join(self):
        parts = ["one", "two", "three"]
        assert self.call(parts, [False, False, False]) == "\n\n".join(parts)

    def test_flagged_part_gets_separator_before_it(self):
        result = self.call(["one", "two"], [False, True])
        assert result == "one\n\n* * *\n\ntwo"

    def test_leading_flag_adds_no_separator(self):
        # A scene flag on the very first chunk must not prepend a separator.
        assert self.call(["only"], [True]) == "only"

    def test_result_never_contains_sentinel(self):
        from epub_io import SCENE_BREAK
        result = self.call(["a", "b", "c"], [False, True, True])
        assert SCENE_BREAK not in result
        assert result == "a\n\n* * *\n\nb\n\n* * *\n\nc"


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


class TestLevelCheck:
    def _worker(self):
        w = ProcessingWorker.__new__(ProcessingWorker)  # bypass QThread init
        w.log = MagicMock()
        w._timeout = 1200
        return w

    def test_level_check_logs_report(self):
        w = self._worker()
        results = [("Capítulo 1", "Hola mundo."), ("Capítulo 2", "Adiós.")]
        with patch("level_detector.assess_document",
                   return_value={"whole": None, "first_third": None,
                                 "last_third": None, "judge": None}) as ad, \
             patch("level_detector.format_report", return_value="REPORT"):
            w._run_level_check(results, "B1", "fakemodel")
        ad.assert_called_once()
        # the report text reached the log
        logged = " ".join(str(c.args[0]) for c in w.log.emit.call_args_list)
        assert "REPORT" in logged

    def test_level_check_never_raises(self):
        w = self._worker()
        with patch("level_detector.assess_document",
                   side_effect=RuntimeError("boom")):
            w._run_level_check([("t", "b")], "B1", "fakemodel")  # must not raise


class TestReadabilityLine:
    def test_readability_line_formats_score(self, monkeypatch):
        import level_detector
        monkeypatch.setattr(level_detector, "textstat_readability", lambda b: 64.0)
        line = ProcessingWorker._readability_line("Texto en español.")
        assert "64.0" in line and "Fernández" in line

    def test_readability_line_none_when_unavailable(self, monkeypatch):
        import level_detector
        monkeypatch.setattr(level_detector, "textstat_readability", lambda b: None)
        assert ProcessingWorker._readability_line("Texto.") is None


class TestValidatedChunk:
    def _worker(self):
        w = ProcessingWorker.__new__(ProcessingWorker)  # bypass QThread init
        w.log = MagicMock()
        w._timeout = 1200
        w._abort = False
        return w

    def test_accepts_when_within_range(self):
        w = self._worker()
        w._ollama_call = MagicMock(return_value="texto bueno")
        with patch("level_detector.PROFILER_AVAILABLE", True), \
             patch("level_detector.profile_text",
                   return_value={"band": "B2", "n_words": 500}):
            out = w._generate_validated_chunk(
                "m", lambda note: f"PROMPT[{note}]", "B1", "lbl", 0.4
            )
        assert out == "texto bueno"
        w._ollama_call.assert_called_once()  # no regeneration (B2 vs B1 = 1)

    def test_regenerates_when_two_above(self):
        w = self._worker()
        w._ollama_call = MagicMock(side_effect=["c1 hard", "b1 easy"])
        with patch("level_detector.PROFILER_AVAILABLE", True), \
             patch("level_detector.load_cuts", return_value=None), \
             patch("level_detector.document_band",
                   side_effect=["C1", "B1"]), \
             patch("level_detector.profile_text",
                   side_effect=[{"band": "C1", "n_words": 500},
                                {"band": "B1", "n_words": 500}]):
            out = w._generate_validated_chunk(
                "m", lambda note: f"PROMPT[{note}]", "B1", "lbl", 0.4
            )
        assert out == "b1 easy"
        assert w._ollama_call.call_count == 2
        # second call's prompt carried a non-empty simplify note
        assert "PROMPT[]" not in w._ollama_call.call_args_list[1].args[1]

    def test_caps_retries_and_keeps_last(self):
        w = self._worker()
        w._ollama_call = MagicMock(side_effect=["a", "b", "c"])
        with patch("level_detector.PROFILER_AVAILABLE", True), \
             patch("level_detector.profile_text",
                   return_value={"band": "C2", "n_words": 500}):
            out = w._generate_validated_chunk(
                "m", lambda note: "P", "B1", "lbl", 0.4, max_retries=2
            )
        assert out == "c"                       # last attempt kept
        assert w._ollama_call.call_count == 3   # 1 + 2 retries

    def test_skips_gate_when_profiler_absent(self):
        w = self._worker()
        w._ollama_call = MagicMock(return_value="whatever")
        with patch("level_detector.PROFILER_AVAILABLE", False):
            out = w._generate_validated_chunk(
                "m", lambda note: "P", "B1", "lbl", 0.4
            )
        assert out == "whatever"
        w._ollama_call.assert_called_once()

    def test_skips_gate_for_short_chunk(self):
        w = self._worker()
        w._ollama_call = MagicMock(return_value="tiny")
        with patch("level_detector.PROFILER_AVAILABLE", True), \
             patch("level_detector.profile_text",
                   return_value={"band": "C2", "n_words": 40}):
            out = w._generate_validated_chunk(
                "m", lambda note: "P", "B1", "lbl", 0.4, min_words=150
            )
        assert out == "tiny"
        w._ollama_call.assert_called_once()     # no regeneration on a tiny chunk

    def test_returns_none_on_call_failure(self):
        w = self._worker()
        w._ollama_call = MagicMock(return_value=None)
        out = w._generate_validated_chunk(
            "m", lambda note: "P", "B1", "lbl", 0.4
        )
        assert out is None


def test_validated_chunk_uses_document_band(monkeypatch):
    import level_detector
    calls = {"n": 0}
    def fake_document_band(text, cuts):
        calls["n"] += 1
        return "B1"  # at/below target => accept, no regeneration
    monkeypatch.setattr(level_detector, "load_cuts", lambda: {"x": 1})
    monkeypatch.setattr(level_detector, "document_band", fake_document_band)
    monkeypatch.setattr(level_detector, "PROFILER_AVAILABLE", True)
    monkeypatch.setattr(level_detector, "profile_text",
                        lambda t: {"band": "C1", "n_words": 300})

    w = ProcessingWorker.__new__(ProcessingWorker)
    w._timeout = 1
    w._abort = False
    w.log = type("S", (), {"emit": lambda *a, **k: None})()
    w._ollama_call = lambda *a, **k: "un texto en español " * 60
    out = w._generate_validated_chunk(
        "m", lambda note: "prompt", "B1", "Translate 1.1/1", 0.3)
    assert out is not None
    assert calls["n"] >= 1  # gate consulted the calibrated band
