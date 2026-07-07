# mlx-lm backend for BookWeaver — design

**Date:** 2026-07-07
**Status:** approved by user (brainstorming session)
**Goal:** make in-process [mlx-lm](https://github.com/ml-explore/mlx-lm) the default
mechanism for all LLM generation calls, with Ollama remaining selectable by a
configuration change (no UI switch).

**Companion documents:**
- `docs/mlx-lm-handover.md` — empirical migration lessons (thread affinity,
  thinking channels, lm→vlm architecture fallback, sampling parity). The
  implementation MUST honor its checklist (§6) except items that don't apply
  (JSON handling — BookWeaver wants prose).
- `mlx_client.py` (repo root) — battle-tested reference client from the
  recipe-extractor migration. Adapt, don't import: it is deleted at the end of
  the implementation.

---

## Decisions made with the user

| Question | Decision |
|---|---|
| Scope | **All** LLM calls (every `_ollama_call` site: summary, rewrite, translation, key ideas, book synthesis) |
| Backend switch | JSON config only (`llm_backend` key); no UI selector |
| Model lists | Per-backend lists in `bookweaver.json` (`models.mlx`, `models.ollama`, per-backend `default_model`) |
| Model memory | **Release after each run** (not process-lifetime caching) |
| Runaway generations | `max_tokens` cap only (`mlx_max_tokens`); the timeout setting applies to Ollama only |
| Dependencies | Optional + import-gated (like Kokoro TTS); install hint on failure |
| Default mlx model | `mlx-community/gemma-4-31B-it-qat-8bit`; also offered: `mlx-community/gemma-4-26B-A4B-it-qat-mxfp8`, `mlx-community/GLM-4.5-Air-4bit` (all already in the local HF cache) |
| Architecture | New Qt-free `llm.py` backend module (approach A) |

---

## 1. Architecture & module layout

New module **`llm.py`** — the single home for all LLM backends. Qt-free, like
`tts.py` and `prompts.py`.

```
worker.py ──(lazy, inside run())──▶ llm.py ──▶ httpx            (ollama path)
                                          └──▶ mlx_lm / mlx_vlm / mlx.core
                                               (mlx path; imported ONLY inside
                                                runtime constructors / unload)
```

Import-flow rules (extends the CLAUDE.md table):
- `worker → llm` lazy, inside `run()`.
- `llm` → `httpx` (lazy, ollama path) and optional mlx packages (lazy, inside
  runtime constructors only) — the module itself must import cleanly with no
  mlx packages installed. Never Qt, never `app`/`worker`/`settings`.
- `app.py` must NOT import `llm` — it checks mlx availability cheaply via
  `importlib.util.find_spec("mlx_lm")` (same pattern as the Kokoro check).

### Public surface of `llm.py`

```python
def generate(prompt: str, *, backend: str, model: str, temperature: float,
             max_tokens: int, timeout: float,
             log: Callable[[str, str], None]) -> str | None

def unload(log: Callable[[str, str], None]) -> None   # no-op for ollama /
                                                      # nothing loaded

MLX_INSTALL_HINT: str   # the shared install-hint message (also used by app.py
                        # wording; app.py hardcodes its own copy to avoid the
                        # import — keep the texts in sync)
```

- `log` is the worker's `self.log.emit` passed as a plain callable
  (`log(message, level)` with levels `"muted"`, `"warning"`, `"error"`), so
  `llm.py` never touches Qt.
- Contract is identical to today's `_ollama_call`: **`str | None`**, all
  failures logged, never raised.

### Ollama path

The current `ProcessingWorker._ollama_call` body moves verbatim: httpx POST to
`http://localhost:11434/api/generate` with `stream=False` and
`options={"temperature": …}`, `raise_for_status`, empty-response guard
(warning + `None`), word-count success log. `timeout` is honored here and only
here. Behavior is unchanged.

### MLX path (adapted from `mlx_client.py`)

Kept from the reference:
- **Module-level single-thread executor**
  `_MLX_THREAD = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx")` —
  ALL load, generate, and unload work is submitted to it. Rationale: MLX binds
  its GPU stream to the loading thread; each run/resume creates a *new*
  QThread, so correctness must not depend on the caller's thread. Also
  serializes access (MLX generation is not thread-safe).
- **`_MlxLmRuntime`** (mlx_lm: `load`, `generate`, `make_sampler`) with
  fall-through to **`_MlxVlmRuntime`** (mlx_vlm ≥ 0.6.1) when `_MlxLmRuntime`
  raises `ValueError`/`ModuleNotFoundError` whose message contains
  `"not supported"` or `"No module named"` (unified/multimodal architectures,
  e.g. gemma4_unified). Any other exception is a load failure.
- **`enable_thinking=False`** passed to `apply_chat_template`; on `TypeError`,
  retry without the kwarg and **log a warning** (`"thinking channel may leak
  into output"`) — never a silent fallback.
- **Thinking-channel cleanup** on every response: if `"<channel|>"` occurs in
  the output, keep only `text.rsplit("<channel|>", 1)[1]`.
- mlx_vlm's `generate` may return an object — use
  `out.text if hasattr(out, "text") else out`.

Changed vs. the reference:
- **No JSON machinery** (`_clean_json_text` beyond the channel split,
  `json.loads`, `generate_json`) — BookWeaver wants prose.
- **No typed error** (`OllamaError`) — failures log and return `None`.
- **Sampler built per call**: `make_sampler(temp=temperature)` inside the
  generate call, because BookWeaver's temperature varies per run via the
  creativity slider (the reference hardcoded 0.1). Cheap; no caching needed.
- **Prompting**: BookWeaver prompts are single self-contained strings with no
  system role → the message list is always
  `[{"role": "user", "content": prompt}]`. (Keep the template call inside a
  `try/except TypeError` only for the `enable_thinking` kwarg; there is no
  system-role fallback to implement.)
- **`unload()` exists** (release-after-run decision): submitted to
  `_MLX_THREAD`; drops the cached runtime reference, `gc.collect()`, then
  `mlx.core.clear_cache()` (import `mlx.core` lazily inside `unload`; ignore
  import errors — if mlx isn't installed nothing was loaded). Idempotent; safe
  when nothing was loaded.
- **Lazy load on first `generate()`** of a run: loading logs its own line
  (model id + elapsed seconds, ~7 s from a warm HF cache) so the silence
  before the first chapter is explained. If a runtime for a *different* repo
  id is somehow cached, reload for the requested one.
- Per-call logging parity with the Ollama path: `"↳ Calling <model>
  (temp=…)…"` before, `"✓ <label>: N words generated."` after (plus elapsed
  seconds), same empty-response warning.

Failure handling in the MLX path — import failure, HF download failure,
unsupported architecture (after the vlm fall-through), load failure, generation
exception, empty response — is caught inside `llm.py`, logged (with
`MLX_INSTALL_HINT` where the cause is a missing/broken install), and returns
`None`.

```python
MLX_INSTALL_HINT = (
    "llm_backend is 'mlx' but the MLX runtime is unavailable: {reason} — "
    'run: uv pip install "mlx-lm>=0.31" "mlx-vlm>=0.6.1" '
    "(or set llm_backend to 'ollama' in bookweaver.json)"
)
```

---

## 2. Configuration

### `bookweaver.json` (new/changed keys)

```json
"llm_backend": "mlx",
"mlx_max_tokens": 8192,
"ollama_timeout": 1200,

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
}
```

The repo's `bookweaver.json` is migrated to this schema as part of the change.

### `settings.py`

`_build()` resolves the active backend once at import time and keeps the
UI-facing keys **flat** so `app.py`'s dropdown code needs no structural change:

- `SETTINGS["llm_backend"]` — validated to `"mlx"` / `"ollama"`. Resolution:
  - key present → use it (invalid value → fall back to `"ollama"` with the
    value ignored; `_build` has no logging, so validation is silent — the
    dynamic UI label makes the outcome visible).
  - key absent + `models` is the **old flat list** → `"ollama"` (old config
    files keep working unchanged).
  - key absent + `models` is the new per-backend dict → `"mlx"` (the new
    default).
- `SETTINGS["models"]` / `SETTINGS["default_model"]` — the active backend's
  list/value only (flattened from the per-backend dict; passed through as-is
  for an old flat config).
- `SETTINGS["mlx_max_tokens"]` — `int`, default **8192**. Rationale: a
  2,000-word chunk translated to Spanish is ~5–6k output tokens; 8192 bounds
  runaway generation without clipping legitimate output. This cap is the
  mlx-side substitute for the timeout.
- `OLLAMA_TIMEOUT` unchanged (Ollama path only).

---

## 3. `worker.py` changes

- Rename `_ollama_call` → **`_llm_call`**; same signature
  (`model, prompt, *, label, temperature`), same `str | None` contract. Body
  delegates:

  ```python
  return llm.generate(
      prompt, backend=self._backend, model=model, temperature=temperature,
      max_tokens=SETTINGS["mlx_max_tokens"], timeout=self._timeout,
      log=self.log.emit,
  )
  ```

  All call sites (summary, rewrite, translation, key ideas, book synthesis)
  stay untouched apart from the method name.
- `run()` sets `self._backend = config.get("backend", SETTINGS["llm_backend"])`.
  The backend is captured in the **config dict** by `app.py` (not read from
  SETTINGS at call time) so resume — which spreads `**config` — can never flip
  backends mid-book even if the JSON is edited between failure and resume.
- **Unload placement:** `run()` today has many early
  `finished.emit(False, …); return` exits and no `finally`. Wrap the body of
  `run()` from the point the backend is known to the end in one `try/finally`
  with `finally: llm.unload(self.log.emit)`. No-op for ollama and when the
  model never loaded; guarantees memory release on success, failure, and every
  early exit without touching the exit sites. (`llm` is imported lazily at the
  top of `run()`, before the `try`.)
- Start-of-run log gains the backend
  (`Starting: backend=mlx model=… level=…`); when the backend is mlx, add one
  line: `mlx backend: timeout setting ignored; output capped at
  {mlx_max_tokens} tokens`.

---

## 4. `app.py` changes

1. Dropdown label `"Ollama model:"` → dynamic `f"Model ({backend}):"` — with a
   JSON-only switch, the label is how the user confirms which backend is live.
2. `_build_config()` adds `"backend": SETTINGS["llm_backend"]` (rides into
   resume automatically via the existing `**config` spread in `_on_resume`).
3. Startup availability check (mirrors the Kokoro `find_spec` pattern): if the
   backend is `"mlx"` and `importlib.util.find_spec("mlx_lm")` is `None`, log
   a warning into the log widget at launch with the install hint. The app
   still starts; a run would fail cleanly with the same hint.
4. Timeout spinbox: **disabled** with tooltip *"Ignored by the mlx backend —
   output is capped by mlx_max_tokens in bookweaver.json"* when the backend is
   mlx. (Set once at construction; the backend cannot change while the app
   runs.)

No new widgets; `widgets.py` untouched.

---

## 5. Error handling

- Every mlx failure surfaces as `None` from `llm.generate()` with a logged
  reason → downstream behavior is **identical to an Ollama failure today**:
  chunk fails → chapter fails → `failed_at_chapter` set → Resume button. No
  new failure paths in the worker, and resume works unchanged (fresh worker,
  fresh QThread, fresh lazy load — safe because the model is released per
  run anyway).
- The `enable_thinking` TypeError fallback logs a warning, never silent.
- **Known residual risk (documented, not mitigated in code):** a Metal/MLX
  fault can kill the whole process — unlike Ollama's process isolation.
  Existing mitigation: per-chapter `.txt` files are written as each chapter
  completes, so a hard crash loses at most the in-flight chapter.
- First use of a model **not yet in the HF cache** triggers a multi-GB
  download inside the first `generate()`; it is logged (the load line) but can
  take many minutes. Accepted: the three configured models are already cached
  locally.

---

## 6. Testing

Follows the `tts.py` pattern — no real deps, conftest stubs, pure functions
tested directly:

- `conftest.py`: stub `mlx_lm`, `mlx_vlm`, and `mlx.core` like the Kokoro
  packages (and continue to never stub numpy).
- New `tests/test_llm.py`:
  - **Import gate:** `llm.py` imports cleanly with no mlx packages installed.
  - **Ollama path:** the existing `_ollama_call` httpx-mock tests move here
    essentially unchanged (success, empty response, HTTP error, timeout;
    patch `httpx.Client` directly — httpx is imported lazily).
  - **MLX path with fake runtimes** (patch the runtime classes / loader):
    lm→vlm fall-through on "not supported"; install hint logged + `None` on
    import failure; thinking-channel cleanup; `enable_thinking` TypeError
    fallback logs a warning; empty response → `None`; per-call sampler gets
    the call's temperature.
  - **Thread-confinement regression test** (handover checklist item): a fake
    runtime records `threading.current_thread().name` at load and at
    generate; assert both ran on the `mlx`-prefixed thread and not the
    caller's thread.
  - **Unload:** drops the cached runtime (next generate reloads), idempotent,
    safe when nothing was loaded.
- `tests/test_worker.py`: `_llm_call` tests reduce to "delegates to
  `llm.generate` with backend/timeout/max_tokens wired from config/SETTINGS".
- `tests/test_settings.py`: schema resolution — per-backend flattening,
  defaults, invalid `llm_backend` value, old flat-schema fallback to ollama.
- After edits, run the CLAUDE.md class-boundary check
  (`grep -n "^class " *.py`).

---

## 7. Cleanup & docs (part of the implementation)

- Delete `mlx_client.py` from the repo root (reference material only; its
  lessons live in `llm.py` and this spec).
- Update `CLAUDE.md`: file-map row for `llm.py`, import-flow rules (§1 above),
  config-key documentation (`llm_backend`, `mlx_max_tokens`, per-backend
  `models`/`default_model`), and the timeout section (Ollama-only; mlx uses
  `mlx_max_tokens`).
- Dependencies are installed manually (`uv pip install "mlx-lm>=0.31"
  "mlx-vlm>=0.6.1"`) — **do not** touch `pyproject.toml` (its build backend
  is known-broken for `uv sync`; this project installs deps with
  `uv pip install`).

---

## Out of scope

- UI backend switcher, per-run model hot-swap, watchdog timeouts for mlx,
  repetition guards beyond the empty-response check, `mlx_lm.server` daemon
  mode, releasing/loading multiple models concurrently, benchmarking harness.
