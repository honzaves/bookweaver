"""
tts.py
------
Kokoro-powered text-to-speech: synthesise chapters into a single MP3
audiobook with ID3v2 chapter markers.

Pure functions only — no Qt, no imports from app/worker. The worker hands
in a list of (title, body) tuples and an output path and gets back a
written file (or an exception).

All heavy dependencies (kokoro/torch, soundfile, lameenc, mutagen) are
optional: the import gate below records availability so the rest of the
app can run without them. See kokoro.md for installation instructions.
"""

from pathlib import Path
from typing import Callable

try:
    import kokoro       # noqa: F401  — pulls in torch (~2.5 GB install)
    import numpy        # noqa: F401
    import soundfile    # noqa: F401
    import lameenc      # noqa: F401
    import mutagen      # noqa: F401
    TTS_AVAILABLE = True
    TTS_IMPORT_ERROR: Exception | None = None
except ImportError as exc:
    TTS_AVAILABLE = False
    TTS_IMPORT_ERROR = exc

# Kokoro models output mono audio at a fixed rate.
SAMPLE_RATE = 24_000


# ──────────────────────────────────────────────────────────────
#  PURE HELPERS (usable without Kokoro installed)
# ──────────────────────────────────────────────────────────────
def kokoro_lang_code(target_lang: str, voice: str) -> str:
    """
    Map a BookWeaver target language + voice name to a Kokoro pipeline
    language code: "e" = Spanish, "a" = American English, "b" = British
    English (UK voices are prefixed bf_/bm_).
    """
    if target_lang == "es":
        return "e"
    if voice.startswith(("bf_", "bm_")):
        return "b"
    return "a"


# ──────────────────────────────────────────────────────────────
#  SYNTHESIS
# ──────────────────────────────────────────────────────────────
def _silence(duration_ms: int):
    import numpy as np
    return np.zeros(SAMPLE_RATE * duration_ms // 1000, dtype=np.float32)


def _make_pipeline(lang_code: str):
    # SystemExit must be trapped too: misaki's English G2P auto-downloads
    # the spaCy model en_core_web_sm via pip and calls sys.exit(1) when
    # that fails (e.g. uv-created venvs have no pip). Letting it escape
    # would kill the worker thread without emitting finished().
    from kokoro import KPipeline
    try:
        return KPipeline(lang_code=lang_code)
    except (Exception, SystemExit) as exc:
        _reraise_with_hint(exc, lang_code)
        raise


def _reraise_with_hint(exc: BaseException, lang_code: str) -> None:
    if lang_code == "e" and "espeak" in str(exc).lower():
        raise RuntimeError(
            f"Spanish synthesis needs espeak-ng — run: brew install espeak-ng "
            f"(underlying error: {exc})"
        ) from exc
    if isinstance(exc, SystemExit):
        raise RuntimeError(
            "Kokoro G2P setup failed — likely the spaCy model "
            "en_core_web_sm is missing and its auto-download could not "
            "run. Install it manually (see kokoro.md §3.2)."
        ) from exc


def _synth(pipe, text: str, voice: str, lang_code: str):
    """Run Kokoro over *text* and return one concatenated float32 array."""
    import numpy as np
    try:
        parts = [audio for _, _, audio in pipe(text, voice=voice)]
    except (Exception, SystemExit) as exc:
        _reraise_with_hint(exc, lang_code)
        raise
    if not parts:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate([np.asarray(p, dtype=np.float32) for p in parts])


def encode_mp3(audio_f32, sr: int, bitrate_kbps: int) -> bytes:
    """Encode a mono float32 array to MP3 bytes via lameenc."""
    import lameenc
    import numpy as np
    enc = lameenc.Encoder()
    enc.set_bit_rate(bitrate_kbps)
    enc.set_in_sample_rate(sr)
    enc.set_channels(1)
    enc.set_quality(2)  # 0 = best, 9 = worst
    pcm16 = (np.clip(audio_f32, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
    return bytes(enc.encode(pcm16)) + bytes(enc.flush())


def _tag_mp3(
    out_path: Path,
    chapter_offsets: list[tuple[str, int, int]],  # (title, start_ms, end_ms)
    book_title: str,
    author: str,
) -> None:
    """Embed ID3v2 CHAP/CTOC chapter markers plus basic title/artist tags."""
    from mutagen.id3 import ID3, CHAP, CTOC, TIT2, TPE1, TALB, CTOCFlags

    tags = ID3()
    if book_title:
        tags.add(TIT2(encoding=3, text=book_title))
    if author:
        tags.add(TPE1(encoding=3, text=author))
    tags.add(TALB(encoding=3, text=book_title or "BookWeaver audiobook"))

    child_ids = []
    for i, (title, start_ms, end_ms) in enumerate(chapter_offsets):
        cid = f"ch{i + 1}"
        child_ids.append(cid)
        tags.add(CHAP(
            element_id=cid,
            start_time=start_ms,
            end_time=end_ms,
            start_offset=0xFFFFFFFF,
            end_offset=0xFFFFFFFF,
            sub_frames=[TIT2(encoding=3, text=title)],
        ))
    tags.add(CTOC(
        element_id="toc",
        flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
        child_element_ids=child_ids,
        sub_frames=[TIT2(encoding=3, text="Chapters")],
    ))
    tags.save(str(out_path))


def synthesise_book(
    *,
    chapters: list[tuple[str, str]],   # (title, body) pairs
    voice: str,
    lang_code: str,                    # Kokoro code: "e", "a", or "b"
    out_path: Path,
    bitrate_kbps: int = 96,
    inter_chapter_silence_ms: int = 1500,
    post_title_silence_ms: int = 1000,
    book_title: str = "",
    author: str = "",
    on_chapter: Callable[[int, int], None] | None = None,
) -> None:
    """Synthesise all chapters into a single MP3 with ID3 chapter markers."""
    if not TTS_AVAILABLE:
        raise RuntimeError(
            f"TTS dependencies are not installed ({TTS_IMPORT_ERROR}). "
            "See kokoro.md."
        )
    import numpy as np

    pipe = _make_pipeline(lang_code)

    segments: list = []
    chapter_offsets: list[tuple[str, int, int]] = []
    cursor = 0  # running sample position
    n = len(chapters)

    for i, (title, body) in enumerate(chapters):
        if i > 0:
            gap = _silence(inter_chapter_silence_ms)
            segments.append(gap)
            cursor += len(gap)

        start = cursor
        for seg in (
            _synth(pipe, title, voice, lang_code),
            _silence(post_title_silence_ms),
            _synth(pipe, body, voice, lang_code),
        ):
            segments.append(seg)
            cursor += len(seg)

        chapter_offsets.append(
            (title, start * 1000 // SAMPLE_RATE, cursor * 1000 // SAMPLE_RATE)
        )
        if on_chapter:
            on_chapter(i + 1, n)

    audio = (
        np.concatenate(segments) if segments
        else np.zeros(0, dtype=np.float32)
    )
    out_path.write_bytes(encode_mp3(audio, SAMPLE_RATE, bitrate_kbps))
    _tag_mp3(out_path, chapter_offsets, book_title, author)
