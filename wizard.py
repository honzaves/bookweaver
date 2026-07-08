#!/usr/bin/env python3
"""
wizard.py
---------
Entry point for the BookWeaver Guided Wizard frontend.

    python wizard.py

Runs alongside the classic UI (`python main.py`), which is untouched. Both
drive the same ProcessingWorker.

Must not import tts (torch) or llm (mlx) at startup — availability is probed
with importlib.util.find_spec, exactly as app.py does.
"""

import sys

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

import wizard_logic as wl
from settings import SETTINGS
from wizard_steps import StepBook, StepOutput, StepRun, StepTransform
from wizard_theme import (
    WIZARD_STYLESHEET, W_AMBER, W_APP_BG, W_SURFACE, W_TEXT, W_WINDOW_BG,
    load_caveat,
)
from wizard_widgets import StepRail

_STEP_NEXT_LABEL = {1: "Next → Transform", 2: "Next → Output", 3: "Next → Run"}


class WizardWindow(QMainWindow):
    """The four-step shell: header, rail, recap, content stack, pinned footer."""

    def __init__(self, caveat: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("BookWeaver")
        self.resize(860, 724)
        self.setMinimumSize(760, 640)

        self.state = wl.WizardState()
        self.state.model = SETTINGS["default_model"]
        self._backend = SETTINGS.get("llm_backend", "ollama")
        self._worker = None
        self._resume_state: dict | None = None
        self._loaded_epub_path: str | None = None

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_rail())

        self._recap = QLabel("")
        self._recap.setObjectName("recapLine")
        self._recap.setContentsMargins(26, 3, 26, 0)
        outer.addWidget(self._recap)

        outer.addWidget(self._build_content(caveat), 1)
        outer.addWidget(self._build_footer())

        self._go_to(1)

    # ── construction ──
    def _build_header(self) -> QWidget:
        wrap = QWidget()
        box = QVBoxLayout(wrap)
        box.setContentsMargins(26, 17, 26, 0)
        box.setSpacing(2)
        title = QLabel("BookWeaver")
        title.setObjectName("appTitle")
        box.addWidget(title)
        sub = QLabel("EPUB → Spanish rewriter via local LLM")
        sub.setObjectName("appSubtitle")
        box.addWidget(sub)
        rule = QFrame()
        rule.setObjectName("amberRule")
        rule.setFixedHeight(2)
        box.addSpacing(13)
        box.addWidget(rule)
        return wrap

    def _build_rail(self) -> QWidget:
        wrap = QWidget()
        box = QVBoxLayout(wrap)
        box.setContentsMargins(26, 16, 26, 4)
        self._rail = StepRail()
        self._rail.stepClicked.connect(self._go_to)
        box.addWidget(self._rail)
        return wrap

    def _build_content(self, caveat: str | None) -> QWidget:
        self._steps = {
            1: StepBook(caveat),
            2: StepTransform(caveat),
            3: StepOutput(caveat),
            4: StepRun(caveat),
        }
        self._steps[1].changed.connect(self._on_step1_changed)
        self._steps[2].changed.connect(self._sync)
        self._steps[2].languageChanged.connect(self._on_language_changed)
        self._steps[3].changed.connect(self._sync)

        self._stack = QStackedWidget()
        for i in (1, 2, 3, 4):
            self._stack.addWidget(self._steps[i])

        scroll = QScrollArea()
        scroll.setObjectName("contentArea")
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._stack)
        scroll.setContentsMargins(26, 18, 26, 22)
        return scroll

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        footer.setObjectName("footer")
        row = QHBoxLayout(footer)
        row.setContentsMargins(26, 13, 26, 13)
        row.setSpacing(14)

        self._back = QPushButton("← Back")
        self._back.setObjectName("ghostBtn")
        self._back.clicked.connect(lambda: self._go_to(self.state.step - 1))
        row.addWidget(self._back)

        self._clear = QPushButton("Clear log")
        self._clear.setObjectName("ghostBtn")
        self._clear.clicked.connect(self._steps[4].console.clear_log)
        row.addWidget(self._clear)

        self._drawer = QLabel("▸ run drawer · idle — expands & takes over on Start")
        self._drawer.setObjectName("helper")
        row.addWidget(self._drawer)
        row.addStretch()

        self._abort = QPushButton("Abort")
        self._abort.setObjectName("dangerBtn")
        self._abort.setEnabled(False)
        self._abort.clicked.connect(self._on_abort)
        row.addWidget(self._abort)

        self._resume = QPushButton("⏩ Resume")
        self._resume.clicked.connect(self._on_resume)
        self._resume.setVisible(False)
        row.addWidget(self._resume)

        self._next = QPushButton("Next →")
        self._next.clicked.connect(lambda: self._go_to(self.state.step + 1))
        row.addWidget(self._next)

        self._start = QPushButton("▶ Start")
        self._start.setObjectName("primaryBtn")
        self._start.clicked.connect(self._on_start)
        row.addWidget(self._start)
        return footer

    # ── navigation & sync ──
    def _go_to(self, step: int) -> None:
        step = max(1, min(4, step))
        self._collect()
        self.state.step = step
        self._stack.setCurrentWidget(self._steps[step])
        self._steps[step].load_from(self.state)
        self._sync()

    def _collect(self) -> None:
        for widget in self._steps.values():
            widget.apply_to(self.state)

    def _on_step1_changed(self) -> None:
        self._collect()
        if self.state.epub_path:
            if self.state.epub_path != self._loaded_epub_path:
                # A genuinely new/different EPUB was loaded — reset the
                # prefill-derived fields so this book's values win. A
                # same-path re-emission (checkbox toggle, model change)
                # must not clobber any edits the user made in step 3.
                self._loaded_epub_path = self.state.epub_path
                self._steps[3].clear_prefill()
            title, author = self._steps[1].cached_metadata()
            from pathlib import Path
            self._steps[3].prefill(str(Path(self.state.epub_path).parent),
                                   title, author)
        self._sync()

    def _on_language_changed(self) -> None:
        self._collect()
        self._steps[3].repopulate_voices(
            wl.derive_target_is_spanish(self.state.mode, self.state.key_ideas_lang)
        )
        self._sync()

    def _sync(self) -> None:
        """Recompute every derived surface from state. One source of truth."""
        self._collect()
        step = self.state.step
        errors = wl.validation_errors(self.state)
        error_steps = {s for s, _ in errors}
        completed = {i for i in range(1, step) if i not in error_steps}
        self._rail.set_state(step, completed, error_steps)

        if step >= 2 and self.state.epub_path:
            self._recap.setText(
                wl.recap_text(self.state, self._steps[1].model_label()) + "  ·  edit"
            )
            self._recap.setVisible(True)
        else:
            self._recap.setVisible(False)

        running = self.state.run_state in ("running", "aborting")
        self._back.setVisible(step > 1 and not running)
        self._next.setVisible(step < 4 and not running)
        self._next.setText(_STEP_NEXT_LABEL.get(step, "Next →"))
        self._clear.setVisible(step == 4)
        self._drawer.setVisible(step < 4 and not running)

        self._start.setEnabled(not errors and not running)
        self._start.setToolTip(" · ".join(msg for _, msg in errors))
        if running:
            self._start.setText("● Running…")
        elif self.state.run_state in ("success", "failed", "aborted"):
            self._start.setText("▶ Start over")
        else:
            self._start.setText("▶ Start")

        self._abort.setEnabled(self.state.run_state == "running")
        if self.state.run_state == "aborting":
            self._abort.setText("Stopping…")
        else:
            self._abort.setText("Abort")
        self._resume.setVisible(self._resume_state is not None and not running)

    # ── worker lifecycle ──
    def _start_worker(self, cfg: dict) -> None:
        from worker import ProcessingWorker      # lazy: never at import time
        console = self._steps[4].console
        self._worker = ProcessingWorker(cfg)
        self._worker.log.connect(console.append)
        self._worker.progress.connect(console.set_progress)
        self._worker.finished.connect(self._on_finished)
        self.state.run_state = "running"
        self._go_to(4)
        self._set_controls_enabled(False)
        self._worker.start()

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in self._steps.values():
            widget.set_enabled_controls(enabled)

    def _on_start(self) -> None:
        self._collect()
        if wl.validation_errors(self.state):
            return                       # Start is disabled; belt and braces
        self._resume_state = None
        self._steps[4].console.reset()
        # Capture the backend once, so a resume can never flip it mid-book.
        cfg = wl.build_config(self.state, self._backend)
        self._steps[4].console.append(
            f"📖  Starting: {len(cfg['selected_chapters'])} chapter(s), "
            f"mode={cfg['mode']}, backend={cfg['backend']}",
            "muted",
        )
        self._start_worker(cfg)

    def _on_abort(self) -> None:
        if not self._worker:
            return
        self._worker.abort()
        self.state.run_state = "aborting"
        # _abort is polled at chunk boundaries (worker.py:187,219,289,335),
        # never mid-generation. On mlx an in-flight call cannot be
        # interrupted, so be honest about the latency.
        self._steps[4].console.append(
            "·  Abort requested — will stop after the current chunk.", "muted"
        )
        self._sync()

    def _on_resume(self) -> None:
        if not self._resume_state:
            return
        cfg = {
            **self._resume_state["config"],
            "timeout": self._steps[3].timeout_value(),
            "max_tokens": self._steps[3].max_tokens_value(),
            "chunk_size": self.state.chunk_words,
            "resume_from": self._resume_state["from_chapter"],
            "prior_results": self._resume_state["results"],
        }
        self._steps[4].console.append(
            f"⏩  Resuming from chapter {self._resume_state['from_chapter'] + 1}…",
            "info",
        )
        self._resume_state = None
        self._start_worker(cfg)

    def _on_finished(self, success: bool, path: str) -> None:
        console = self._steps[4].console
        worker, self._worker = self._worker, None
        aborting = self.state.run_state == "aborting"

        if success:
            self.state.run_state = "success"
            self._resume_state = None
            console.append(f"\n🎉  All done!  Output: {path}", "success")
        else:
            self.state.run_state = "aborted" if aborting else "failed"
            if not aborting:
                console.append("\n✗  Run failed.", "error")
            partial = list(getattr(worker, "completed_results", []) or [])
            if partial:
                # Aborted runs are resumable too: completed_results is
                # populated identically on every early exit.
                self._resume_state = {
                    "config": worker.config,
                    "from_chapter": worker.failed_at_chapter,
                    "results": partial,
                }
                console.append(
                    f"💾  {len(partial)} chapter(s) saved. "
                    f"{wl.resume_hint(self._backend)}",
                    "warning",
                )

        self._set_controls_enabled(True)
        self._sync()


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(WIZARD_STYLESHEET)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(W_WINDOW_BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(W_TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(W_APP_BG))
    palette.setColor(QPalette.ColorRole.Text, QColor(W_TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(W_SURFACE))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(W_TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(W_AMBER))
    app.setPalette(palette)

    # load_caveat() MUST come after QApplication(): Qt's font database
    # reaches the platform integration and segfaults without a live app.
    win = WizardWindow(caveat=load_caveat())
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
