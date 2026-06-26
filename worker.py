"""
worker.py
---------
ProcessingWorker runs the full pipeline in a background QThread so the
UI stays responsive during long processing jobs.

Pipeline per chapter:
  1. Summarise (English → compressed English) via Ollama
  2. Rewrite   (compressed English → Spanish at target CEFR level)

Output is written as plain text or EPUB depending on the job config.
"""

import html
import re
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from prompts import (
    build_summary_prompt,
    build_rewrite_prompt,
    build_translation_prompt,
    build_key_ideas_prompt,
    build_book_key_ideas_prompt,
    KEY_IDEAS_HEADER,
    BOOK_KEY_IDEAS_HEADER,
)
from settings import creativity_to_temperature, OLLAMA_TIMEOUT, SETTINGS


# ──────────────────────────────────────────────────────────────
#  WORKER
# ──────────────────────────────────────────────────────────────
class ProcessingWorker(QThread):
    """
    Background thread that drives the summarise → rewrite pipeline.

    Signals
    -------
    log(message, level)
        Emitted for each log line.  level is one of:
        "info", "success", "warning", "error", "muted".
    progress(current, total)
        Emitted after each completed step (summarise or rewrite).
    finished(success, output_path)
        Emitted when the job completes or fails.
    """

    log = pyqtSignal(str, str)        # (message, level)
    progress = pyqtSignal(int, int)   # (current, total)
    finished = pyqtSignal(bool, str)  # (success, output_path)

    def __init__(self, config: dict) -> None:
        super().__init__()
        self.config = config
        self._abort = False
        self._timeout = config.get("timeout", OLLAMA_TIMEOUT)
        self._chunk_size = config.get("chunk_size", 2000)
        # Populated during run(); readable by the app after finished(False).
        self.completed_results: list[tuple[str, str]] = []
        self.failed_at_chapter: int = 0

    def abort(self) -> None:
        """Request a clean stop after the current Ollama call."""
        self._abort = True

    # ── main entry point ──────────────────────────────────────
    def run(self) -> None:
        try:
            from ebooklib import epub as ebooklib_epub
            import httpx
            import epub_io
        except ImportError as exc:
            self.log.emit(
                f"Missing dependency: {exc}\n"
                "Run: pip install ebooklib httpx beautifulsoup4",
                "error",
            )
            self.finished.emit(False, "")
            return

        cfg = self.config
        epub_path = cfg["epub_path"]
        level = cfg["level"]
        keep_pct = cfg["keep_pct"]
        model = cfg["model"]
        out_format = cfg["out_format"]
        out_folder = (
            Path(cfg["out_folder"]) if cfg.get("out_folder")
            else Path(epub_path).parent
        )
        creativity = cfg["creativity"]
        temperature = creativity_to_temperature(creativity)
        mode = cfg.get("mode", "summarise_rewrite")  # or "translate"
        summary_lang = cfg.get("summary_lang", "es")
        resume_from = cfg.get("resume_from", 0)
        meta = {
            "title": cfg.get("meta_title") or Path(epub_path).stem,
            "creator": cfg.get("meta_creator") or "",
            "language": cfg.get("meta_language") or "es",
            "contributor": cfg.get("meta_contributor") or "",
        }

        # ── load source EPUB ──────────────────────────────────
        self.log.emit(f"📖  Loading {Path(epub_path).name}…", "info")

        preview_chars = SETTINGS.get("chapter_title_preview_chars", 50)
        try:
            all_chapters = epub_io.extract_chapters(epub_path, preview_chars)
        except Exception as exc:
            self.log.emit(f"Failed to open EPUB: {exc}", "error")
            self.finished.emit(False, "")
            return
        if not all_chapters:
            self.log.emit("No readable chapters found in EPUB.", "error")
            self.finished.emit(False, "")
            return

        chapters = epub_io.select_chapters(
            all_chapters, cfg.get("selected_chapters")
        )
        if not chapters:
            self.log.emit("No chapters selected to process.", "error")
            self.finished.emit(False, "")
            return
        if len(chapters) < len(all_chapters):
            self.log.emit(
                f"ℹ️   Processing {len(chapters)} of "
                f"{len(all_chapters)} chapters.", "info"
            )

        if mode == "summarise_key_ideas":
            # summary (+ rewrite for Spanish) + 1 key-ideas call per chapter
            steps_per_chapter = 3 if summary_lang == "es" else 2
        elif mode in ("translate", "summarise_only"):
            steps_per_chapter = 1
        else:
            steps_per_chapter = 2
        total_steps = len(chapters) * steps_per_chapter
        out_formats = out_format if isinstance(out_format, list) else [out_format]
        stem = Path(epub_path).stem
        # Seed results and progress from any previously completed chapters.
        results: list[tuple[str, str]] = list(cfg.get("prior_results", []))
        step = resume_from * steps_per_chapter

        if resume_from > 0:
            self.log.emit(
                f"⏩  Resuming from chapter {resume_from + 1} "
                f"({resume_from} chapter(s) already done).",
                "info",
            )
        else:
            self.log.emit(f"✅  Found {len(chapters)} chapter(s) to process.", "success")

        for idx, chapter in enumerate(chapters):
            text = chapter.text
            # Skip chapters already completed in a prior run.
            if idx < resume_from:
                continue

            if self._abort:
                self.log.emit("⛔  Aborted by user.", "warning")
                self.completed_results = results
                self.failed_at_chapter = idx
                self.finished.emit(False, "")
                return

            chunks = self._split_into_chunks(text, self._chunk_size)
            n_chunks = len(chunks)
            if n_chunks > 1:
                self.log.emit(
                    f"\n── Chapter {idx + 1}/{len(chapters)}: "
                    f"split into {n_chunks} chunks (~{self._chunk_size} words each).", "info"
                )

            spanish_parts: list[str] = []

            for chunk_idx, chunk in enumerate(chunks):
                chunk_label = (
                    f"{idx + 1}.{chunk_idx + 1}/{n_chunks}"
                    if n_chunks > 1 else str(idx + 1)
                )

                if self._abort:
                    self.log.emit("⛔  Aborted by user.", "warning")
                    self.completed_results = results
                    self.failed_at_chapter = idx
                    self.finished.emit(False, "")
                    return

                if mode == "translate":
                    # ── Translation-only: one LLM call per chunk ──────────
                    self.log.emit(
                        f"\n── Chapter {chunk_label}/{len(chapters)}: translating…", "info"
                    )
                    spanish = self._ollama_call(
                        model,
                        build_translation_prompt(chunk, level, idx, creativity),
                        label=f"Translate {chunk_label}",
                        temperature=temperature,
                    )
                    if spanish is None:
                        self.completed_results = results
                        self.failed_at_chapter = idx
                        self.finished.emit(False, "")
                        return
                    spanish_parts.append(self._strip_asterisk_markers(spanish))

                elif mode == "summarise_only":
                    # ── Summarise-only: condense to English, no rewrite ───
                    self.log.emit(
                        f"\n── Chapter {chunk_label}/{len(chapters)}: summarising…", "info"
                    )
                    summary = self._ollama_call(
                        model,
                        build_summary_prompt(chunk, keep_pct),
                        label=f"Summary {chunk_label}",
                        temperature=temperature,
                    )
                    if summary is None:
                        self.completed_results = results
                        self.failed_at_chapter = idx
                        self.finished.emit(False, "")
                        return
                    spanish_parts.append(summary)

                elif mode == "summarise_key_ideas":
                    # Summary path mirrors English (summarise_only) or Spanish
                    # (summarise→rewrite) depending on summary_lang. Key ideas
                    # are extracted once per chapter, after the chunk loop.
                    self.log.emit(
                        f"\n── Chapter {chunk_label}/{len(chapters)}: summarising…",
                        "info",
                    )
                    summary = self._ollama_call(
                        model,
                        build_summary_prompt(chunk, keep_pct),
                        label=f"Summary {chunk_label}",
                        temperature=temperature,
                    )
                    if summary is None:
                        self.completed_results = results
                        self.failed_at_chapter = idx
                        self.finished.emit(False, "")
                        return

                    if summary_lang == "es":
                        if self._abort:
                            self.completed_results = results
                            self.failed_at_chapter = idx
                            self.log.emit("⛔  Aborted by user.", "warning")
                            self.finished.emit(False, "")
                            return
                        self.log.emit(
                            f"── Chapter {chunk_label}/{len(chapters)}: "
                            f"rewriting in Spanish ({level}, "
                            f"creativity {creativity}/10)…",
                            "info",
                        )
                        rewritten = self._ollama_call(
                            model,
                            build_rewrite_prompt(summary, level, idx, creativity),
                            label=f"Rewrite {chunk_label}",
                            temperature=temperature,
                        )
                        if rewritten is None:
                            self.completed_results = results
                            self.failed_at_chapter = idx
                            self.finished.emit(False, "")
                            return
                        spanish_parts.append(self._strip_asterisk_markers(rewritten))
                    else:
                        spanish_parts.append(summary)

                else:
                    # ── Summarise → Rewrite (original two-step pipeline) ──
                    # ── step 1: summarise ─────────────────────────────
                    self.log.emit(
                        f"\n── Chapter {chunk_label}/{len(chapters)}: summarising…", "info"
                    )
                    summary = self._ollama_call(
                        model,
                        build_summary_prompt(chunk, keep_pct),
                        label=f"Summary {chunk_label}",
                        temperature=temperature,
                    )
                    if summary is None:
                        self.completed_results = results
                        self.failed_at_chapter = idx
                        self.finished.emit(False, "")
                        return

                    if self._abort:
                        self.completed_results = results
                        self.failed_at_chapter = idx
                        self.log.emit("⛔  Aborted by user.", "warning")
                        self.finished.emit(False, "")
                        return

                    # ── step 2: rewrite in Spanish ────────────────────
                    self.log.emit(
                        f"── Chapter {chunk_label}/{len(chapters)}: "
                        f"rewriting in Spanish ({level}, creativity {creativity}/10)…",
                        "info",
                    )
                    spanish = self._ollama_call(
                        model,
                        build_rewrite_prompt(summary, level, idx, creativity),
                        label=f"Rewrite {chunk_label}",
                        temperature=temperature,
                    )
                    if spanish is None:
                        self.completed_results = results
                        self.failed_at_chapter = idx
                        self.finished.emit(False, "")
                        return

                    spanish_parts.append(self._strip_asterisk_markers(spanish))

            chapter_body = "\n\n".join(spanish_parts)

            # For the key-ideas mode, append a key-ideas section to the body.
            if mode == "summarise_key_ideas":
                self.log.emit(
                    f"── Chapter {idx + 1}/{len(chapters)}: extracting key ideas…",
                    "info",
                )
                ideas = self._ollama_call(
                    model,
                    build_key_ideas_prompt(chapter_body, summary_lang, level),
                    label=f"Key ideas {idx + 1}",
                    temperature=temperature,
                )
                if ideas is None:
                    self.completed_results = results
                    self.failed_at_chapter = idx
                    self.finished.emit(False, "")
                    return
                ideas = (
                    self._strip_asterisk_markers(ideas)
                    if summary_lang == "es" else ideas
                )
                chapter_body = f"{chapter_body}\n\n{ideas.strip()}"

            step += steps_per_chapter
            self.progress.emit(step, total_steps)
            if mode == "summarise_only" or (
                mode == "summarise_key_ideas" and summary_lang == "en"
            ):
                ch_title = f"Chapter {idx + 1}"
            else:
                ch_title = f"Capítulo {idx + 1}"
            results.append((ch_title, chapter_body))
            self.completed_results = results[:]
            if "txt" in out_formats:
                self._write_chapter_file(
                    out_folder, stem, level,
                    chapter.index, chapter.title,
                    chapter_body,
                )
            self.log.emit(f"✅  Chapter {idx + 1} done.", "success")

        # ── book-wide key ideas (only if ≥ 2 chapters were processed) ──
        if mode == "summarise_key_ideas" and len(results) >= 2:
            ch_header = KEY_IDEAS_HEADER.get(summary_lang, KEY_IDEAS_HEADER["en"])
            book_header = BOOK_KEY_IDEAS_HEADER.get(
                summary_lang, BOOK_KEY_IDEAS_HEADER["en"]
            )
            self.log.emit("\n🧩  Synthesising book-wide key ideas…", "info")
            ideas_text = self._collect_chapter_ideas(results, ch_header)
            book = self._ollama_call(
                model,
                build_book_key_ideas_prompt(ideas_text, summary_lang, level),
                label="Book key ideas",
                temperature=temperature,
            )
            if book:
                book_body = (
                    self._strip_asterisk_markers(book)
                    if summary_lang == "es" else book
                ).strip()
                results.append((book_header, book_body))
                self.completed_results = results[:]
                if "txt" in out_formats:
                    # index len(all_chapters) keeps the NN prefix after the
                    # last chapter; title is the localized book header.
                    self._write_chapter_file(
                        out_folder, stem, level,
                        len(all_chapters), book_header, book_body,
                    )
                self.log.emit("🧩  Book-wide key ideas added.", "success")
            else:
                self.log.emit(
                    "Book key-ideas synthesis failed; continuing without it.",
                    "warning",
                )

        # ── write output ──────────────────────────────────────
        out_folder.mkdir(parents=True, exist_ok=True)
        if mode == "summarise_only" or (
            mode == "summarise_key_ideas" and summary_lang == "en"
        ):
            lang_label = "English summary"
        else:
            lang_label = f"Spanish {level}"
        out_paths = []

        for fmt in out_formats:
            if fmt == "txt":
                out_paths.append(
                    self._write_txt(results, out_folder, stem, level, meta, lang_label)
                )
            elif fmt == "epub":
                out_paths.append(
                    self._write_epub(
                        results, out_folder, stem, level, meta, ebooklib_epub, lang_label
                    )
                )
            elif fmt == "html":
                out_paths.append(
                    self._write_html(results, out_folder, stem, level, meta, lang_label)
                )

        # ── MP3 audiobook (optional) ──────────────────────────
        # Guard on "txt" is defensive — the UI already enforces it — but
        # keeps the worker correct in isolation.
        if cfg.get("generate_mp3") and "txt" in out_formats:
            self._generate_mp3(results, out_folder, stem, level, meta, cfg)

        self.finished.emit(True, ", ".join(str(p) for p in out_paths))

    # ── MP3 audiobook ─────────────────────────────────────────
    def _generate_mp3(
        self,
        results: list[tuple[str, str]],
        out_folder: Path,
        stem: str,
        level: str,
        meta: dict,
        cfg: dict,
    ) -> None:
        """Synthesise *results* into one MP3 via Kokoro. Never raises —
        a failure here must not undo the already-written text output."""
        # Lazy import: pulls in torch only when MP3 output was requested.
        from tts import (
            TTS_AVAILABLE, TTS_IMPORT_ERROR, kokoro_lang_code, synthesise_book,
        )

        if not TTS_AVAILABLE:
            self.log.emit(
                f"MP3 requested but Kokoro is not installed "
                f"({TTS_IMPORT_ERROR}). See kokoro.md.",
                "error",
            )
            return

        voice = cfg.get("voice")
        if not voice:
            self.log.emit(
                "MP3 requested but no voice is selected — check the "
                "'voices' block in bookweaver.json.",
                "error",
            )
            return
        lang_code = kokoro_lang_code(cfg.get("target_lang", "es"), voice)
        tts_cfg = SETTINGS.get("tts", {})
        out_path = out_folder / f"{stem}_ES_{level}.mp3"

        self.log.emit(
            f"\n🔊  Synthesising audiobook with voice '{voice}' "
            f"(first run downloads the Kokoro model from Hugging Face)…",
            "info",
        )
        try:
            synthesise_book(
                chapters=results,
                voice=voice,
                lang_code=lang_code,
                out_path=out_path,
                bitrate_kbps=int(tts_cfg.get("mp3_bitrate_kbps", 96)),
                inter_chapter_silence_ms=int(
                    tts_cfg.get("inter_chapter_silence_ms", 1500)
                ),
                post_title_silence_ms=int(
                    tts_cfg.get("post_title_silence_ms", 1000)
                ),
                book_title=meta["title"],
                author=meta["creator"],
                on_chapter=lambda i, n: self.log.emit(
                    f"   ↳ Chapter {i}/{n} synthesised.", "muted"
                ),
            )
            self.log.emit(f"🎧  Saved MP3 → {out_path}", "success")
        except Exception as exc:
            self.log.emit(f"MP3 generation failed: {exc}", "error")

    # ── output writers ────────────────────────────────────────
    @staticmethod
    def _chapter_block(title: str, body: str) -> str:
        """The shared `===`-delimited chapter block used by both the
        assembled .txt output and the per-chapter .txt files."""
        return f"\n{'=' * 60}\n{title}\n{'=' * 60}\n\n{body}\n\n"

    @staticmethod
    def _safe_filename(title: str) -> str:
        """Make *title* safe for a filename: strip illegal characters,
        collapse whitespace, cap length. Falls back to 'untitled'."""
        cleaned = re.sub(r'[/\\:*?"<>|]', "", title)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned[:80].strip() or "untitled"

    def _write_chapter_file(
        self,
        out_folder: Path,
        stem: str,
        level: str,
        index: int,
        title: str,
        body: str,
    ) -> Path:
        """Write a single chapter's result to
        {stem}_ES_{level}_chapters/{NN} - {title}.txt and return the path.
        NN = index + 1, matching the number shown in the UI chapter list."""
        chapters_dir = out_folder / f"{stem}_ES_{level}_chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        fname = f"{index + 1:02d} - {self._safe_filename(title)}.txt"
        out_path = chapters_dir / fname
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(self._chapter_block(title, body))
        self.log.emit(f"   ↳ Saved chapter file → {out_path.name}", "muted")
        return out_path

    def _write_txt(
        self,
        results: list[tuple[str, str]],
        out_folder: Path,
        stem: str,
        level: str,
        meta: dict,
        lang_label: str = "",
    ) -> Path:
        out_path = out_folder / f"{stem}_ES_{level}.txt"
        with open(out_path, "w", encoding="utf-8") as fh:
            if meta["title"]:
                fh.write(f"{meta['title']}\n")
            if meta["creator"]:
                fh.write(f"by {meta['creator']}\n")
            fh.write(f"{lang_label or f'Spanish ({level})'}\n{'─' * 60}\n\n")
            for title, body in results:
                fh.write(self._chapter_block(title, body))
        self.log.emit(f"\n📄  Saved plain text → {out_path}", "success")
        return out_path

    def _write_epub(
        self,
        results: list[tuple[str, str]],
        out_folder: Path,
        stem: str,
        level: str,
        meta: dict,
        ebooklib_epub,
        lang_label: str = "",
    ) -> Path:
        label = lang_label or f"Spanish {level}"
        out_path = out_folder / f"{stem}_ES_{level}.epub"
        try:
            out_book = ebooklib_epub.EpubBook()
            out_book.set_title(meta["title"] or f"{stem} ({label})")
            out_book.set_language(meta["language"])
            if meta["creator"]:
                out_book.add_author(meta["creator"])
            if meta["contributor"]:
                out_book.add_metadata("DC", "contributor", meta["contributor"])
            out_book.add_metadata(
                "DC",
                "description",
                f"{label} generated by BookWeaver via Ollama.",
            )

            spine = ["nav"]
            toc = []
            for i, (title, body) in enumerate(results):
                chap = ebooklib_epub.EpubHtml(
                    title=title,
                    file_name=f"chap_{i + 1:03d}.xhtml",
                    lang="es",
                )
                safe_body = (
                    body
                    .replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                )
                paragraphs = "".join(
                    f"<p>{p.strip()}</p>"
                    for p in safe_body.split("\n")
                    if p.strip()
                )
                chap.set_content(
                    f"<html><body>"
                    f"<h2>{html.escape(title)}</h2>"
                    f"{paragraphs}"
                    f"</body></html>"
                )
                out_book.add_item(chap)
                spine.append(chap)
                toc.append(chap)

            out_book.toc = toc
            out_book.spine = spine
            out_book.add_item(ebooklib_epub.EpubNcx())
            out_book.add_item(ebooklib_epub.EpubNav())
            ebooklib_epub.write_epub(str(out_path), out_book)
            self.log.emit(f"\n📗  Saved EPUB → {out_path}", "success")

        except Exception as exc:
            self.log.emit(
                f"EPUB write failed: {exc}. Falling back to .txt", "warning"
            )
            out_path = out_path.with_suffix(".txt")
            with open(out_path, "w", encoding="utf-8") as fh:
                for title, body in results:
                    fh.write(
                        f"\n{'=' * 60}\n{title}\n{'=' * 60}\n\n{body}\n\n"
                    )

        return out_path

    def _write_html(
        self,
        results: list[tuple[str, str]],
        out_folder: Path,
        stem: str,
        level: str,
        meta: dict,
        lang_label: str = "",
    ) -> Path:
        label = lang_label or f"Spanish {level}"
        out_path = out_folder / f"{stem}_ES_{level}.html"
        title = html.escape(meta["title"] or f"{stem} ({label})")
        author = html.escape(meta["creator"]) if meta["creator"] else ""

        chapters_html = []
        for ch_title, body in results:
            paragraphs = "".join(
                f"    <p>{html.escape(p.strip())}</p>\n"
                for p in body.split("\n")
                if p.strip()
            )
            chapters_html.append(
                f'  <section class="chapter">\n'
                f'    <h2>{html.escape(ch_title)}</h2>\n'
                f'{paragraphs}'
                f'  </section>\n'
            )

        author_line = f'    <p class="author">{author}</p>\n' if author else ""
        doc = (
            "<!DOCTYPE html>\n"
            '<html lang="es">\n'
            "<head>\n"
            '  <meta charset="UTF-8">\n'
            f'  <title>{title}</title>\n'
            "  <style>\n"
            "    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }\n"
            "    body {\n"
            "      font-family: Arial, 'Helvetica Neue', Helvetica, sans-serif;\n"
            "      font-size: 17px;\n"
            "      line-height: 1.75;\n"
            "      color: #1a1a1a;\n"
            "      background: #fafafa;\n"
            "      max-width: 720px;\n"
            "      margin: 0 auto;\n"
            "      padding: 3rem 2rem 6rem;\n"
            "    }\n"
            "    header { margin-bottom: 3rem; border-bottom: 2px solid #e0e0e0; padding-bottom: 1.5rem; }\n"
            "    header h1 { font-size: 2rem; font-weight: 700; letter-spacing: -0.5px; }\n"
            "    header .author { color: #555; margin-top: 0.4rem; font-size: 1rem; }\n"
            "    header .meta { color: #999; font-size: 0.82rem; margin-top: 0.25rem; }\n"
            "    .chapter { margin-top: 3.5rem; }\n"
            "    .chapter h2 {\n"
            "      font-size: 1.15rem;\n"
            "      font-weight: 700;\n"
            "      letter-spacing: 0.5px;\n"
            "      text-transform: uppercase;\n"
            "      color: #444;\n"
            "      margin-bottom: 1.2rem;\n"
            "      padding-bottom: 0.4rem;\n"
            "      border-bottom: 1px solid #e8e8e8;\n"
            "    }\n"
            "    p { margin-top: 0.9rem; text-align: justify; }\n"
            "    p:first-of-type { margin-top: 0; }\n"
            "  </style>\n"
            "</head>\n"
            "<body>\n"
            "  <header>\n"
            f"    <h1>{title}</h1>\n"
            f"{author_line}"
            f'    <p class="meta">{html.escape(label)} · generated by BookWeaver</p>\n'
            "  </header>\n"
            + "".join(chapters_html)
            + "</body>\n</html>\n"
        )
        out_path.write_text(doc, encoding="utf-8")
        self.log.emit(f"\n🌐  Saved HTML → {out_path}", "success")
        return out_path

    # ── text helpers ──────────────────────────────────────────
    @staticmethod
    def _split_into_chunks(text: str, max_words: int = 2000) -> list[str]:
        """
        Split *text* into chunks of at most *max_words* words, always
        breaking at paragraph boundaries.  A paragraph is a block of text
        separated by one or more blank lines.
        """
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks: list[str] = []
        current: list[str] = []
        current_words = 0

        for para in paragraphs:
            para_words = len(para.split())
            if current and current_words + para_words > max_words:
                chunks.append("\n\n".join(current))
                current = []
                current_words = 0
            current.append(para)
            current_words += para_words

        if current:
            chunks.append("\n\n".join(current))

        return chunks or [text]

    @staticmethod
    def _extract_key_ideas(body: str, header: str) -> str:
        """Return the key-ideas section of *body* (from the first occurrence
        of *header* to the end), or the whole *body* if *header* is absent.
        Reads from result bodies so it is correct on fresh and resumed runs."""
        idx = body.find(header)
        return body[idx:] if idx != -1 else body

    @staticmethod
    def _collect_chapter_ideas(
        results: list[tuple[str, str]], header: str
    ) -> str:
        """Concatenate every chapter's key-ideas section for the book-wide
        synthesis prompt."""
        return "\n\n".join(
            ProcessingWorker._extract_key_ideas(body, header)
            for _, body in results
        )

    @staticmethod
    def _strip_asterisk_markers(text: str) -> str:
        """Remove *word* / *phrase* markers the LLM adds around proper nouns."""
        import re
        return re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)', r'\1', text)
    def _ollama_call(
        self,
        model: str,
        prompt: str,
        *,
        label: str = "",
        temperature: float,
    ) -> str | None:
        """
        Send *prompt* to the local Ollama instance and return the response
        text, or None on any error.
        """
        try:
            import httpx
            self.log.emit(
                f"   ↳ Calling {model} (temp={temperature})…", "muted"
            )
            with httpx.Client(timeout=self._timeout) as client:
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
                    self.log.emit(
                        f"   ⚠️  Empty response for {label}", "warning"
                    )
                    return None
                word_count = len(result.split())
                self.log.emit(
                    f"   ✓  {label}: {word_count} words generated.", "muted"
                )
                return result
        except Exception as exc:
            self.log.emit(f"   Ollama error ({label}): {exc}", "error")
            return None
