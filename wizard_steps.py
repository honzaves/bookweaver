"""
wizard_steps.py
---------------
One QWidget per wizard step. Each step owns its controls, writes into the
shared WizardState via apply_to(), and re-reads it via load_from().

Imports wizard_widgets, wizard_theme, wizard_logic and settings. Never
imports app.py or widgets.py (the old UI). epub_io is imported lazily.
"""

import importlib.util
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)

import wizard_logic as wl
from settings import SETTINGS
from wizard_widgets import Card, TriStateChapterList


def _prompt(text: str, caveat_family: str | None) -> QLabel:
    """The decorative hand-lettered per-step prompt.

    Falls back to muted italic system text when Caveat is unavailable — the
    prompt is cosmetic and must never be a startup dependency.
    """
    lbl = QLabel(text)
    lbl.setObjectName("stepPrompt")
    if caveat_family:
        font = lbl.font()
        font.setFamily(caveat_family)
        font.setPointSize(16)
        lbl.setFont(font)
    else:
        font = lbl.font()
        font.setItalic(True)
        lbl.setFont(font)
    return lbl


class StepBook(QWidget):
    """Step 1 — identify the book and choose what to process."""

    changed = pyqtSignal()

    def __init__(self, caveat: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._chapters: list[wl.ChapterRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(13)
        layout.addWidget(_prompt("which book are we weaving?", caveat))

        # ── EPUB file ──
        file_card = Card("EPUB file")
        row = QHBoxLayout()
        row.setSpacing(8)
        self._path = QLineEdit()
        self._path.setReadOnly(True)
        self._path.setPlaceholderText("No file selected")
        row.addWidget(self._path, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        file_card.body.addLayout(row)
        helper = QLabel(
            "Selecting a file reads title, author & chapters, "
            "and pre-fills the output folder."
        )
        helper.setObjectName("helper")
        file_card.body.addWidget(helper)
        layout.addWidget(file_card)

        # ── Chapters ──
        self._chapters_card = Card("Chapters", "0 / 0 selected")
        self._list = TriStateChapterList()
        self._list.selectionChanged.connect(self._on_selection_changed)
        self._chapters_card.body.addWidget(self._list)
        layout.addWidget(self._chapters_card)

        # ── Model ──
        backend = SETTINGS.get("llm_backend", "ollama")
        model_card = Card(f"Model ({backend})")
        self._model = QComboBox()
        for entry in SETTINGS["models"]:
            self._model.addItem(entry["label"], userData=entry["value"])
        default = SETTINGS["default_model"]
        idx = self._model.findData(default)
        if idx >= 0:
            self._model.setCurrentIndex(idx)
        self._model.currentIndexChanged.connect(lambda _i: self.changed.emit())
        model_card.body.addWidget(self._model)
        layout.addWidget(model_card)
        layout.addStretch()

    # ── public API ──
    def model_label(self) -> str:
        return self._model.currentText()

    def apply_to(self, state: wl.WizardState) -> None:
        state.epub_path = self._path.text()
        state.chapters = self._list.rows()
        state.model = self._model.currentData()

    def load_from(self, state: wl.WizardState) -> None:
        self._path.setText(state.epub_path)
        if state.chapters:
            self._list.set_chapters(state.chapters)
        self._refresh_meta()

    def set_enabled_controls(self, enabled: bool) -> None:
        for w in (self._path, self._list, self._model):
            w.setEnabled(enabled)

    # ── internals ──
    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select an EPUB", str(Path.home()), "EPUB files (*.epub)"
        )
        if path:
            self._load_epub(path)

    def _load_epub(self, path: str) -> None:
        self._path.setText(path)
        # Lazy, exactly as app.py:_on_epub_selected does.
        try:
            import epub_io
            preview = SETTINGS.get("chapter_title_preview_chars", 50)
            chapters = epub_io.extract_chapters(path, preview)
            self._chapters = [
                wl.ChapterRow(c.index, c.title, True) for c in chapters
            ]
            self._list.set_chapters(self._chapters)
        except Exception:
            self._chapters = []
            self._list.clear()
        self._refresh_meta()
        self.changed.emit()

    def read_book_metadata(self, path: str) -> tuple[str, str]:
        """(title, author) from the EPUB's DC metadata; ('', '') on failure."""
        try:
            from ebooklib import epub as ebooklib_epub
            book = ebooklib_epub.read_epub(path)
            title = book.get_metadata("DC", "title")
            author = book.get_metadata("DC", "creator")
            return (title[0][0] if title else "",
                    author[0][0] if author else "")
        except Exception:
            return "", ""

    def _on_selection_changed(self) -> None:
        self._refresh_meta()
        self.changed.emit()

    def _refresh_meta(self) -> None:
        rows = self._list.rows()
        total = len(rows)
        selected = sum(1 for r in rows if r.checked)
        self._chapters_card.set_meta(f"{selected} / {total} selected")
