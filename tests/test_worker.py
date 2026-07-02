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
