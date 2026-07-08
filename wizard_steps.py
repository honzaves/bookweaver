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

from PyQt6.QtCore import (
    QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, pyqtSignal,
)
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFileDialog, QGraphicsOpacityEffect,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton,
    QSpinBox, QVBoxLayout, QWidget,
)

import wizard_logic as wl
from settings import SETTINGS, OLLAMA_TIMEOUT, voices_for_language
from wizard_widgets import Card, ModeTileGrid, Note, RunConsole, TriStateChapterList, WizardSlider


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


_REVEAL_MS = 180


class _Reveal:
    """Animates a widget's maximumHeight + opacity. 'Don't pop.'

    Qt has no built-in collapse. We drive maximumHeight from 0 to the
    widget's sizeHint and back, pairing it with an opacity effect so the
    content fades rather than sliding out of a clipping rect.
    """

    def __init__(self, widget: QWidget) -> None:
        self._w = widget
        self._effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(self._effect)
        self._effect.setOpacity(1.0)
        self._group: QParallelAnimationGroup | None = None
        self._visible = True

    def set_visible(self, visible: bool, animate: bool = True) -> None:
        if visible == self._visible:
            return
        self._visible = visible
        target_h = self._w.sizeHint().height() if visible else 0
        if not animate:
            self._w.setVisible(visible)
            self._w.setMaximumHeight(target_h if visible else 0)
            self._effect.setOpacity(1.0 if visible else 0.0)
            return
        if visible:
            self._w.setVisible(True)

        group = QParallelAnimationGroup(self._w)
        h_anim = QPropertyAnimation(self._w, b"maximumHeight")
        h_anim.setDuration(_REVEAL_MS)
        h_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        h_anim.setStartValue(self._w.height())
        h_anim.setEndValue(target_h)
        group.addAnimation(h_anim)

        o_anim = QPropertyAnimation(self._effect, b"opacity")
        o_anim.setDuration(_REVEAL_MS)
        o_anim.setStartValue(self._effect.opacity())
        o_anim.setEndValue(1.0 if visible else 0.0)
        group.addAnimation(o_anim)

        if not visible:
            group.finished.connect(lambda: self._w.setVisible(False))
        else:
            # Release the cap so the card can grow with its content later.
            group.finished.connect(lambda: self._w.setMaximumHeight(16777215))
        self._group = group
        group.start()


_LEVELS = (
    ("B1 — Threshold", "B1"), ("B2 — Vantage", "B2"),
    ("C1 — Advanced", "C1"), ("C2 — Mastery", "C2"),
)
_CARRY = (
    ("Off — no continuity aid", "off"),
    ("Names only — protect proper nouns", "names"),
    ("Prose tail — scene-gated carry-over", "tail"),
    ("Both — names + prose tail", "both"),
)
_CARRY_NOTES = {
    "off": "No continuity aid — each chunk is processed independently.",
    "names": "Character and place names from each chunk's source are passed "
             "to the model so spellings stay consistent. No extra model calls.",
    "tail": "The last ~120 words of the previous chunk's output carry into "
            "the next prompt; the carry resets at scene breaks and chapter "
            "starts. Also hard-splits chapters at scene breaks, which can "
            "add model calls.",
    "both": "Both mechanisms together; highest continuity, may add model "
            "calls at scene breaks.",
}


