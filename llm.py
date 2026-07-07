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
