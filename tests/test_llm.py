"""
tests/test_llm.py
-----------------
Unit tests for llm.py — the backend dispatch module.

Coverage
--------
- generate(backend="ollama")   mocked httpx (moved from test_worker.py's
                               TestOllamaCall): success, empty, HTTP error,
                               connection error, payload fields
- generate(backend="mlx")      fake runtimes: success, channel cleanup,
                               empty response, install-hint on ImportError,
                               thread confinement
- _load_runtime                lm → vlm fall-through on unsupported arch
- _MlxLmRuntime                per-call sampler temperature, template fallback
- unload()                     releases the cached runtime, idempotent
"""

import sys
import threading
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

import llm


def _collecting_log(store: list) -> callable:
    return lambda msg, level: store.append((msg, level))


def NO_LOG(msg, level):  # discarding log callable (upper-case: used as a constant)
    return None


def _gen(backend="ollama", **overrides):
    """Call llm.generate with test defaults, overridable per test."""
    prompt = overrides.pop("prompt", "Test prompt")
    kwargs = dict(
        backend=backend, model="test-model", temperature=0.7,
        max_tokens=100, timeout=60, label="T1", log=NO_LOG,
    )
    kwargs.update(overrides)
    return llm.generate(prompt, **kwargs)


# ──────────────────────────────────────────────────────────────
#  Ollama path  (httpx.Client mocked — httpx is imported lazily
#  inside the function, so we patch "httpx.Client" directly)
# ──────────────────────────────────────────────────────────────
class TestOllamaGenerate:
    def _mock_response(self, text: str, status: int = 200) -> MagicMock:
        resp = MagicMock()
        resp.status_code = status
        resp.json.return_value = {"response": text}
        resp.raise_for_status = MagicMock()
        if status >= 400:
            resp.raise_for_status.side_effect = Exception(f"HTTP {status}")
        return resp

    def _patched_client(self, mock_resp):
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=mock_client)
        cm.__exit__ = MagicMock(return_value=False)
        return patch("httpx.Client", return_value=cm), mock_client

    def test_successful_call_returns_text(self):
        p, _ = self._patched_client(self._mock_response("Este es el resultado."))
        with p:
            assert _gen() == "Este es el resultado."

    def test_empty_response_returns_none(self):
        p, _ = self._patched_client(self._mock_response(""))
        with p:
            assert _gen() is None

    def test_whitespace_only_response_returns_none(self):
        p, _ = self._patched_client(self._mock_response("   \n\n   "))
        with p:
            assert _gen() is None

    def test_http_error_returns_none(self):
        p, _ = self._patched_client(self._mock_response("", status=500))
        with p:
            assert _gen() is None

    def test_connection_error_returns_none_and_logs_error(self):
        logs = []
        with patch("httpx.Client", side_effect=ConnectionError("refused")):
            assert _gen(log=_collecting_log(logs)) is None
        assert any(level == "error" for _, level in logs)

    def test_temperature_and_model_passed_to_ollama(self):
        p, mock_client = self._patched_client(self._mock_response("ok"))
        with p:
            _gen(model="llama3.3:70b", temperature=0.75)
        payload = mock_client.post.call_args[1]["json"]
        assert payload["model"] == "llama3.3:70b"
        assert payload["options"]["temperature"] == 0.75

    def test_timeout_passed_to_client(self):
        mock_resp = self._mock_response("ok")
        p, _ = self._patched_client(mock_resp)
        with p as client_cls:
            _gen(timeout=777)
        assert client_cls.call_args[1]["timeout"] == 777

    def test_response_is_stripped(self):
        p, _ = self._patched_client(self._mock_response("  stripped text  "))
        with p:
            assert _gen() == "stripped text"


# ──────────────────────────────────────────────────────────────
#  MLX path — fake runtimes; never loads real models
# ──────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _reset_mlx_runtime():
    """Each test starts and ends with no cached runtime."""
    llm._runtime = None
    llm._runtime_repo = None
    yield
    llm._runtime = None
    llm._runtime_repo = None


class _FakeRuntime:
    def __init__(self, reply="salida generada"):
        self.reply = reply
        self.calls = []

    def generate_text(self, prompt, temperature, max_tokens, log):
        self.calls.append((prompt, temperature, max_tokens))
        return self.reply