class StepTransform(QWidget):
    """Step 2 — the mode tiles, the two sliders, and the mode-driven reveals."""

    changed = pyqtSignal()
    modeChanged = pyqtSignal(str)
    languageChanged = pyqtSignal()

    def __init__(self, caveat: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(13)
        layout.addWidget(_prompt("how should we transform it?", caveat))

        self._tiles = ModeTileGrid()
        self._tiles.modeChanged.connect(self._on_mode_changed)
        layout.addWidget(self._tiles)

        # ── the two sliders, side by side ──
        slider_row = QHBoxLayout()
        slider_row.setSpacing(13)
        self._depth_card = Card("Summarisation depth")
        self._keep = WizardSlider.keep_pct()
        self._keep.valueChanged.connect(lambda _v: self.changed.emit())
        self._depth_card.body.addWidget(self._keep)
        slider_row.addWidget(self._depth_card, 1)

        creativity_card = Card("Creativity")
        self._creativity = WizardSlider.creativity()
        self._creativity.valueChanged.connect(lambda _v: self.changed.emit())
        creativity_card.body.addWidget(self._creativity)
        slider_row.addWidget(creativity_card, 1)
        layout.addLayout(slider_row)

        # ── mode-conditional notes ──
        self._translate_note = Note(
            "⚠️  Full text is translated directly — expect longer model "
            "calls. Consider raising the timeout in step 3."
        )
        self._sum_note = Note(
            "ℹ️  Output stays in English; no translation is performed."
        )
        layout.addWidget(self._translate_note)
        layout.addWidget(self._sum_note)

        # ── key-ideas language ──
        self._key_card = Card("Key-ideas output language")
        key_row = QHBoxLayout()
        self._key_group = QButtonGroup(self)
        self._key_es = QRadioButton("Spanish (at your CEFR level)")
        self._key_en = QRadioButton("English")
        self._key_es.setChecked(True)
        for btn in (self._key_es, self._key_en):
            self._key_group.addButton(btn)
            key_row.addWidget(btn)
            btn.toggled.connect(self._on_key_lang_changed)
        self._key_card.body.addLayout(key_row)
        key_note = QLabel(
            "Changing this re-populates the MP3 voice list in step 3."
        )
        key_note.setObjectName("helper")
        self._key_card.body.addWidget(key_note)
        layout.addWidget(self._key_card)

        # ── Spanish level (gated on target_is_spanish) ──
        self._level_card = Card("Spanish level")
        self._level = QComboBox()
        for label, value in _LEVELS:
            self._level.addItem(label, userData=value)
        self._level.setCurrentIndex(1)                 # B2
        self._level.setMaximumWidth(280)
        self._level.currentIndexChanged.connect(lambda _i: self.changed.emit())
        self._level_card.body.addWidget(self._level)
        level_help = QLabel("Target CEFR level for the rewritten Spanish.")
        level_help.setObjectName("helper")
        self._level_card.body.addWidget(level_help)
        layout.addWidget(self._level_card)

        # ── continuity (never gated) ──
        carry_card = Card("Cross-chunk continuity")
        self._carry = QComboBox()
        for label, value in _CARRY:
            self._carry.addItem(label, userData=value)
        self._carry.setMaximumWidth(340)
        self._carry.currentIndexChanged.connect(self._on_carry_changed)
        carry_card.body.addWidget(self._carry)
        self._carry_note = QLabel(_CARRY_NOTES["off"])
        self._carry_note.setObjectName("helper")
        self._carry_note.setWordWrap(True)
        carry_card.body.addWidget(self._carry_note)
        layout.addWidget(carry_card)
        layout.addStretch()

        self._reveals = {
            "depth": _Reveal(self._depth_card),
            "translate": _Reveal(self._translate_note),
            "sum": _Reveal(self._sum_note),
            "key": _Reveal(self._key_card),
            "level": _Reveal(self._level_card),
        }
        self._sync_reveals(animate=False)

    # ── public API ──
    def apply_to(self, state: wl.WizardState) -> None:
        state.mode = self._tiles.mode()
        state.key_ideas_lang = "en" if self._key_en.isChecked() else "es"
        state.cefr_level = self._level.currentData()
        state.carry = self._carry.currentData()
        state.keep_pct = self._keep.value()
        state.creativity = self._creativity.value()

    def load_from(self, state: wl.WizardState) -> None:
        self._tiles.set_mode(state.mode)
        self._keep.set_value(state.keep_pct)
        self._creativity.set_value(state.creativity)

    def set_enabled_controls(self, enabled: bool) -> None:
        for w in (self._tiles, self._keep, self._creativity,
                  self._level, self._carry, self._key_es, self._key_en):
            w.setEnabled(enabled)

    # ── internals ──
    def _on_mode_changed(self, mode: str) -> None:
        self._sync_reveals()
        self.modeChanged.emit(mode)
        self.languageChanged.emit()      # mode can flip target_is_spanish
        self.changed.emit()

    def _on_key_lang_changed(self, checked: bool) -> None:
        if not checked:
            return                        # ignore the untoggled partner
        self._sync_reveals()
        self.languageChanged.emit()
        self.changed.emit()

    def _on_carry_changed(self, _i: int) -> None:
        self._carry_note.setText(_CARRY_NOTES[self._carry.currentData()])
        self.changed.emit()

    def _sync_reveals(self, animate: bool = True) -> None:
        mode = self._tiles.mode()
        key_lang = "en" if self._key_en.isChecked() else "es"
        self._reveals["depth"].set_visible(mode != "full", animate)
        self._reveals["translate"].set_visible(mode == "full", animate)
        self._reveals["sum"].set_visible(mode == "sum", animate)
        self._reveals["key"].set_visible(mode == "key", animate)
        self._reveals["level"].set_visible(
            wl.derive_target_is_spanish(mode, key_lang), animate
        )


_KOKORO_AVAILABLE = importlib.util.find_spec("kokoro") is not None


class StepOutput(QWidget):
    """Step 3 — formats, audio, destination, metadata, advanced."""

    changed = pyqtSignal()

    def __init__(self, caveat: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._backend = SETTINGS.get("llm_backend", "ollama")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(13)
        layout.addWidget(_prompt("where should it land?", caveat))

        # ── formats ──
        fmt_card = Card("Output formats", "at least one")
        fmt_row = QHBoxLayout()
        self._fmt = {
            "txt": QCheckBox("Plain text (.txt)"),
            "epub": QCheckBox("EPUB (.epub)"),
            "html": QCheckBox("HTML (.html)"),
        }
        self._fmt["txt"].setChecked(True)
        for box in self._fmt.values():
            box.stateChanged.connect(self._on_formats_changed)
            fmt_row.addWidget(box)
        fmt_row.addStretch()
        fmt_card.body.addLayout(fmt_row)

        self._mp3 = QCheckBox("Generate MP3 audiobook (Kokoro TTS)")
        self._mp3.stateChanged.connect(self._on_mp3_toggled)
        fmt_card.body.addWidget(self._mp3)
        self._mp3_note = QLabel("")
        self._mp3_note.setObjectName("helper")
        fmt_card.body.addWidget(self._mp3_note)

        self._voice_wrap = QWidget()
        voice_box = QHBoxLayout(self._voice_wrap)
        voice_box.setContentsMargins(26, 0, 0, 0)
        voice_box.addWidget(QLabel("Voice:"))
        self._voice = QComboBox()
        self._voice.currentIndexChanged.connect(lambda _i: self.changed.emit())
        voice_box.addWidget(self._voice, 1)
        fmt_card.body.addWidget(self._voice_wrap)
        layout.addWidget(fmt_card)

        # ── output folder ──
        folder_card = Card("Output folder")
        folder_row = QHBoxLayout()
        self._folder = QLineEdit()
        self._folder.textChanged.connect(lambda _t: self.changed.emit())
        folder_row.addWidget(self._folder, 1)
        pick = QPushButton("Browse…")
        pick.clicked.connect(self._browse_folder)
        folder_row.addWidget(pick)
        folder_card.body.addLayout(folder_row)
        layout.addWidget(folder_card)

        # ── EPUB metadata (gated on .epub) ──
        self._meta_card = Card("EPUB metadata")
        grid = QGridLayout()
        grid.setSpacing(9)
        self._meta_title = QLineEdit()
        self._meta_creator = QLineEdit()
        self._meta_language = QLineEdit("es")
        self._meta_contributor = QLineEdit()
        for col, (label, widget) in enumerate([
            ("Title", self._meta_title), ("Author", self._meta_creator),
        ]):
            grid.addWidget(QLabel(label), 0, col * 2)
            grid.addWidget(widget, 0, col * 2 + 1)
        for col, (label, widget) in enumerate([
            ("Language", self._meta_language),
            ("Contributor", self._meta_contributor),
        ]):
            grid.addWidget(QLabel(label), 1, col * 2)
            grid.addWidget(widget, 1, col * 2 + 1)
        for widget in (self._meta_title, self._meta_creator,
                       self._meta_language, self._meta_contributor):
            widget.textChanged.connect(lambda _t: self.changed.emit())
        self._meta_card.body.addLayout(grid)
        layout.addWidget(self._meta_card)

        # ── advanced: backend-aware stepper + chunk size ──
        adv_row = QHBoxLayout()
        adv_row.setSpacing(13)
        self._timeout: QSpinBox | None = None
        self._tokens: QSpinBox | None = None

        if self._backend == "mlx":
            tok_card = Card("Max tokens per call")
            self._tokens = QSpinBox()
            self._tokens.setRange(256, 65536)
            self._tokens.setSingleStep(256)
            self._tokens.setValue(SETTINGS.get("mlx_max_tokens", 8192))
            self._tokens.setSuffix("  tokens")
            self._tokens.valueChanged.connect(lambda _v: self.changed.emit())
            tok_card.body.addWidget(self._tokens)
            hint = QLabel("caps runaway output — mlx cannot abort mid-call")
            hint.setObjectName("helper")
            tok_card.body.addWidget(hint)
            adv_row.addWidget(tok_card, 1)
        else:
            to_card = Card("Timeout per call")
            self._timeout = QSpinBox()
            self._timeout.setRange(30, 3600)
            self._timeout.setSingleStep(30)
            self._timeout.setValue(OLLAMA_TIMEOUT)
            self._timeout.setSuffix("  s")
            self._timeout.valueChanged.connect(lambda _v: self.changed.emit())
            to_card.body.addWidget(self._timeout)
            hint = QLabel("raise for Full translation")
            hint.setObjectName("helper")
            to_card.body.addWidget(hint)
            adv_row.addWidget(to_card, 1)

        chunk_card = Card("Chunk size")
        self._chunk = QSpinBox()
        self._chunk.setRange(200, 10000)
        self._chunk.setSingleStep(100)
        self._chunk.setValue(2000)
        self._chunk.setSuffix("  words")
        self._chunk.valueChanged.connect(lambda _v: self.changed.emit())
        chunk_card.body.addWidget(self._chunk)
        chunk_hint = QLabel("long chapters split & rejoin")
        chunk_hint.setObjectName("helper")
        chunk_card.body.addWidget(chunk_hint)
        adv_row.addWidget(chunk_card, 1)
        layout.addLayout(adv_row)

        layout.addWidget(Note(
            "ℹ️  Character names and place names are never translated — "
            "passed through to the model exactly as written."
        ))
        layout.addStretch()

        self._meta_reveal = _Reveal(self._meta_card)
        self._voice_reveal = _Reveal(self._voice_wrap)
        self.repopulate_voices(True)
        self._on_formats_changed()
        self._meta_reveal.set_visible(False, animate=False)
        self._voice_reveal.set_visible(False, animate=False)

    # ── public API ──
    def timeout_value(self) -> int:
        return self._timeout.value() if self._timeout else OLLAMA_TIMEOUT

    def max_tokens_value(self) -> int:
        if self._tokens:
            return self._tokens.value()
        return SETTINGS.get("mlx_max_tokens", 8192)

    def prefill(self, folder: str, title: str, author: str) -> None:
        if not self._folder.text():
            self._folder.setText(folder)
        if title and not self._meta_title.text():
            self._meta_title.setText(title)
        if author and not self._meta_creator.text():
            self._meta_creator.setText(author)

    def repopulate_voices(self, target_is_spanish: bool) -> None:
        """Rebuild the voice list, preserving the selection when possible."""
        previous = self._voice.currentData()
        lang = "es" if target_is_spanish else "en"
        self._voice.blockSignals(True)
        self._voice.clear()
        for entry in voices_for_language(lang):
            self._voice.addItem(entry["label"], userData=entry["value"])
        idx = self._voice.findData(previous)
        self._voice.setCurrentIndex(idx if idx >= 0 else 0)
        self._voice.blockSignals(False)

    def apply_to(self, state: wl.WizardState) -> None:
        state.formats = {k: b.isChecked() for k, b in self._fmt.items()}
        state.mp3_enabled = self._mp3.isChecked() and self._mp3.isEnabled()
        state.voice = self._voice.currentData() if state.mp3_enabled else None
        state.out_folder = self._folder.text().strip()
        state.meta_title = self._meta_title.text()
        state.meta_creator = self._meta_creator.text()
        state.meta_language = self._meta_language.text()
        state.meta_contributor = self._meta_contributor.text()
        state.chunk_words = self._chunk.value()
        state.timeout_sec = self.timeout_value()
        state.max_tokens = self.max_tokens_value()

    def load_from(self, state: wl.WizardState) -> None:
        self._folder.setText(state.out_folder)

    def set_enabled_controls(self, enabled: bool) -> None:
        for box in self._fmt.values():
            box.setEnabled(enabled)
        for w in (self._mp3, self._voice, self._folder, self._chunk,
                  self._meta_title, self._meta_creator,
                  self._meta_language, self._meta_contributor):
            w.setEnabled(enabled)
        if self._timeout:
            self._timeout.setEnabled(enabled)
        if self._tokens:
            self._tokens.setEnabled(enabled)
        if enabled:
            self._sync_mp3_gate()

    # ── internals ──
    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select output folder", self._folder.text() or str(Path.home())
        )
        if folder:
            self._folder.setText(folder)

    def _on_formats_changed(self) -> None:
        self._sync_mp3_gate()
        self._meta_reveal.set_visible(self._fmt["epub"].isChecked())
        self.changed.emit()

    def _sync_mp3_gate(self) -> None:
        """MP3 needs Kokoro installed AND .txt selected (worker.py:472)."""
        txt = self._fmt["txt"].isChecked()
        enabled = _KOKORO_AVAILABLE and txt
        self._mp3.setEnabled(enabled)
        if not enabled:
            self._mp3.setChecked(False)
        if not _KOKORO_AVAILABLE:
            self._mp3_note.setText("Kokoro is not installed — see kokoro.md.")
        elif not txt:
            self._mp3_note.setText("Requires Plain text (.txt) to be selected.")
        else:
            self._mp3_note.setText("")
        self._voice_reveal.set_visible(self._mp3.isChecked() and enabled)

    def _on_mp3_toggled(self, _state: int) -> None:
        self._voice_reveal.set_visible(
            self._mp3.isChecked() and self._mp3.isEnabled()
        )
        self.changed.emit()


class StepRun(QWidget):
    """Step 4 — the run console. The expanded 'drawer takes over' view."""

    def __init__(self, caveat: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(13)
        self.console = RunConsole()
        layout.addWidget(self.console, 1)

    def apply_to(self, state: wl.WizardState) -> None:
        """Step 4 holds no configuration."""

    def load_from(self, state: wl.WizardState) -> None:
        """Step 4 holds no configuration."""

    def set_enabled_controls(self, enabled: bool) -> None:
        """The console is always interactive (scroll/select)."""
