# mlx-lm Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make in-process mlx-lm the default backend for every LLM call in BookWeaver, with Ollama selectable via `llm_backend` in `bookweaver.json`.

**Architecture:** A new Qt-free module `llm.py` owns both backends behind one `generate()` / `unload()` API. The worker's `_ollama_call` becomes a thin `_llm_call` delegator; the MLX model is loaded lazily on a dedicated single thread and released in a `finally` at the end of every run. `settings.py` resolves per-backend model lists into the existing flat `SETTINGS` keys so the UI code barely changes.

**Tech Stack:** Python 3.14, PyQt6 (stubbed in tests), httpx (Ollama path), `mlx-lm>=0.31` + `mlx-vlm>=0.6.1` (optional, lazily imported), pytest.

**Spec:** `docs/superpowers/specs/2026-07-07-mlx-lm-backend-design.md` (approved). Background: `docs/mlx-lm-handover.md`. Reference client being adapted: `mlx_client.py` at repo root (deleted in the final task).

## Global Constraints

- Install packages with `uv pip install …` only — NEVER `pip install` and NEVER `uv sync` (this repo's `pyproject.toml` build backend is broken for sync). Do NOT edit `pyproject.toml`.
- `llm.py` must never import Qt, `app`, `worker`, or `settings`. httpx and all mlx packages are imported lazily inside functions/constructors — `import llm` must succeed with none of them installed.
- `app.py` must never import `llm` — it probes availability with `importlib.util.find_spec("mlx_lm")`.
- All failures inside `llm.py` are logged via the passed `log` callable and surface as `None` — never an exception to the caller.
- Line length ≤ 100; E221 (aligned assignments) is allowed. Check with `pycodestyle --statistics *.py`.
- After ANY edit that touches a class boundary, run `grep -n "^class " *.py` and compare against the expected list in CLAUDE.md (plus `llm.py` adds no classes to that list — its runtime classes are private module classes: `llm.py: class _MlxLmRuntime`, `llm.py: class _MlxVlmRuntime` will appear; that is expected).
- One pre-existing test failure is expected and must be left alone: `tests/test_settings.py::TestOllamaTimeout::test_defaults_when_missing` (asserts 600, code has always used 1200). "All tests pass" below means "everything passes except this one".
- Run tests with `python -m pytest` from the repo root using the project venv (`.venv`).
- Every commit message ends with the line: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

### Task 1: settings.py — backend resolution, per-backend model lists, `mlx_max_tokens`

**Files:**
- Modify: `settings.py` (the `SETTINGS = {...}` block at lines 242–252, plus one new helper above `_build`)
- Modify: `bookweaver.json` (migrate to per-backend schema, `llm_backend: "ollama"` for now — flipped to `"mlx"` in Task 5 so the app stays coherent mid-migration)
- Test: `tests/test_settings.py` (append a new test class)

**Interfaces:**
- Produces: `SETTINGS["llm_backend"]: str` (`"mlx"` or `"ollama"`), `SETTINGS["mlx_max_tokens"]: int` (default 8192), and — unchanged in shape — `SETTINGS["models"]: list[dict]` / `SETTINGS["default_model"]: str` now holding only the *active* backend's entries. Tasks 4 and 5 consume `SETTINGS["llm_backend"]` and `SETTINGS["mlx_max_tokens"]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings.py`:

```python
# ──────────────────────────────────────────────────────────────
#  llm_backend resolution & per-backend model lists
# ──────────────────────────────────────────────────────────────
MLX_CFG = {
    **MINIMAL_CFG,
    "llm_backend": "mlx",
    "mlx_max_tokens": 4096,
    "models": {
        "mlx":    [{"label": "M", "value": "mlx-community/test-model"}],
        "ollama": [{"label": "O", "value": "test:1b"}],
    },
    "default_model": {"mlx": "mlx-community/test-model", "ollama": "test:1b"},
}


class TestLlmBackendConfig:
    @pytest.fixture(autouse=True)
    def _restore_real_config(self):
        yield
        _build()  # restore module globals from the real bookweaver.json

    def test_mlx_backend_flattens_models_to_mlx_list(self, tmp_path):
        p = _write_json(tmp_path, MLX_CFG)
        _build(p)
        assert settings_module.SETTINGS["llm_backend"] == "mlx"
        assert settings_module.SETTINGS["models"] == MLX_CFG["models"]["mlx"]
        assert settings_module.SETTINGS["default_model"] == "mlx-community/test-model"

    def test_ollama_backend_selects_ollama_list(self, tmp_path):
        cfg = {**MLX_CFG, "llm_backend": "ollama"}
        p = _write_json(tmp_path, cfg)
        _build(p)
        assert settings_module.SETTINGS["llm_backend"] == "ollama"
        assert settings_module.SETTINGS["models"] == MLX_CFG["models"]["ollama"]
        assert settings_module.SETTINGS["default_model"] == "test:1b"

    def test_old_flat_schema_defaults_to_ollama(self, tmp_path):
        # MINIMAL_CFG has no llm_backend and a flat models list.
        p = _write_json(tmp_path, MINIMAL_CFG)
        _build(p)
        assert settings_module.SETTINGS["llm_backend"] == "ollama"
        assert settings_module.SETTINGS["models"] == MINIMAL_CFG["models"]
        assert settings_module.SETTINGS["default_model"] == "test:1b"

    def test_missing_key_with_dict_schema_defaults_to_mlx(self, tmp_path):
        cfg = {k: v for k, v in MLX_CFG.items() if k != "llm_backend"}
        p = _write_json(tmp_path, cfg)
        _build(p)
        assert settings_module.SETTINGS["llm_backend"] == "mlx"

    def test_invalid_backend_falls_back_to_ollama(self, tmp_path):
        cfg = {**MLX_CFG, "llm_backend": "banana"}
        p = _write_json(tmp_path, cfg)
        _build(p)
        assert settings_module.SETTINGS["llm_backend"] == "ollama"
        assert settings_module.SETTINGS["models"] == MLX_CFG["models"]["ollama"]

    def test_mlx_max_tokens_from_config(self, tmp_path):
        p = _write_json(tmp_path, MLX_CFG)
        _build(p)
        assert settings_module.SETTINGS["mlx_max_tokens"] == 4096

    def test_mlx_max_tokens_defaults_to_8192(self, tmp_path):
        p = _write_json(tmp_path, MINIMAL_CFG)
        _build(p)
        assert settings_module.SETTINGS["mlx_max_tokens"] == 8192
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python -m pytest tests/test_settings.py::TestLlmBackendConfig -v`
Expected: FAIL — `KeyError: 'llm_backend'` (or missing key assertions).

- [ ] **Step 3: Implement in settings.py**

Insert this helper directly above `def _build(...)`:

```python
def _resolve_llm_backend(cfg: dict) -> str:
    """Return the active backend: "mlx" or "ollama".

    Absent key: new per-backend schema (models is a dict) means "mlx";
    a legacy flat models list means "ollama". Invalid values fall back
    to "ollama" (the UI's dynamic "Model (<backend>):" label makes the
    outcome visible — _build has no logging channel)."""
    backend = cfg.get("llm_backend")
    if backend in ("mlx", "ollama"):
        return backend
    if backend is None and isinstance(cfg["models"], dict):
        return "mlx"
    return "ollama"
```

Replace the `SETTINGS = {...}` block (currently lines 242–250) with:

```python
    llm_backend = _resolve_llm_backend(cfg)
    models = cfg["models"]
    default_model = cfg["default_model"]
    if isinstance(models, dict):
        models = models[llm_backend]
        default_model = cfg["default_model"][llm_backend]

    SETTINGS = {
        "llm_backend":   llm_backend,
        "models":        models,
        "default_model": default_model,
        "mlx_max_tokens": int(cfg.get("mlx_max_tokens", 8192)),
        "voices":        cfg.get("voices", {}),
        "tts":           cfg.get("tts", {}),
        "chapter_title_preview_chars": int(
            cfg.get("chapter_title_preview_chars", 50)
        ),
    }
```

(`OLLAMA_TIMEOUT` line stays as is.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_settings.py -v`
Expected: `TestLlmBackendConfig` all PASS; only the known pre-existing `TestOllamaTimeout::test_defaults_when_missing` failure remains.

- [ ] **Step 5: Migrate bookweaver.json to the per-backend schema**

Replace the `"models"` and `"default_model"` entries of `bookweaver.json` with the block below, and add the two new top-level keys `"llm_backend"` and `"mlx_max_tokens"` right after `"ollama_timeout"`. `llm_backend` stays `"ollama"` in this task (flipped to `"mlx"` in Task 5, once the worker/app can actually drive mlx):

```json
  "llm_backend": "ollama",
  "mlx_max_tokens": 8192,

  "models": {
    "mlx": [
      { "label": "Gemma 4 31B QAT (recommended)", "value": "mlx-community/gemma-4-31B-it-qat-8bit" },
      { "label": "Gemma 4 26B MoE QAT (fast)",    "value": "mlx-community/gemma-4-26B-A4B-it-qat-mxfp8" },
      { "label": "GLM-4.5-Air 4bit",              "value": "mlx-community/GLM-4.5-Air-4bit" }
    ],
    "ollama": [
      { "label": "Gemma 4 31B  (recommended)",     "value": "gemma4:31b-mxfp8" },
      { "label": "Gemma 4 26B  (2nd recommended)", "value": "gemma4:26b-mxfp8" },
      { "label": "Gemma 3 27B  (3rd recommended)", "value": "gemma3:27b" }
    ]
  },

  "default_model": {
    "mlx": "mlx-community/gemma-4-31B-it-qat-8bit",
    "ollama": "gemma4:31b-mxfp8"
  },
```

Keep everything else (`colors`, `tts`, `voices`, `chapter_title_preview_chars`, `_comment`) unchanged. Validate: `python -c "import json; json.load(open('bookweaver.json'))"`.

- [ ] **Step 6: Run the FULL suite to confirm nothing regressed**

Run: `python -m pytest -q`
Expected: everything passes except the one known pre-existing failure.

- [ ] **Step 7: Commit**

```bash
git add settings.py bookweaver.json tests/test_settings.py
git commit -m "feat: per-backend model config with llm_backend selector in settings

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: llm.py — backend module (Ollama path moved, MLX path added)

**Files:**
- Create: `llm.py`
- Modify: `tests/conftest.py` (stub the mlx packages)
- Test: `tests/test_llm.py` (new)

**Interfaces:**
- Produces (consumed by Task 4's worker):
  - `llm.generate(prompt: str, *, backend: str, model: str, temperature: float, max_tokens: int, timeout: float, label: str = "", log: Callable[[str, str], None]) -> str | None`
  - `llm.MLX_INSTALL_HINT: str` (format template with a `{reason}` placeholder)
  - (`llm.unload` is added in Task 3.)
- Note: `label` is an addition to the spec's public surface — the existing log lines (`"✓ {label}: N words"`) need it; the spec's "per-call logging parity" requirement implies it.

- [ ] **Step 1: Add mlx package stubs to conftest.py**

In `tests/conftest.py`, extend the existing stub loop (the `for _name in ("kokoro", ...)` at the bottom) — replace it with:

```python
for _name in ("kokoro", "soundfile", "lameenc", "mutagen", "mutagen.id3",
              "torch",
              # llm.py's mlx path probes these heavy optional packages.
              # Empty stubs make `from mlx_lm import load` raise ImportError,
              # which exercises the real install-failure path; tests that
              # need working fakes monkeypatch richer modules over these.
              "mlx", "mlx.core", "mlx_lm", "mlx_lm.sample_utils",
              "mlx_vlm", "mlx_vlm.prompt_utils", "mlx_vlm.utils"):
    if _is_absent(_name):
        sys.modules.setdefault(_name, ModuleType(_name))
```

- [ ] **Step 2: Write the failing tests for the Ollama path (moved from test_worker.py)**

Create `tests/test_llm.py`:

```python
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


NO_LOG = lambda msg, level: None  # noqa: E731


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
```

- [ ] **Step 3: Run to verify failure**

Run: `python -m pytest tests/test_llm.py -v`
Expected: FAIL at collection — `ModuleNotFoundError: No module named 'llm'`.

- [ ] **Step 4: Create llm.py — scaffolding, dispatch, and the Ollama path**

Create `llm.py`. This step writes the module header, the `generate()` dispatcher, and `_ollama_generate`; the MLX internals it references (`_mlx_generate` and below) are appended in Step 7 of this task — no test touches the mlx branch until then:

```python
"""
llm.py
------
LLM backends for the processing pipeline: in-process MLX (mlx-lm /
mlx-vlm, the default) and a local Ollama server, selected per run via
the *backend* argument to generate().

Qt-free by design (like prompts.py and tts.py): the worker passes its
log-signal emitter in as a plain ``log(message, level)`` callable. Every
failure — import, download, load, generation, empty response — is logged
and surfaces as ``None``, never an exception, so the pipeline's
chapter-failure / resume behaviour is identical across backends.

httpx (ollama path) and the mlx packages (mlx path) are imported lazily
inside the functions and constructors that need them, so this module
imports cleanly with neither installed.
"""

import gc
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

LogFn = Callable[[str, str], None]

MLX_INSTALL_HINT = (
    "llm_backend is 'mlx' but the MLX runtime is unavailable: {reason} — "
    'run: uv pip install "mlx-lm>=0.31" "mlx-vlm>=0.6.1" '
    "(or set llm_backend to 'ollama' in bookweaver.json)"
)

# MLX binds its GPU stream to the thread that loads the model; generating
# from any other thread crashes with "There is no Stream(gpu, N) in current
# thread". Each run/resume creates a fresh QThread, so ALL load, generate,
# and unload work is confined to this single persistent thread. max_workers=1
# also serializes access — MLX generation is not thread-safe.
_MLX_THREAD = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx")
_runtime = None            # loaded model runtime; cached until unload()
_runtime_repo: str | None = None


def generate(
    prompt: str,
    *,
    backend: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout: float,
    label: str = "",
    log: LogFn,
) -> str | None:
    """Send *prompt* to the selected backend; return the response text or
    None on any error. *timeout* applies to the ollama backend only; the
    mlx backend is bounded by *max_tokens* instead."""
    if backend == "mlx":
        return _mlx_generate(
            prompt, model=model, temperature=temperature,
            max_tokens=max_tokens, label=label, log=log,
        )
    return _ollama_generate(
        prompt, model=model, temperature=temperature,
        timeout=timeout, label=label, log=log,
    )


# ──────────────────────────────────────────────────────────────
#  OLLAMA BACKEND
# ──────────────────────────────────────────────────────────────
def _ollama_generate(
    prompt: str,
    *,
    model: str,
    temperature: float,
    timeout: float,
    label: str,
    log: LogFn,
) -> str | None:
    """POST *prompt* to the local Ollama instance."""
    try:
        import httpx
        log(f"   ↳ Calling {model} (temp={temperature})…", "muted")
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": temperature},
                },
            )
            response.raise_for_status()
            data = response.json()
            result = data.get("response", "").strip()
            if not result:
                log(f"   ⚠️  Empty response for {label}", "warning")
                return None
            word_count = len(result.split())
            log(f"   ✓  {label}: {word_count} words generated.", "muted")
            return result
    except Exception as exc:
        log(f"   Ollama error ({label}): {exc}", "error")
        return None
```

(The `import gc` is used by `unload()` in Task 3, and `time` by the MLX path
in Step 7 — pycodestyle does not flag unused imports; leave them.)

- [ ] **Step 5: Run the Ollama tests to verify they pass**

Run: `python -m pytest tests/test_llm.py::TestOllamaGenerate -v`
Expected: all `TestOllamaGenerate` PASS.

- [ ] **Step 6: Write the failing MLX-path tests**

Append to `tests/test_llm.py`:

```python
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
```


- [ ] **Step 7: Append the MLX path to llm.py**

First verify the new tests fail: `python -m pytest tests/test_llm.py -v` —
expected: `TestMlxGenerate` etc. FAIL with `NameError: name '_mlx_generate' is
not defined` (or `AttributeError` for the missing helpers).

Then append to `llm.py`:

```python
# ──────────────────────────────────────────────────────────────
#  MLX BACKEND
# ──────────────────────────────────────────────────────────────
def _apply_template(tokenizer, prompt: str, log: LogFn) -> str:
    """Chat-template a single user turn with thinking DISABLED.

    enable_thinking=False makes the template emit a pre-closed empty
    thought channel so the model answers directly — without it, Gemma-4
    family -it models flood the output with reasoning. Templates that
    predate the kwarg raise TypeError; fall back loudly, never silently."""
    messages = [{"role": "user", "content": prompt}]
    try:
        return tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=False,
            enable_thinking=False,
        )
    except TypeError:
        log(
            "   ⚠️  Chat template rejects enable_thinking; thinking "
            "channel may leak into output.", "warning",
        )
        return tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=False,
        )


class _MlxLmRuntime:
    """Text-only architectures via mlx-lm."""

    def __init__(self, repo_id: str):
        from mlx_lm import generate as lm_generate, load
        from mlx_lm.sample_utils import make_sampler

        self._model, self._tokenizer = load(repo_id)
        self._gen = lm_generate
        self._make_sampler = make_sampler

    def generate_text(
        self, prompt: str, temperature: float, max_tokens: int, log: LogFn
    ) -> str:
        templated = _apply_template(self._tokenizer, prompt, log)
        return self._gen(
            self._model, self._tokenizer, prompt=templated,
            max_tokens=max_tokens,
            sampler=self._make_sampler(temp=temperature), verbose=False,
        )


class _MlxVlmRuntime:
    """Multimodal / "unified" architectures (e.g. gemma4_unified) via
    mlx-vlm ≥ 0.6.1 — mlx-lm alone rejects them as unsupported."""

    def __init__(self, repo_id: str):
        from mlx_vlm import generate as vlm_generate, load
        from mlx_vlm.prompt_utils import apply_chat_template
        from mlx_vlm.utils import load_config

        self._model, self._processor = load(repo_id)
        self._config = load_config(repo_id)
        self._gen = vlm_generate
        self._apply = apply_chat_template

    def generate_text(
        self, prompt: str, temperature: float, max_tokens: int, log: LogFn
    ) -> str:
        try:
            templated = self._apply(
                self._processor, self._config, prompt,
                num_images=0, enable_thinking=False,
            )
        except TypeError:
            log(
                "   ⚠️  mlx-vlm apply_chat_template rejects enable_thinking; "
                "thinking channel may leak into output.", "warning",
            )
            templated = self._apply(
                self._processor, self._config, prompt, num_images=0
            )
        out = self._gen(
            self._model, self._processor, templated,
            max_tokens=max_tokens, temperature=temperature, verbose=False,
        )
        return out.text if hasattr(out, "text") else out


def _load_runtime(repo_id: str, log: LogFn):
    """Try mlx-lm first; architectures it rejects fall through to mlx-vlm.

    Detection string-matches the error message ("not supported" /
    "No module named") — brittle across versions by nature, which is why
    the handover doc says to pin versions. Anything else propagates to
    the caller, which logs MLX_INSTALL_HINT."""
    try:
        return _MlxLmRuntime(repo_id)
    except (ValueError, ModuleNotFoundError) as exc:
        msg = str(exc)
        if "not supported" not in msg and "No module named" not in msg:
            raise
    return _MlxVlmRuntime(repo_id)


def _get_runtime(repo_id: str, log: LogFn):
    """Return the cached runtime, loading it on first use (~7 s from a
    warm HF cache; a cold cache downloads the full model first).
    Must only ever run on the _MLX_THREAD worker."""
    global _runtime, _runtime_repo
    if _runtime is None or _runtime_repo != repo_id:
        log(f"   ↳ Loading MLX model {repo_id}…", "info")
        t0 = time.monotonic()
        _runtime = _load_runtime(repo_id, log)
        _runtime_repo = repo_id
        log(f"   ✓  Model loaded in {time.monotonic() - t0:.1f}s.", "muted")
    return _runtime


def _strip_thinking_channel(text: str) -> str:
    """Safety net for leaked reasoning channels: keep only what follows
    the LAST channel-close marker."""
    if "<channel|>" in text:
        return text.rsplit("<channel|>", 1)[1]
    return text


def _mlx_generate(
    prompt: str,
    *,
    model: str,
    temperature: float,
    max_tokens: int,
    label: str,
    log: LogFn,
) -> str | None:
    def body() -> str | None:
        try:
            runtime = _get_runtime(model, log)
        except Exception as exc:  # import / download / load / arch failure
            log(MLX_INSTALL_HINT.format(reason=exc), "error")
            return None
        log(f"   ↳ Calling {model} (temp={temperature})…", "muted")
        t0 = time.monotonic()
        try:
            text = runtime.generate_text(prompt, temperature, max_tokens, log)
        except Exception as exc:
            log(f"   MLX error ({label}): {exc}", "error")
            return None
        text = _strip_thinking_channel(text or "").strip()
        if not text:
            log(f"   ⚠️  Empty response for {label}", "warning")
            return None
        log(
            f"   ✓  {label}: {len(text.split())} words generated "
            f"({time.monotonic() - t0:.0f}s).", "muted",
        )
        return text

    return _MLX_THREAD.submit(body).result()
```

- [ ] **Step 8: Run the full test file to verify everything passes**

Run: `python -m pytest tests/test_llm.py -v`
Expected: all PASS.

- [ ] **Step 9: Verify llm.py imports cleanly and run the full suite**

Run: `python -c "import llm; print('llm imports OK')" && python -m pytest -q`
Expected: `llm imports OK`; suite passes except the known failure. Also run `pycodestyle --statistics llm.py tests/test_llm.py` — no violations (E221 allowed).

- [ ] **Step 10: Commit**

```bash
git add llm.py tests/test_llm.py tests/conftest.py
git commit -m "feat: llm.py backend module — ollama path moved, in-process mlx path added

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: llm.py — unload()

**Files:**
- Modify: `llm.py` (append one function)
- Test: `tests/test_llm.py` (append one class)

**Interfaces:**
- Produces: `llm.unload(log: LogFn) -> None` — releases the cached MLX runtime; safe no-op when nothing is loaded or mlx is absent. Consumed by Task 4's `run()` `finally`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_llm.py`:

```python
class TestUnload:
    def test_unload_releases_cached_runtime(self):
        loader = MagicMock(return_value=_FakeRuntime())
        with patch("llm._load_runtime", loader):
            _gen(backend="mlx")
            assert loader.call_count == 1
            llm.unload(NO_LOG)
            _gen(backend="mlx")
        assert loader.call_count == 2

    def test_unload_noop_when_nothing_loaded(self):
        logs = []
        llm.unload(_collecting_log(logs))  # must not raise
        assert not any(level == "error" for _, level in logs)

    def test_unload_is_idempotent(self):
        with patch("llm._load_runtime", return_value=_FakeRuntime()):
            _gen(backend="mlx")
        llm.unload(NO_LOG)
        llm.unload(NO_LOG)  # second call must not raise
        assert llm._runtime is None

    def test_unload_runs_on_mlx_thread(self):
        recorded = {}
        with patch("llm._load_runtime", return_value=_FakeRuntime()):
            _gen(backend="mlx")
        real_collect = gc.collect

        def spying_collect():
            recorded["thread"] = threading.current_thread().name
            return real_collect()

        with patch("llm.gc.collect", side_effect=spying_collect):
            llm.unload(NO_LOG)
        assert recorded["thread"].startswith("mlx")
```

Add `import gc` to the imports at the top of `tests/test_llm.py`.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_llm.py::TestUnload -v`
Expected: FAIL — `AttributeError: module 'llm' has no attribute 'unload'`.

- [ ] **Step 3: Implement unload() in llm.py**

Append to `llm.py`:

```python
def unload(log: LogFn) -> None:
    """Release the cached MLX runtime and its GPU memory (release-after-run
    policy). No-op when nothing is loaded — including every ollama run —
    and when mlx is not installed. Runs on the MLX thread; never raises."""
    def body() -> None:
        global _runtime, _runtime_repo
        if _runtime is None:
            return
        _runtime = None
        _runtime_repo = None
        gc.collect()
        try:
            import mlx.core as mx
            # clear_cache moved from mx.metal to mx top-level across versions.
            clear = getattr(mx, "clear_cache", None) or mx.metal.clear_cache
            clear()
        except Exception:
            pass  # mlx absent or API drift — refs are dropped either way
        log("   ✓  MLX model released.", "muted")

    try:
        _MLX_THREAD.submit(body).result()
    except Exception as exc:
        log(f"   MLX unload failed: {exc}", "warning")
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_llm.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add llm.py tests/test_llm.py
git commit -m "feat: llm.unload releases the mlx model after each run

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: worker.py — delegate to llm.py, capture backend, unload in finally

**Files:**
- Modify: `worker.py`
- Test: `tests/test_worker.py` (delete `TestOllamaCall`, add delegation tests)

**Interfaces:**
- Consumes: `llm.generate(...)`, `llm.unload(...)` (Tasks 2–3), `SETTINGS["llm_backend"]`, `SETTINGS["mlx_max_tokens"]` (Task 1).
- Produces: `ProcessingWorker._llm_call(model, prompt, *, label="", temperature)` (same contract `_ollama_call` had) and `ProcessingWorker._backend: str` set in `__init__` from `config.get("backend", ...)`. Task 5's `_build_config()` supplies `config["backend"]`.

**⚠️ This task moves a method boundary and splits `run()`. After every edit run `grep -n "^class " *.py` — repeated str_replace edits have historically dropped `class Foo(Bar):` lines in this repo.**

- [ ] **Step 1: Write the failing tests**

In `tests/test_worker.py`: **delete the entire `TestOllamaCall` class** (lines ~312–407 — its coverage moved to `tests/test_llm.py::TestOllamaGenerate` in Task 2) and the stale `_ollama_call` lines in the module docstring's Coverage list; add in its place:

```python
# ──────────────────────────────────────────────────────────────
#  _llm_call — thin delegation to llm.generate
#  (the backends themselves are tested in tests/test_llm.py)
# ──────────────────────────────────────────────────────────────
class TestLlmCallDelegation:
    def test_delegates_and_returns_result(self):
        w = _make_worker()
        with patch("llm.generate", return_value="hola") as gen:
            result = w._llm_call(
                "gemma3:27b", "Test prompt", label="T1", temperature=0.7
            )
        assert result == "hola"
        assert gen.call_args[0] == ("Test prompt",)
        kwargs = gen.call_args[1]
        assert kwargs["backend"] == w._backend
        assert kwargs["model"] == "gemma3:27b"
        assert kwargs["temperature"] == 0.7
        assert kwargs["label"] == "T1"
        assert kwargs["timeout"] == w._timeout
        assert kwargs["max_tokens"] == SETTINGS.get("mlx_max_tokens", 8192)
        assert kwargs["log"] is w.log.emit

    def test_backend_captured_from_config(self):
        w = _make_worker()
        w.config["backend"] = "mlx"
        w2 = ProcessingWorker(w.config)
        assert w2._backend == "mlx"

    def test_backend_defaults_to_settings(self):
        w = _make_worker()  # config has no "backend" key
        assert w._backend == SETTINGS.get("llm_backend", "ollama")
```

Add `SETTINGS` to the settings import at the top of `tests/test_worker.py`:
`from settings import creativity_to_temperature, SETTINGS`.

Also in `TestRunChapterSelection.test_subset_uses_fulllist_index_for_filenames`
(tests/test_worker.py:448) change

```python
        with patch.object(ProcessingWorker, "_ollama_call", return_value="texto"), \
```

to

```python
        with patch.object(ProcessingWorker, "_llm_call", return_value="texto"), \
```

— `patch.object` resolves the attribute by name and raises `AttributeError`
after the rename otherwise. (This test drives `run()` end-to-end, so after
Step 3 it also exercises the new `run()`→`_run()` split and the
`finally: llm.unload(...)` no-op path.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_worker.py::TestLlmCallDelegation -v`
Expected: FAIL — `AttributeError: ... no attribute '_llm_call'` / `'_backend'`.

- [ ] **Step 3: Implement in worker.py**

3a. In `__init__` (after the `self._chunk_size` line):

```python
        self._backend = config.get(
            "backend", SETTINGS.get("llm_backend", "ollama")
        )
```

3b. Replace the whole `_ollama_call` method (worker.py:878–921) with:

```python
    def _llm_call(
        self,
        model: str,
        prompt: str,
        *,
        label: str = "",
        temperature: float,
    ) -> str | None:
        """
        Send *prompt* to the configured LLM backend (mlx or ollama) and
        return the response text, or None on any error.
        """
        import llm
        return llm.generate(
            prompt,
            backend=self._backend,
            model=model,
            temperature=temperature,
            max_tokens=SETTINGS.get("mlx_max_tokens", 8192),
            timeout=self._timeout,
            label=label,
            log=self.log.emit,
        )
```

3c. Rename all 8 call sites: every `self._ollama_call(` → `self._llm_call(` (worker.py lines 211, 230, 252, 281, 303, 328, 353, 396 as of the current tree — re-grep, the lines shift).

3d. Split `run()` so unload is guaranteed. The current `run()` starts with a dependency-check `try/except ImportError` block (lines 70–82) and then `cfg = self.config`. Change the method header area to:

```python
    # ── main entry point ──────────────────────────────────────
    def run(self) -> None:
        try:
            from ebooklib import epub as ebooklib_epub
            import httpx  # noqa: F401 — presence check for the ollama path
            import epub_io
        except ImportError as exc:
            self.log.emit(
                f"Missing dependency: {exc}\n"
                "Run: pip install ebooklib httpx beautifulsoup4",
                "error",
            )
            self.finished.emit(False, "")
            return
        import llm
        try:
            self._run(ebooklib_epub, epub_io)
        finally:
            # Release-after-run policy: drop the mlx model on success,
            # failure, abort, and every early return alike. No-op for
            # ollama runs and when the model never loaded.
            llm.unload(self.log.emit)

    def _run(self, ebooklib_epub, epub_io) -> None:
        cfg = self.config
```

i.e. the old body from `cfg = self.config` (line 84) to the final `self.finished.emit(True, ...)` (line 455) moves unchanged — same indentation — into the new `_run` method; only the import block at its top is removed (the imports are now parameters). **Do this as a minimal edit: change the `def` line and remove the import block; do not retype the body.**

3e. Add the mlx info line in `_run`, immediately before the `# ── load source EPUB ──` comment (currently the `self.log.emit(f"📖  Loading …")` block):

```python
        if self._backend == "mlx":
            self.log.emit(
                f"ℹ️   mlx backend: timeout setting ignored; output capped "
                f"at {SETTINGS.get('mlx_max_tokens', 8192)} tokens.",
                "info",
            )
```

3f. Update the module docstring (lines 1–12): replace `via Ollama` with `via the configured LLM backend (mlx-lm in-process, or a local Ollama server)`.

- [ ] **Step 4: Verify class boundaries survived the edits**

Run: `grep -n "^class " *.py`
Expected: the exact list from CLAUDE.md, plus `llm.py:class _MlxLmRuntime` and `llm.py:class _MlxVlmRuntime`.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass except the known `test_settings.py` failure. In particular `TestRunChapterSelection` (drives `run()` end-to-end with mocks) must still pass — it exercises the new `run()`→`_run()` split and the `finally: llm.unload(...)` path.

- [ ] **Step 6: Commit**

```bash
git add worker.py tests/test_worker.py
git commit -m "refactor: worker delegates LLM calls to llm.py; unload model after every run

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: app.py — backend in config, dynamic label, availability warning, timeout disable; flip default to mlx

**Files:**
- Modify: `app.py`
- Modify: `bookweaver.json` (flip `"llm_backend"` to `"mlx"`)

**Interfaces:**
- Consumes: `SETTINGS["llm_backend"]` (Task 1). Produces `config["backend"]`, consumed by `ProcessingWorker.__init__` (Task 4).
- No unit tests: app.py is Qt UI and the suite doesn't cover it (conftest only stubs enough Qt for worker.py). Verification is the syntax check, full suite, and class-boundary grep below.

- [ ] **Step 1: Dynamic model label** — in `_add_model_group` (app.py:170) replace:

```python
        col1.addWidget(QLabel("Ollama model:"))
```

with:

```python
        col1.addWidget(
            QLabel(f"Model ({SETTINGS.get('llm_backend', 'ollama')}):")
        )
```

- [ ] **Step 2: Backend into the run config** — in `_build_config()`'s returned dict (after the `"model":` entry, app.py:568) add:

```python
            "backend": SETTINGS.get("llm_backend", "ollama"),
```

(Resume re-applies it automatically via the `**self._resume_state["config"]` spread in `_on_resume` — no change needed there.)

- [ ] **Step 3: Backend in the start log** — in `_on_start` (app.py:681–687) change the first f-string line from
`f"Starting: model={cfg['model']}  level={cfg['level']}  "` to
`f"Starting: backend={cfg['backend']}  model={cfg['model']}  level={cfg['level']}  "`.

- [ ] **Step 4: Startup availability warning** — in `_build_ui`, right after the `self._log.append_line("Ready. …")` call (app.py:120–122), add:

```python
        if (SETTINGS.get("llm_backend") == "mlx"
                and importlib.util.find_spec("mlx_lm") is None):
            self._log.append_line(
                "⚠️  llm_backend is 'mlx' but mlx-lm is not installed — "
                'run: uv pip install "mlx-lm>=0.31" "mlx-vlm>=0.6.1", '
                "or set llm_backend to 'ollama' in bookweaver.json.",
                "warning",
            )
```

(`importlib` is already imported at module level for the Kokoro check at app.py:328 — verify with `grep -n "^import importlib" app.py`; if it is imported locally inside a method instead, add `import importlib.util` to the module-level imports.)

- [ ] **Step 5: Disable the timeout spinbox for mlx** — after the `self._timeout_spin` construction block (app.py:363–368), add:

```python
        if SETTINGS.get("llm_backend") == "mlx":
            self._timeout_spin.setEnabled(False)
            self._timeout_spin.setToolTip(
                "Ignored by the mlx backend — output is capped by "
                "mlx_max_tokens in bookweaver.json."
            )
```

- [ ] **Step 6: Update the header subtitle** — app.py:136: change `"  EPUB → Spanish rewriter via Ollama"` to `"  EPUB → Spanish rewriter via local LLM"`.

- [ ] **Step 7: Flip the default backend** — in `bookweaver.json`, change `"llm_backend": "ollama"` to `"llm_backend": "mlx"`. From this commit on, mlx is the default and Ollama is the config-selectable fallback (the spec's goal state).

- [ ] **Step 8: Verify**

```bash
python -c "import ast; ast.parse(open('app.py').read()); print('app.py parses')"
python -c "import json; json.load(open('bookweaver.json')); print('json valid')"
python -m pytest -q
grep -n "^class " *.py
pycodestyle --statistics app.py
```

Expected: parses, valid, suite green except the known failure, class list intact, no new style violations.

- [ ] **Step 9: Commit**

```bash
git add app.py bookweaver.json
git commit -m "feat: mlx is the default backend — dynamic model label, availability warning, timeout disable

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Cleanup, CLAUDE.md, final verification

**Files:**
- Delete: `mlx_client.py` (repo root — reference material, superseded by `llm.py`)
- Modify: `CLAUDE.md`

**Interfaces:** none (documentation only).

- [ ] **Step 1: Delete the reference client**

```bash
git rm mlx_client.py
```

- [ ] **Step 2: Update CLAUDE.md** — five edits:

2a. File map: add after the `prompts.py` row:

```markdown
| `llm.py` | LLM backends — in-process mlx-lm/mlx-vlm (default) and local Ollama; lazy optional imports, Qt-free | For backend/LLM-call changes |
```

2b. Architecture rules, import-flow list: add these lines to rule 1 (after the `worker → epub_io` line):

```markdown
   `worker` → `llm` (lazy, inside `run` / `_llm_call`)
   `llm` → `httpx` and optional mlx deps only (`mlx_lm`, `mlx_vlm`,
   `mlx.core`), all imported lazily inside functions/constructors; never
   Qt, never `app`/`worker`/`settings`
```

and extend the `app.py must not import tts` sentence: `app.py must not import `llm` either — it checks mlx availability cheaply via `importlib.util.find_spec("mlx_lm")`.`

2c. Configuration system section: add to the bullet list:

```markdown
- `llm_backend` — `"mlx"` (default, in-process mlx-lm/mlx-vlm on Apple
  silicon) or `"ollama"` (local Ollama server). JSON-only switch, no UI.
- `mlx_max_tokens` — per-call output cap for the mlx backend (default 8192);
  the mlx substitute for a timeout (in-process generation can't be aborted)
- `models` / `default_model` — now per-backend dicts keyed `"mlx"` /
  `"ollama"`; `settings.py` flattens the active backend's entries into
  `SETTINGS["models"]` / `SETTINGS["default_model"]`, so the UI only ever
  sees the active list. mlx values are Hugging Face repo ids
  (`mlx-community/*`, instruction-tuned conversions only); ollama values
  are Ollama tags. The legacy flat-list schema still parses (implies
  `llm_backend: "ollama"`).
```

2d. Pipeline config-keys table: add a row:

```markdown
| `backend` | `str` | `"mlx"` or `"ollama"` — captured from `SETTINGS["llm_backend"]` at start time so resume never flips backends mid-book |
```

2e. Timeout section: append:

```markdown
The timeout applies to the **Ollama backend only**. The mlx backend runs
in-process and cannot abort a generation midway; runaway output is bounded
by `mlx_max_tokens` instead, and the timeout spinbox is disabled in the UI
when `llm_backend` is `"mlx"`. The mlx model loads lazily on the first call
of a run (~7 s from a warm HF cache) and is **released after every run**
(`llm.unload()` in `run()`'s `finally`). Known trade-off vs Ollama: a
Metal/MLX fault can take down the whole app process; per-chapter txt files
limit the loss to the in-flight chapter.
```

2f. Test suite section: add `llm.py` to the tested-modules sentence and mention that conftest also stubs the mlx packages. Update the expected `grep -n "^class " *.py` list in "Known historical issues" to include:

```
llm.py:     class _MlxLmRuntime
llm.py:     class _MlxVlmRuntime
```

Also update the worker.py line in that section if needed (unchanged: `worker.py:  class ProcessingWorker(QThread)`).

- [ ] **Step 3: Final full verification**

```bash
python -m pytest -q
pycodestyle --statistics *.py
grep -n "^class " *.py
```

Expected: suite green except the known `test_settings.py::TestOllamaTimeout::test_defaults_when_missing`; no new style violations; class list matches the updated CLAUDE.md.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs: CLAUDE.md for llm backend architecture; drop reference mlx_client

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Real-model smoke test (requires the human)**

Not automatable in CI (loads a real 8-bit 31B model). Ask the user to run:

```bash
.venv/bin/python main.py
```

then process one short chapter of any EPUB in *Summarise only* mode with the default mlx model and confirm: the log shows `backend=mlx`, a `Loading MLX model mlx-community/gemma-4-31B-it-qat-8bit…` line, a per-call `✓ … words generated` line, and a final `MLX model released.` line. If mlx-lm/mlx-vlm are not yet installed in `.venv`: `uv pip install "mlx-lm>=0.31" "mlx-vlm>=0.6.1"`.
