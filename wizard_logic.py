"""
wizard_logic.py
---------------
Pure, Qt-free decision logic for the Guided Wizard frontend.

This is the only load-bearing wizard module: build_config() is the single
seam where a cosmetic rewrite could silently break the pipeline. Everything
here is unit-tested.

Imports stdlib + settings only. Never Qt, never wizard_theme, never app or
worker. In particular it NEVER returns a hex colour — only semantic ramp
keys, which wizard_widgets maps to W_* constants. That is what keeps this
module testable without a QApplication or a palette.
"""

from dataclasses import dataclass, field
from pathlib import Path

from settings import creativity_to_temperature, TARGET_LANG

# ──────────────────────────────────────────────────────────────
#  Vocabulary
# ──────────────────────────────────────────────────────────────
# The design's state names are short; the worker's are explicit.
MODE_TO_WORKER: dict[str, str] = {
    "sr": "summarise_rewrite",
    "full": "translate",
    "sum": "summarise_only",
    "key": "summarise_key_ideas",
}

# Likewise for cross-chunk continuity (worker.py reads carry_mode).
CARRY_TO_WORKER: dict[str, str] = {
    "off": "off",
    "names": "glossary",
    "tail": "prose",
    "both": "both",
}

# Exactly what ProcessingWorker._run() reads. app.py emits the first 21;
# max_tokens is the wizard's addition (see worker.py __init__).
CONFIG_KEYS: frozenset[str] = frozenset({
    "epub_path", "model", "backend", "selected_chapters", "mode", "level",
    "keep_pct", "creativity", "carry_mode", "summary_lang", "target_lang",
    "out_format", "out_folder", "generate_mp3", "voice",
    "meta_title", "meta_creator", "meta_language", "meta_contributor",
    "chunk_size", "timeout", "max_tokens",
})

KEEP_SWEET_MIN, KEEP_SWEET_MAX = 30, 50
CREATIVITY_SWEET_MIN, CREATIVITY_SWEET_MAX = 5, 6

# (name, ramp_key). Ramp per the handoff README: 1-2 muted, 3-4 neutral,
# 5-6 green, 7-8 warning, 9-10 error. widgets.py's older ramp puts 7-8 on
# brand amber and 9 on warning; the wizard does not copy it.
CREATIVITY_NOTCHES: dict[int, tuple[str, str]] = {
    1: ("Verbatim", "muted"),
    2: ("Faithful", "muted"),
    3: ("Faithful+", "neutral"),
    4: ("Enriched", "neutral"),
    5: ("Enriched+", "green"),
    6: ("Vivid", "green"),
    7: ("Expressive", "warning"),
    8: ("Inventive", "warning"),
    9: ("Free", "error"),
    10: ("Unbound", "error"),
}


# ──────────────────────────────────────────────────────────────
#  State
# ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ChapterRow:
    """One row of the Step-1 chapter checklist.

    `index` is epub_io.Chapter.index — the stable 0-based document position,
    which is what worker.select_chapters() filters on. It is NOT the row's
    position in this list.
    """
    index: int
    title: str
    checked: bool = True


def _default_formats() -> dict[str, bool]:
    return {"txt": True, "epub": False, "html": False}


@dataclass
class WizardState:
    step: int = 1
    epub_path: str = ""
    book_title: str = ""
    book_author: str = ""
    chapters: list[ChapterRow] = field(default_factory=list)
    model: str = ""                 # seeded from SETTINGS["default_model"]
    mode: str = "sr"                # sr | full | sum | key
    key_ideas_lang: str = "es"      # es | en
    cefr_level: str = "B2"          # B1 | B2 | C1 | C2
    carry: str = "off"              # off | names | tail | both
    keep_pct: int = 40
    creativity: int = 5
    formats: dict[str, bool] = field(default_factory=_default_formats)
    mp3_enabled: bool = False
    voice: str | None = None
    out_folder: str = ""
    meta_title: str = ""
    meta_creator: str = ""
    meta_language: str = "es"
    meta_contributor: str = ""
    timeout_sec: int = 1200         # seeded from settings.OLLAMA_TIMEOUT
    max_tokens: int = 8192          # seeded from SETTINGS["mlx_max_tokens"]
    chunk_words: int = 2000
    run_state: str = "idle"         # idle|running|success|failed|aborting|aborted


# ──────────────────────────────────────────────────────────────
#  Derivations
# ──────────────────────────────────────────────────────────────
def derive_target_is_spanish(mode: str, key_ideas_lang: str) -> bool:
    """True when the run produces Spanish text.

    There is no explicit target-language picker: it falls out of the mode,
    and for key-ideas out of that mode's own language toggle. Gates the
    Step-2 Spanish-level card, the recap line's level segment, and which
    voice list Step 3 populates.
    """
    return mode in ("sr", "full") or (mode == "key" and key_ideas_lang == "es")


