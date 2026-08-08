"""
settings.py
-----------
Loads bookweaver.json and exposes the SETTINGS dict, OLLAMA_TIMEOUT, and the
shared mode/temperature helpers to the rest of the application.

Deliberately theme-free: the UI palette lives in bookweaver.json's
"wizard_colors" block and is loaded by wizard_theme.py, which has its own
loader so the two modules share no mutable state.

To change models or timeouts, edit bookweaver.json — no Python changes needed.
"""

import json
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "bookweaver.json"


# ──────────────────────────────────────────────────────────────
#  CONFIG LOADER
# ──────────────────────────────────────────────────────────────
def _load_config(path: Path = _CONFIG_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise SystemExit(f"[BookWeaver] Config file not found: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[BookWeaver] Invalid JSON in config: {exc}")


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


def _build(path: Path = _CONFIG_PATH) -> None:
    """Load config and populate SETTINGS and OLLAMA_TIMEOUT.

    Those two are the only globals this rebuilds; TARGET_LANG and
    creativity_to_temperature are static and defined below."""
    global SETTINGS, OLLAMA_TIMEOUT

    cfg = _load_config(path)

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

    OLLAMA_TIMEOUT = int(cfg.get("ollama_timeout", 1200))


# Initialise module-level constants from the default config path.
_build()


# ──────────────────────────────────────────────────────────────
#  OUTPUT LANGUAGE & TTS VOICE SELECTION
# ──────────────────────────────────────────────────────────────
# Target language of each processing mode's output text.
TARGET_LANG = {
    "summarise_rewrite":   "es",
    "translate":           "es",
    "summarise_only":      "en",
    "summarise_key_ideas": "es",
}


def voices_for_language(lang_code: str) -> list[dict]:
    """Return the configured voice list for a 2-letter language code."""
    return SETTINGS.get("voices", {}).get(lang_code, [])


# ──────────────────────────────────────────────────────────────
#  CREATIVITY → TEMPERATURE MAPPING
# ──────────────────────────────────────────────────────────────
def creativity_to_temperature(creativity: int) -> float:
    """Map creativity 1–10 linearly to Ollama temperature 0.1–1.4."""
    return round(0.1 + (creativity - 1) * (1.3 / 9), 2)
