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
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from prompts import build_summary_prompt, build_rewrite_prompt
from settings import creativity_to_temperature, OLLAMA_TIMEOUT


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
        # Populated during run(); readable by the app after finished(False).
        self.completed_results: list[tuple[str, str]] = []
        self.failed_at_chapter: int = 0

    def abort(self) -> None:
        """Request a clean stop after the current Ollama call."""
        self._abort = True

    # ── main entry point ──────────────────────────────────────
    def run(self) -> None:
        try:
            import ebooklib
            from ebooklib import epub as ebooklib_epub
            import httpx
            from bs4 import BeautifulSoup
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
        first_only = cfg["first_only"]
        out_format = cfg["out_format"]
        out_folder = (
            Path(cfg["out_folder"]) if cfg.get("out_folder")
            else Path(epub_path).parent
        )
        creativity = cfg["creativity"]
        temperature = creativity_to_temperature(creativity)
        resume_from = cfg.get("resume_from", 0)
        meta = {
            "title": cfg.get("meta_title") or Path(epub_path).stem,
            "creator": cfg.get("meta_creator") or "",
            "language": cfg.get("meta_language") or "es",
            "contributor": cfg.get("meta_contributor") or "",
        }

        # ── load source EPUB ──────────────────────────────────
        self.log.emit(f"📖  Loading {Path(epub_path).name}…", "info")
        try:
            book = ebooklib_epub.read_epub(epub_path)
        except Exception as exc:
            self.log.emit(f"Failed to open EPUB: {exc}", "error")
            self.finished.emit(False, "")
            return

        chapters = []
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                soup = BeautifulSoup(item.get_content(), "html.parser")
                text = soup.get_text(separator="\n").strip()
                if len(text) > 200:  # skip tiny nav/cover pages
                    chapters.append((item.get_name(), text))

        if not chapters:
            self.log.emit("No readable chapters found in EPUB.", "error")
            self.finished.emit(False, "")
            return

        if first_only:
            chapters = chapters[:1]
            self.log.emit("ℹ️   Processing first chapter only.", "info")

        total_steps = len(chapters) * 2
        # Seed results and progress from any previously completed chapters.
        results: list[tuple[str, str]] = list(cfg.get("prior_results", []))
        step = resume_from * 2

        if resume_from > 0:
            self.log.emit(
                f"⏩  Resuming from chapter {resume_from + 1} "
                f"({resume_from} chapter(s) already done).",
                "info",
            )
        else:
            self.log.emit(f"✅  Found {len(chapters)} chapter(s) to process.", "success")

        for idx, (_name, text) in enumerate(chapters):
            # Skip chapters already completed in a prior run.
            if idx < resume_from:
                continue

            if self._abort:
                self.log.emit("⛔  Aborted by user.", "warning")
                self.completed_results = results
                self.failed_at_chapter = idx
                self.finished.emit(False, "")
                return

            chunks = self._split_into_chunks(text)
            n_chunks = len(chunks)
            if n_chunks > 1:
                self.log.emit(
                    f"\n── Chapter {idx + 1}/{len(chapters)}: "
                    f"split into {n_chunks} chunks (~2000 words each).", "info"
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

            step += 2
            self.progress.emit(step, total_steps)
            results.append((f"Capítulo {idx + 1}", "\n\n".join(spanish_parts)))
            self.completed_results = results[:]
            self.log.emit(f"✅  Chapter {idx + 1} done.", "success")

        # ── write output ──────────────────────────────────────
        out_folder.mkdir(parents=True, exist_ok=True)
        stem = Path(epub_path).stem

        if out_format == "txt":
            out_path = self._write_txt(results, out_folder, stem, level, meta)
        else:
            out_path = self._write_epub(
                results, out_folder, stem, level, meta, ebooklib_epub
            )

        self.finished.emit(True, str(out_path))

    # ── output writers ────────────────────────────────────────
    def _write_txt(
        self,
        results: list[tuple[str, str]],
        out_folder: Path,
        stem: str,
        level: str,
        meta: dict,
    ) -> Path:
        out_path = out_folder / f"{stem}_ES_{level}.txt"
        with open(out_path, "w", encoding="utf-8") as fh:
            if meta["title"]:
                fh.write(f"{meta['title']}\n")
            if meta["creator"]:
                fh.write(f"by {meta['creator']}\n")
            fh.write(f"Spanish ({level})\n{'─' * 60}\n\n")
            for title, body in results:
                fh.write(f"\n{'=' * 60}\n{title}\n{'=' * 60}\n\n{body}\n\n")
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
    ) -> Path:
        out_path = out_folder / f"{stem}_ES_{level}.epub"
        try:
            out_book = ebooklib_epub.EpubBook()
            out_book.set_title(meta["title"] or f"{stem} (Spanish {level})")
            out_book.set_language(meta["language"])
            if meta["creator"]:
                out_book.add_author(meta["creator"])
            if meta["contributor"]:
                out_book.add_metadata("DC", "contributor", meta["contributor"])
            out_book.add_metadata(
                "DC",
                "description",
                f"Spanish {level} rewrite generated by BookWeaver via Ollama.",
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