def validation_errors(state: WizardState) -> list[tuple[int, str]]:
    """Return (step_number, message) for each unmet start requirement.

    One source of truth for three consumers: Start's enabled state, Start's
    tooltip, and the error decoration on the step-rail badges.
    """
    errs: list[tuple[int, str]] = []
    if not state.epub_path:
        errs.append((1, "Select an EPUB file"))
    elif not any(row.checked for row in state.chapters):
        # Only meaningful once a book is loaded — otherwise it double-reports.
        errs.append((1, "Select at least one chapter"))
    if not any(state.formats.values()):
        errs.append((3, "Select at least one output format"))
    return errs


def resume_hint(backend: str) -> str:
    """Recovery copy for the 💾 log line after a resumable failure.

    On mlx there is no timeout to raise: generation runs in-process and is
    bounded by max_tokens instead.
    """
    if backend == "ollama":
        return "Raise the timeout, then press Resume."
    return "Adjust settings, then press Resume."


def creativity_notch(n: int) -> tuple[str, str]:
    """(display name, ramp key) for creativity level *n* (1-10)."""
    return CREATIVITY_NOTCHES[n]


def creativity_readout(n: int) -> str:
    """e.g. 'Enriched+ — level 5/10  (temp ≈ 0.68)'.

    The temperature comes from settings.creativity_to_temperature — the very
    function worker.py passes to the model. The handoff mockup showed 0.44,
    computed as (n-1)/9; that formula is not what the pipeline uses and is
    not reproduced here.
    """
    name, _ = CREATIVITY_NOTCHES[n]
    return f"{name} — level {n}/10  (temp ≈ {creativity_to_temperature(n)})"


def is_creativity_sweet(n: int) -> bool:
    return CREATIVITY_SWEET_MIN <= n <= CREATIVITY_SWEET_MAX


def keep_pct_readout(pct: int) -> tuple[str, bool]:
    """(readout text, is_sweet_spot) for the summarisation-depth slider."""
    text = f"Keep {pct}% of original (↓ {100 - pct}% reduction)"
    return text, KEEP_SWEET_MIN <= pct <= KEEP_SWEET_MAX


def recap_text(state: WizardState, model_label: str) -> str:
    """The one-line step-1 recap shown from step 2 onward.

    Shows the real selection ('3 / 11 chapters'), collapsing to a bare count
    when everything is ticked. The model's config label is truncated at its
    first parenthesis so '(recommended)' does not eat the line. The CEFR
    level appears only when the run actually produces Spanish.
    """
    total = len(state.chapters)
    selected = sum(1 for row in state.chapters if row.checked)
    chapters = (
        f"{total} chapters" if selected == total
        else f"{selected} / {total} chapters"
    )
    parts = [
        "Step 1",
        Path(state.epub_path).name,
        chapters,
        model_label.split("(")[0].strip(),
    ]
    if derive_target_is_spanish(state.mode, state.key_ideas_lang):
        parts.append(state.cefr_level)
    return " · ".join(parts)


def build_config(state: WizardState, backend: str) -> dict:
    """Translate WizardState into ProcessingWorker's config dict.

    Emits all 22 keys on both backends. The dict shape must never branch on
    backend: _on_resume() spreads **config, and a shape that varies would
    make the resume path backend-dependent. The worker simply ignores the
    key its backend does not use (self._timeout is unread on mlx,
    self._max_tokens on ollama).

    *backend* is passed in rather than read from SETTINGS so the caller can
    capture it once at Start and resume can never flip backends mid-book.
    """
    worker_mode = MODE_TO_WORKER[state.mode]
    summary_lang = state.key_ideas_lang
    target_lang = (
        summary_lang if worker_mode == "summarise_key_ideas"
        else TARGET_LANG[worker_mode]
    )
    return {
        "epub_path": state.epub_path,
        "model": state.model,
        "backend": backend,
        "selected_chapters": [r.index for r in state.chapters if r.checked],
        "mode": worker_mode,
        "level": state.cefr_level,
        "keep_pct": state.keep_pct,
        "creativity": state.creativity,
        "carry_mode": CARRY_TO_WORKER[state.carry],
        "summary_lang": summary_lang,
        "target_lang": target_lang,
        "out_format": [f for f in ("txt", "epub", "html")
                       if state.formats.get(f)],
        "out_folder": state.out_folder or str(Path(state.epub_path).parent),
        "generate_mp3": state.mp3_enabled,
        "voice": state.voice if state.mp3_enabled else None,
        "meta_title": state.meta_title.strip(),
        "meta_creator": state.meta_creator.strip(),
        "meta_language": state.meta_language.strip() or "es",
        "meta_contributor": state.meta_contributor.strip(),
        "chunk_size": state.chunk_words,
        "timeout": state.timeout_sec,
        "max_tokens": state.max_tokens,
    }
