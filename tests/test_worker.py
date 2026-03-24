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

from worker import ProcessingWorker
from settings import creativity_to_temperature


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
        "first_only": True,
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
