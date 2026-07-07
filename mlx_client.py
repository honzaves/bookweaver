"""In-process MLX backend (mlx-lm / mlx-vlm), selected via LLM_BACKEND=mlx.

The model is loaded lazily on first use and cached for the process lifetime
(~7s load, ~16GB resident for the default 26B-A4B mxfp8). MLX has no
grammar-constrained decoding, so JSON is obtained by prompting and cleaned
deterministically before parsing. All failures raise OllamaError so callers
and failed_chunks handling are identical across backends.

mlx_lm / mlx_vlm are imported ONLY inside the runtime-class constructors —
never at module level — so this module is importable without the [mlx] extra
and the test-suite guard can patch _load_runtime.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .config import settings
from .ollama_client import OllamaError, _check_repetition

log = logging.getLogger(__name__)

# MLX binds its GPU stream to the thread that loads the model; generating from
# any other thread crashes with "There is no Stream(gpu, N) in current thread".
# Callers arrive from many threads (FastAPI's threadpool, the wizard's ingest
# job thread, the CLI main thread), so ALL load + generate work is confined to
# this single dedicated thread. max_workers=1 also serializes access — MLX
# generation is not thread-safe anyway.
_MLX_THREAD = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx")

_TEMPERATURE = 0.1  # parity with ollama_client's extraction temperature

_INSTALL_HINT = (
    "LLM_BACKEND=mlx but the MLX runtime is unavailable: {reason} — "
    "run: pip3 install -e '.[mlx]'  (or set LLM_BACKEND=ollama)"
)

_lock = threading.Lock()
_runtime: Any = None


def _apply_template(tokenizer, system: str | None, user: str) -> str:
    """Chat-template a (system, user) pair with Gemma 4's thinking DISABLED.

    enable_thinking=False makes the template emit a pre-closed empty thought
    channel ('<|channel>thought\\n<channel|>') so the model answers directly —
    without it, Gemma 4 -it models flood the output with reasoning.
    Templates that reject a system role get it folded into the user turn.
    """
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": user}
    ]
    try:
        return tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=False, enable_thinking=False
        )
    except Exception:
        merged = [{"role": "user", "content": f"{system}\n\n{user}" if system else user}]
        return tokenizer.apply_chat_template(
            merged, add_generation_prompt=True, tokenize=False, enable_thinking=False
        )


class _MlxLmRuntime:
    """Text-only architectures (e.g. the gemma4 MoE) via mlx-lm."""

    def __init__(self, repo_id: str):
        from mlx_lm import generate, load
        from mlx_lm.sample_utils import make_sampler

        self._model, self._tokenizer = load(repo_id)
        self._gen = generate
        self._sampler = make_sampler(temp=_TEMPERATURE)

    def generate_text(self, system: str | None, user: str, max_tokens: int) -> str:
        prompt = _apply_template(self._tokenizer, system, user)
        return self._gen(
            self._model, self._tokenizer, prompt=prompt,
            max_tokens=max_tokens, sampler=self._sampler, verbose=False,
        )


class _MlxVlmRuntime:
    """Multimodal architectures (e.g. gemma4_unified) via mlx-vlm ≥0.6.1."""

    def __init__(self, repo_id: str):
        from mlx_vlm import generate, load
        from mlx_vlm.prompt_utils import apply_chat_template
        from mlx_vlm.utils import load_config

        self._model, self._processor = load(repo_id)
        self._config = load_config(repo_id)
        self._gen = generate
        self._apply = apply_chat_template

    def generate_text(self, system: str | None, user: str, max_tokens: int) -> str:
        merged = f"{system}\n\n{user}" if system else user
        try:
            prompt = self._apply(
                self._processor, self._config, merged, num_images=0, enable_thinking=False
            )
        except TypeError:
            log.warning(
                "mlx-vlm apply_chat_template does not accept enable_thinking; "
                "thinking channel may leak into output"
            )
            prompt = self._apply(self._processor, self._config, merged, num_images=0)
        out = self._gen(
            self._model, self._processor, prompt,
            max_tokens=max_tokens, temperature=_TEMPERATURE, verbose=False,
        )
        return out.text if hasattr(out, "text") else out


def _load_runtime():
    """Import the MLX stack and load settings.mlx_model.

    Separate function so tests inject fakes and the conftest guard blocks
    real loads. Tries mlx-lm first; unsupported archs fall through to mlx-vlm.
    Every failure surfaces as OllamaError (the module contract).
    """
    repo_id = settings.mlx_model
    try:
        return _MlxLmRuntime(repo_id)
    except (ValueError, ModuleNotFoundError) as e:
        msg = str(e)
        if "not supported" not in msg and "No module named" not in msg:
            raise OllamaError(_INSTALL_HINT.format(reason=msg)) from e
    except Exception as e:  # any other load failure = backend unavailable
        raise OllamaError(_INSTALL_HINT.format(reason=str(e))) from e
    try:
        return _MlxVlmRuntime(repo_id)
    except Exception as e:  # any load failure here = backend unavailable
        raise OllamaError(_INSTALL_HINT.format(reason=str(e))) from e


def _get_runtime():
    global _runtime
    if _runtime is None:
        with _lock:
            if _runtime is None:
                log.info("Loading MLX model %s …", settings.mlx_model)
                _runtime = _load_runtime()
    return _runtime


def reset() -> None:
    """Drop the cached runtime (used by tests)."""
    global _runtime
    _runtime = None


def _clean_json_text(text: str) -> str:
    """Deterministically isolate the JSON object in a model response."""
    # Thinking-channel safety net: keep only what follows the last close marker.
    if "<channel|>" in text:
        text = text.rsplit("<channel|>", 1)[1]
    stripped = text.strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end <= start:
        return stripped  # no JSON object present; json.loads will fail loudly
    return stripped[start : end + 1]


def generate_json(
    prompt: str,
    *,
    model: str | None = None,
    system: str | None = None,
    num_predict: int | None = None,
) -> Any:
    """MLX flavor of ollama_client.generate_json — same contract, same errors.

    `model` is accepted for signature parity but ignored: the in-process
    runtime serves exactly one model (settings.mlx_model). No call site
    passes it today.

    The actual MLX work runs on the dedicated mlx thread (see _MLX_THREAD);
    exceptions (OllamaError included) propagate to the caller unchanged via
    Future.result().
    """
    if model and model != settings.mlx_model:
        log.warning("mlx backend ignores per-call model override %r", model)
    max_tokens = num_predict if num_predict is not None else settings.mlx_max_tokens
    return _MLX_THREAD.submit(_generate_json_on_mlx_thread, prompt, system, max_tokens).result()


def _generate_json_on_mlx_thread(prompt: str, system: str | None, max_tokens: int) -> Any:
    """Body of generate_json; must only ever run on the _MLX_THREAD worker."""
    runtime = _get_runtime()

    t0 = time.monotonic()
    text = runtime.generate_text(system, prompt, max_tokens)
    log.info("← MLX  response=%d chars  elapsed=%.1fs", len(text or ""), time.monotonic() - t0)

    if not text or not text.strip():
        raise OllamaError("MLX returned an empty response")
    rep_msg = _check_repetition(text)
    if rep_msg:
        raise OllamaError(rep_msg, raw_response=text)
    cleaned = _clean_json_text(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        log.warning("Failed to parse MLX JSON output: %s\nRaw: %s", e, text[:500])
        raise OllamaError(f"Invalid JSON from model: {e}", raw_response=text) from e


def health_check() -> bool:
    """True iff the MLX runtime is importable and the model loads. Never raises.

    Loads (or reuses) the runtime on the dedicated mlx thread so the stream
    is created where generation will later run.
    """
    try:
        _MLX_THREAD.submit(_get_runtime).result()
        return True
    except Exception:
        return False