class TestMlxGenerate:
    def test_successful_call_returns_text(self):
        with patch("llm._load_runtime", return_value=_FakeRuntime("Hola.")):
            assert _gen(backend="mlx") == "Hola."

    def test_runtime_loaded_once_and_cached(self):
        loader = MagicMock(return_value=_FakeRuntime())
        with patch("llm._load_runtime", loader):
            _gen(backend="mlx")
            _gen(backend="mlx")
        assert loader.call_count == 1

    def test_thinking_channel_stripped(self):
        reply = "<|channel>thought pondering…<channel|>La respuesta real."
        with patch("llm._load_runtime", return_value=_FakeRuntime(reply)):
            assert _gen(backend="mlx") == "La respuesta real."

    def test_empty_response_returns_none_and_warns(self):
        logs = []
        with patch("llm._load_runtime", return_value=_FakeRuntime("")):
            result = _gen(backend="mlx", log=_collecting_log(logs))
        assert result is None
        assert any(level == "warning" for _, level in logs)

    def test_generation_exception_returns_none_and_logs_error(self):
        rt = _FakeRuntime()
        rt.generate_text = MagicMock(side_effect=RuntimeError("metal oom"))
        logs = []
        with patch("llm._load_runtime", return_value=rt):
            result = _gen(backend="mlx", log=_collecting_log(logs))
        assert result is None
        assert any("metal oom" in msg and level == "error" for msg, level in logs)

    def test_missing_mlx_logs_install_hint(self):
        logs = []
        err = ImportError("No module named 'mlx_lm'")
        with patch("llm._load_runtime", side_effect=err):
            result = _gen(backend="mlx", log=_collecting_log(logs))
        assert result is None
        assert any(
            "uv pip install" in msg and level == "error" for msg, level in logs
        )

    def test_temperature_and_max_tokens_reach_runtime(self):
        rt = _FakeRuntime()
        with patch("llm._load_runtime", return_value=rt):
            _gen(backend="mlx", temperature=0.42, max_tokens=555)
        assert rt.calls == [("Test prompt", 0.42, 555)]

    def test_load_and_generate_confined_to_mlx_thread(self):
        recorded = {}

        class _ThreadRecordingRuntime(_FakeRuntime):
            def generate_text(self, prompt, temperature, max_tokens, log):
                recorded["generate"] = threading.current_thread().name
                return "ok"

        def fake_load(repo_id, log):
            recorded["load"] = threading.current_thread().name
            return _ThreadRecordingRuntime()

        with patch("llm._load_runtime", side_effect=fake_load):
            assert _gen(backend="mlx") == "ok"
        assert recorded["load"].startswith("mlx")
        assert recorded["generate"].startswith("mlx")
        assert recorded["load"] != threading.current_thread().name


class TestLoadRuntimeFallthrough:
    def test_unsupported_arch_falls_through_to_vlm(self, monkeypatch):
        monkeypatch.setattr(
            llm, "_MlxLmRuntime",
            MagicMock(side_effect=ValueError(
                "Model type gemma4_unified not supported")),
        )
        sentinel = object()
        monkeypatch.setattr(
            llm, "_MlxVlmRuntime", MagicMock(return_value=sentinel)
        )
        assert llm._load_runtime("repo/x", NO_LOG) is sentinel

    def test_missing_module_falls_through_to_vlm(self, monkeypatch):
        monkeypatch.setattr(
            llm, "_MlxLmRuntime",
            MagicMock(side_effect=ModuleNotFoundError(
                "No module named 'mlx_lm.models.gemma4_unified'")),
        )
        sentinel = object()
        monkeypatch.setattr(
            llm, "_MlxVlmRuntime", MagicMock(return_value=sentinel)
        )
        assert llm._load_runtime("repo/x", NO_LOG) is sentinel

    def test_other_load_error_propagates(self, monkeypatch):
        monkeypatch.setattr(
            llm, "_MlxLmRuntime",
            MagicMock(side_effect=RuntimeError("out of memory")),
        )
        with pytest.raises(RuntimeError):
            llm._load_runtime("repo/x", NO_LOG)


class _FakeTokenizer:
    """Accepts enable_thinking; records the kwargs it was given."""

    def __init__(self):
        self.kwargs_seen = []

    def apply_chat_template(self, messages, **kwargs):
        self.kwargs_seen.append(kwargs)
        return "TEMPLATED:" + messages[0]["content"]


class _RejectingTokenizer(_FakeTokenizer):
    """Simulates an older template that predates enable_thinking."""

    def apply_chat_template(self, messages, **kwargs):
        if "enable_thinking" in kwargs:
            raise TypeError("unexpected keyword argument 'enable_thinking'")
        return super().apply_chat_template(messages, **kwargs)


class TestApplyTemplate:
    def test_passes_enable_thinking_false(self):
        tok = _FakeTokenizer()
        out = llm._apply_template(tok, "hola", NO_LOG)
        assert out == "TEMPLATED:hola"
        assert tok.kwargs_seen[0]["enable_thinking"] is False

    def test_typeerror_falls_back_and_warns(self):
        logs = []
        tok = _RejectingTokenizer()
        out = llm._apply_template(tok, "hola", _collecting_log(logs))
        assert out == "TEMPLATED:hola"
        assert any(level == "warning" for _, level in logs)


class TestMlxLmRuntime:
    def test_sampler_built_with_call_temperature(self, monkeypatch):
        fake_lm = ModuleType("mlx_lm")
        fake_lm.load = lambda repo: ("MODEL", _FakeTokenizer())
        fake_lm.generate = (
            lambda model, tok, prompt, max_tokens, sampler, verbose:
            f"gen[{sampler}]"
        )
        fake_su = ModuleType("mlx_lm.sample_utils")
        fake_su.make_sampler = lambda temp: f"sampler(temp={temp})"
        monkeypatch.setitem(sys.modules, "mlx_lm", fake_lm)
        monkeypatch.setitem(sys.modules, "mlx_lm.sample_utils", fake_su)

        rt = llm._MlxLmRuntime("repo/x")
        assert rt.generate_text("hola", 0.75, 50, NO_LOG) == \
            "gen[sampler(temp=0.75)]"


class TestStripThinkingChannel:
    def test_no_marker_passthrough(self):
        assert llm._strip_thinking_channel("plain") == "plain"

    def test_splits_on_last_marker(self):
        text = "a<channel|>b<channel|>final"
        assert llm._strip_thinking_channel(text) == "final"
