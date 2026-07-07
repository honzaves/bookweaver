"""
app.py
------
BookWeaverApp — the main application window.

Responsibilities
----------------
- Build and lay out all UI sections.
- Read EPUB metadata on file selection and pre-fill output fields.
- Collect the processing config dict and hand it to ProcessingWorker.
- Show/hide EPUB metadata fields based on the selected output format.
- Relay worker signals to the log and progress bar.
"""

import importlib.util
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from settings import (
    C_AMBER,
    C_BORDER,
    C_MUTED,
    C_SURFACE,
    OLLAMA_TIMEOUT,
    SETTINGS,
    TARGET_LANG,
    voices_for_language,
)
from widgets import (
    ChapterListWidget,
    CreativitySlider,
    FilePickerRow,
    FolderPickerRow,
    LogWidget,
    ProgressBar,
    SummarizationSlider,
)
from worker import ProcessingWorker


class BookWeaverApp(QMainWindow):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("BookWeaver")
        self.setMinimumSize(700, 820)
        self.resize(760, 900)
        self._worker: ProcessingWorker | None = None
        self._resume_state: dict | None = None
        self._build_ui()

    # ──────────────────────────────────────────────────────────
    #  UI CONSTRUCTION
    # ──────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(28, 24, 28, 20)
        outer.setSpacing(0)

        self._add_header(outer)

        # thin amber rule below header
        rule = QFrame()
        rule.setFixedHeight(2)
        rule.setStyleSheet(f"background: {C_AMBER}; border: none;")
        outer.addWidget(rule)
        outer.addSpacing(20)

        # scrollable config area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll_widget = QWidget()
        form = QVBoxLayout(scroll_widget)
        form.setSpacing(16)
        form.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(scroll_widget)
        outer.addWidget(scroll, 1)

        self._add_source_group(form)
        self._add_chapters_group(form)
        self._add_model_group(form)
        self._add_summarisation_group(form)
        self._add_creativity_group(form)
        self._add_options_group(form)
        self._add_names_note(form)

        # progress bar, log, and action buttons sit outside the scroll area
        outer.addSpacing(14)
        self._progress = ProgressBar()
        outer.addWidget(self._progress)
        outer.addSpacing(6)

        self._log = LogWidget()
        self._log.setFixedHeight(200)
        self._log.append_line(
            "Ready.  Configure settings above and press Start.", "muted"
        )
        if SETTINGS.get("llm_backend") == "mlx" and importlib.util.find_spec("mlx_lm") is None:
            self._log.append_line(
                "⚠️  llm_backend is 'mlx' but mlx-lm is not installed — "
                'run: uv pip install "mlx-lm>=0.31" "mlx-vlm>=0.6.1", '
                "or set llm_backend to 'ollama' in bookweaver.json.",
                "warning",
            )
        outer.addWidget(self._log)
        outer.addSpacing(12)

        self._add_action_buttons(outer)

    def _add_header(self, layout: QVBoxLayout) -> None:
        header = QHBoxLayout()
        title = QLabel("BookWeaver")
        title.setObjectName("amber")
        title.setStyleSheet(
            f"font-size: 26px; font-weight: 800; "
            f"letter-spacing: -1px; color: {C_AMBER};"
        )
        sub = QLabel("  EPUB → Spanish rewriter via local LLM")
        sub.setStyleSheet(
            f"color: {C_MUTED}; font-size: 13px; margin-top: 6px;"
        )
        header.addWidget(title)
        header.addWidget(sub, 1, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(header)
        layout.addSpacing(4)

    def _add_source_group(self, form: QVBoxLayout) -> None:
        grp = QGroupBox("Source")
        gl = QVBoxLayout(grp)
        gl.addWidget(QLabel("EPUB file:"))
        self._file_picker = FilePickerRow("Select an .epub file…")
        self._file_picker.fileSelected.connect(self._on_epub_selected)
        gl.addWidget(self._file_picker)
        form.addWidget(grp)

    def _add_chapters_group(self, form: QVBoxLayout) -> None:
        grp = QGroupBox("Chapters")
        cl = QVBoxLayout(grp)
        cl.addWidget(QLabel("Select chapters to process:"))
        self._chapter_list = ChapterListWidget()
        cl.addWidget(self._chapter_list)
        self._chapters: list = []  # list[epub_io.Chapter]; filled on selection
        form.addWidget(grp)

    def _add_model_group(self, form: QVBoxLayout) -> None:
        grp = QGroupBox("Model & Target Language")
        ml = QHBoxLayout(grp)
        ml.setSpacing(20)

        # ── model combo ──
        col1 = QVBoxLayout()
        col1.addWidget(
            QLabel(f"Model ({SETTINGS.get('llm_backend', 'ollama')}):")
        )
        self._model_combo = QComboBox()
        default_val = SETTINGS.get("default_model", "gemma4:31b-mxfp8")
        default_idx = 0
        for i, entry in enumerate(SETTINGS.get("models", [])):
            self._model_combo.addItem(entry["label"], userData=entry["value"])
            if entry["value"] == default_val:
                default_idx = i
        self._model_combo.setCurrentIndex(default_idx)
        col1.addWidget(self._model_combo)
        ml.addLayout(col1, 1)

        # ── CEFR level combo ──
        col2 = QVBoxLayout()
        col2.addWidget(QLabel("Spanish CEFR level:"))
        self._level_combo = QComboBox()
        for code, desc in [
            ("B1", "B1 — Threshold"),
            ("B2", "B2 — Vantage"),
            ("C1", "C1 — Advanced"),
            ("C2", "C2 — Mastery"),
        ]:
            self._level_combo.addItem(desc, userData=code)
        self._level_combo.setCurrentIndex(1)  # B2 default
        col2.addWidget(self._level_combo)
        ml.addLayout(col2, 1)

        form.addWidget(grp)

    def _add_summarisation_group(self, form: QVBoxLayout) -> None:
        grp = QGroupBox("Processing mode")
        sl = QVBoxLayout(grp)

        # ── mode radio buttons ──
        mode_row = QHBoxLayout()
        self._mode_group = QButtonGroup(self)
        self._mode_summarise = QRadioButton("Summarise → Rewrite in Spanish")
        self._mode_translate = QRadioButton("Full translation (no summarisation)")
        self._mode_summarise_only = QRadioButton("Summarise only  (English, no translation)")
        self._mode_key_ideas = QRadioButton("Summary with key ideas")
        self._mode_summarise.setChecked(True)
        self._mode_group.addButton(self._mode_summarise)
        self._mode_group.addButton(self._mode_translate)
        self._mode_group.addButton(self._mode_summarise_only)
        self._mode_group.addButton(self._mode_key_ideas)
        mode_row.addWidget(self._mode_summarise)
        mode_row.addWidget(self._mode_translate)
        mode_row.addWidget(self._mode_summarise_only)
        mode_row.addWidget(self._mode_key_ideas)
        mode_row.addStretch()
        sl.addLayout(mode_row)

        sl.addSpacing(4)

        # ── summarisation depth (hidden in translate mode) ──
        self._summarisation_widget = QWidget()
        sw = QVBoxLayout(self._summarisation_widget)
        sw.setContentsMargins(0, 0, 0, 0)
        info = QLabel(
            "Controls how much of each chapter is condensed. "
            "Lower % = shorter, punchier output. "
            "Higher % = more faithful to source."
        )
        info.setObjectName("muted")
        info.setWordWrap(True)
        sw.addWidget(info)
        sw.addSpacing(6)
        self._slider = SummarizationSlider()
        sw.addWidget(self._slider)
        sl.addWidget(self._summarisation_widget)

        # translate mode note
        self._translate_note = QLabel(
            "The full chapter text will be translated directly — "
            "nothing is cut or condensed. Expect longer LLM calls."
        )
        self._translate_note.setObjectName("muted")
        self._translate_note.setWordWrap(True)
        self._translate_note.setVisible(False)
        sl.addWidget(self._translate_note)

        # summarise-only mode note
        self._summarise_only_note = QLabel(
            "Each chapter will be condensed to the target length and saved "
            "as English text — no translation is performed."
        )
        self._summarise_only_note.setObjectName("muted")
        self._summarise_only_note.setWordWrap(True)
        self._summarise_only_note.setVisible(False)
        sl.addWidget(self._summarise_only_note)

        # language toggle — only visible for the key-ideas mode
        self._keyideas_lang_widget = QWidget()
        kl = QHBoxLayout(self._keyideas_lang_widget)
        kl.setContentsMargins(0, 0, 0, 0)
        kl.addWidget(QLabel("Key-ideas output language:"))
        self._keyideas_lang_group = QButtonGroup(self)
        self._keyideas_lang_es = QRadioButton("Spanish (CEFR level)")
        self._keyideas_lang_en = QRadioButton("English")
        self._keyideas_lang_es.setChecked(True)
        self._keyideas_lang_group.addButton(self._keyideas_lang_es)
        self._keyideas_lang_group.addButton(self._keyideas_lang_en)
        kl.addWidget(self._keyideas_lang_es)
        kl.addWidget(self._keyideas_lang_en)
        kl.addStretch()
        self._keyideas_lang_widget.setVisible(False)
        sl.addWidget(self._keyideas_lang_widget)

        # wire toggles
        for btn in (
            self._mode_summarise,
            self._mode_translate,
            self._mode_summarise_only,
            self._mode_key_ideas,
        ):
            btn.toggled.connect(lambda _: self._on_mode_changed())
        for btn in (self._keyideas_lang_es, self._keyideas_lang_en):
            btn.toggled.connect(lambda _: self._on_mode_changed())

        form.addWidget(grp)

    def _add_creativity_group(self, form: QVBoxLayout) -> None:
        grp = QGroupBox("Creativity — how freely may the LLM elaborate?")
        cl = QVBoxLayout(grp)
        info = QLabel(
            "Controls how much the LLM may invent sensory details, imagery, "
            "and atmosphere beyond what is stated in the summary. "
            "Also sets the model temperature."
        )
        info.setObjectName("muted")
        info.setWordWrap(True)
        cl.addWidget(info)
        cl.addSpacing(6)
        self._creativity_slider = CreativitySlider()
        cl.addWidget(self._creativity_slider)
        form.addWidget(grp)

    def _add_options_group(self, form: QVBoxLayout) -> None:
        grp = QGroupBox("Options")
        ol = QVBoxLayout(grp)
        ol.setSpacing(10)

        ol.addWidget(self._make_separator())

        ol.addWidget(QLabel("Output format  (select one or more):"))
        fmt_row = QHBoxLayout()
        self._fmt_txt = QCheckBox("Plain text  (.txt)")
        self._fmt_epub = QCheckBox("EPUB  (.epub)")
        self._fmt_html = QCheckBox("HTML  (.html)")
        self._fmt_txt.setChecked(True)
        fmt_row.addWidget(self._fmt_txt)
        fmt_row.addWidget(self._fmt_epub)
        fmt_row.addWidget(self._fmt_html)
        fmt_row.addStretch()
        ol.addLayout(fmt_row)

        ol.addSpacing(4)
        # ── MP3 audiobook (Kokoro TTS, optional install) ──
        self._tts_available = importlib.util.find_spec("kokoro") is not None
        self._mp3_chk = QCheckBox("Generate MP3 audiobook  (Kokoro TTS)")
        ol.addWidget(self._mp3_chk)

        self._voice_row = QWidget()
        vr = QHBoxLayout(self._voice_row)
        vr.setContentsMargins(24, 0, 0, 0)
        vr.addWidget(QLabel("Voice:"))
        self._voice_combo = QComboBox()
        vr.addWidget(self._voice_combo)
        vr.addStretch()
        self._voice_row.setVisible(False)
        ol.addWidget(self._voice_row)

        self._mp3_chk.toggled.connect(self._voice_row.setVisible)
        self._fmt_txt.toggled.connect(
            lambda _: self._update_mp3_checkbox_state()
        )
        self._rebuild_voice_combo()
        self._update_mp3_checkbox_state()

        ol.addSpacing(4)
        ol.addWidget(QLabel("Output folder:"))
        self._out_folder = FolderPickerRow(
            "Same folder as source file (default)"
        )
        ol.addWidget(self._out_folder)

        ol.addWidget(self._build_epub_meta_widget())
        self._fmt_epub.toggled.connect(self._epub_meta_widget.setVisible)

        ol.addWidget(self._make_separator())

        timeout_row = QHBoxLayout()
        timeout_row.addWidget(QLabel("Timeout per call:"))
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(30, 3600)
        self._timeout_spin.setSingleStep(30)
        self._timeout_spin.setValue(OLLAMA_TIMEOUT)
        self._timeout_spin.setSuffix("  s")
        self._timeout_spin.setFixedWidth(110)
        timeout_row.addWidget(self._timeout_spin)
        timeout_row.addStretch()
        ol.addLayout(timeout_row)

        if SETTINGS.get("llm_backend") == "mlx":
            self._timeout_spin.setEnabled(False)
            self._timeout_spin.setToolTip(
                "Ignored by the mlx backend — output is capped by "
                "mlx_max_tokens in bookweaver.json."
            )

        chunk_row = QHBoxLayout()
        chunk_row.addWidget(QLabel("Chunk size:"))
        self._chunk_spin = QSpinBox()
        self._chunk_spin.setRange(200, 10000)
        self._chunk_spin.setSingleStep(100)
        self._chunk_spin.setValue(2000)
        self._chunk_spin.setSuffix("  words")
        self._chunk_spin.setFixedWidth(150)
        chunk_row.addWidget(self._chunk_spin)
        chunk_row.addStretch()
        ol.addLayout(chunk_row)

        carry_row = QHBoxLayout()
        carry_row.addWidget(QLabel("Cross-chunk continuity:"))
        self._carry_combo = QComboBox()
        for label, value in [
            ("Off", "off"),
            ("Names only (protect proper nouns)", "glossary"),
            ("Prose tail (scene-gated)", "prose"),
            ("Both", "both"),
        ]:
            self._carry_combo.addItem(label, userData=value)
        self._carry_combo.setCurrentIndex(0)
        self._carry_combo.setToolTip(
            "'Names' reinforces proper-noun consistency; 'Prose tail' "
            "carries the end of the previous chunk for smoother "
            "transitions, reset at scene breaks. Prose modes also split "
            "chapters at scene breaks (may increase LLM calls) and "
            "restore a '* * *' separator in the output."
        )
        carry_row.addWidget(self._carry_combo)
        carry_row.addStretch()
        ol.addLayout(carry_row)

        form.addWidget(grp)

    def _build_epub_meta_widget(self) -> QWidget:
        """Build the EPUB metadata sub-panel (hidden by default)."""
        self._epub_meta_widget = QWidget()
        em = QVBoxLayout(self._epub_meta_widget)
        em.setContentsMargins(0, 8, 0, 0)
        em.setSpacing(8)

        em.addWidget(self._make_separator())

        lbl = QLabel("EPUB Metadata")
        lbl.setStyleSheet(
            f"color: {C_MUTED}; font-size: 11px; "
            "font-weight: 600; letter-spacing: 1.2px;"
        )
        em.addWidget(lbl)

        self._meta_title = self._meta_row(em, "Title:", "Book title")
        self._meta_creator = self._meta_row(em, "Author:", "Original author")
        self._meta_language = self._meta_row(
            em, "Language:", "Language code", default="es"
        )
        self._meta_contributor = self._meta_row(
            em, "Contributor:", "Translator / editor"
        )

        self._epub_meta_widget.setVisible(False)
        return self._epub_meta_widget

    @staticmethod
    def _meta_row(
        layout: QVBoxLayout,
        label: str,
        placeholder: str = "",
        default: str = "",
    ) -> QLineEdit:
        """Add a labelled input row to *layout* and return the QLineEdit."""
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(90)
        lbl.setStyleSheet(f"color: {C_MUTED}; font-size: 12px;")
        edit = QLineEdit(default)
        edit.setPlaceholderText(placeholder)
        row.addWidget(lbl)
        row.addWidget(edit, 1)
        layout.addLayout(row)
        return edit

    def _add_names_note(self, form: QVBoxLayout) -> None:
        note = QLabel(
            "ℹ️  Character names and place names are never translated — "
            "they are passed through to the LLM exactly as written in the source."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color: {C_MUTED}; font-size: 11px; "
            f"background: {C_SURFACE}; border: 1px solid {C_BORDER}; "
            "border-radius: 6px; padding: 8px 10px;"
        )
        form.addWidget(note)

    def _add_action_buttons(self, layout: QVBoxLayout) -> None:
        btn_row = QHBoxLayout()

        self._clear_btn = QPushButton("Clear log")
        self._clear_btn.clicked.connect(self._log.clear)
        btn_row.addWidget(self._clear_btn)
        btn_row.addStretch()

        self._abort_btn = QPushButton("Abort")
        self._abort_btn.setObjectName("danger")
        self._abort_btn.setEnabled(False)
        self._abort_btn.clicked.connect(self._on_abort)
        btn_row.addWidget(self._abort_btn)

        self._resume_btn = QPushButton("⏩  Resume")
        self._resume_btn.setVisible(False)
        self._resume_btn.clicked.connect(self._on_resume)
        btn_row.addWidget(self._resume_btn)

        self._start_btn = QPushButton("▶  Start")
        self._start_btn.setObjectName("primary")
        self._start_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self._start_btn)

        layout.addLayout(btn_row)

    @staticmethod
    def _make_separator() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C_BORDER};")
        return sep

    # ──────────────────────────────────────────────────────────
    #  HELPERS
    # ──────────────────────────────────────────────────────────
    def _on_epub_selected(self, path: str) -> None:
        """Pre-fill metadata fields and default output folder."""
        try:
            from ebooklib import epub as ebooklib_epub
            book = ebooklib_epub.read_epub(path)
            title = book.get_metadata("DC", "title")
            author = book.get_metadata("DC", "creator")
            if title:
                self._meta_title.setText(title[0][0])
            if author:
                self._meta_creator.setText(author[0][0])
        except Exception as exc:
            self.statusBar().showMessage(
                f"Could not read EPUB metadata: {exc}", 5000
            )

        if not self._out_folder.path():
            self._out_folder.set_path(str(Path(path).parent))

        # Build the chapter selection list.
        try:
            import epub_io
            preview_chars = SETTINGS.get("chapter_title_preview_chars", 50)
            self._chapters = epub_io.extract_chapters(path, preview_chars)
            self._chapter_list.set_chapters(
                [(c.index, f"{c.index + 1:02d}. {c.title}") for c in self._chapters]
            )
        except Exception as exc:
            self._chapters = []
            self._chapter_list.clear()
            self.statusBar().showMessage(
                f"Could not read chapters: {exc}", 5000
            )

    def _build_config(self) -> dict | None:
        path = self._file_picker.path()
        if not path:
            self._log.append_line(
                "Please select an EPUB file first.", "warning"
            )
            return None
        out_fmt = [
            fmt for fmt, chk in [
                ("txt", self._fmt_txt),
                ("epub", self._fmt_epub),
                ("html", self._fmt_html),
            ] if chk.isChecked()
        ]
        if not out_fmt:
            self._log.append_line("Please select at least one output format.", "warning")
            return None
        selected = self._chapter_list.selected_indices()
        if not selected:
            self._log.append_line(
                "Please select at least one chapter to process.", "warning"
            )
            return None
        out_folder = self._out_folder.path() or str(Path(path).parent)
        mode = self._selected_mode()
        return {
            "epub_path": path,
            "level": self._level_combo.currentData(),
            "keep_pct": self._slider.value(),
            "model": self._model_combo.currentData(),
            "backend": SETTINGS.get("llm_backend", "ollama"),
            "out_format": out_fmt,
            "out_folder": out_folder,
            "selected_chapters": selected,
            "creativity": self._creativity_slider.value(),
            "mode": mode,
            "chunk_size": self._chunk_spin.value(),
            "carry_mode": self._carry_combo.currentData(),
            "meta_title": self._meta_title.text().strip(),
            "meta_creator": self._meta_creator.text().strip(),
            "meta_language": self._meta_language.text().strip() or "es",
            "meta_contributor": self._meta_contributor.text().strip(),
            "timeout": self._timeout_spin.value(),
            "generate_mp3": self._mp3_chk.isChecked(),
            "voice": (
                self._voice_combo.currentData()
                if self._mp3_chk.isChecked() else None
            ),
            "summary_lang": self._summary_target_lang(),
            "target_lang": (
                self._summary_target_lang()
                if mode == "summarise_key_ideas" else TARGET_LANG[mode]
            ),
        }

    def _summary_target_lang(self) -> str:
        """Effective output language for the key-ideas mode."""
        return "en" if self._keyideas_lang_en.isChecked() else "es"

    def _selected_mode(self) -> str:
        if self._mode_translate.isChecked():
            return "translate"
        if self._mode_summarise_only.isChecked():
            return "summarise_only"
        if self._mode_key_ideas.isChecked():
            return "summarise_key_ideas"
        return "summarise_rewrite"

    def _on_mode_changed(self) -> None:
        """Show/hide controls based on selected processing mode."""
        translate = self._mode_translate.isChecked()
        summarise_only = self._mode_summarise_only.isChecked()
        key_ideas = self._mode_key_ideas.isChecked()
        # Reduction depth applies to every mode except full translation.
        self._summarisation_widget.setVisible(not translate)
        self._translate_note.setVisible(translate)
        self._summarise_only_note.setVisible(summarise_only)
        self._keyideas_lang_widget.setVisible(key_ideas)
        # The voice combo is built in a later group than the mode radios.
        if hasattr(self, "_voice_combo"):
            self._rebuild_voice_combo()

    def _rebuild_voice_combo(self) -> None:
        """Repopulate the voice list for the current mode's target language,
        preserving the selection when the voice exists in both lists."""
        mode = self._selected_mode()
        lang = (
            self._summary_target_lang()
            if mode == "summarise_key_ideas" else TARGET_LANG[mode]
        )
        previous = self._voice_combo.currentData()
        default = SETTINGS.get("tts", {}).get(f"default_voice_{lang}")
        self._voice_combo.clear()
        for entry in voices_for_language(lang):
            self._voice_combo.addItem(entry["label"], userData=entry["value"])
        idx = self._voice_combo.findData(previous)
        if idx < 0:
            idx = self._voice_combo.findData(default)
        self._voice_combo.setCurrentIndex(max(idx, 0))

    def _update_mp3_checkbox_state(self) -> None:
        """Enable/disable the MP3 checkbox, with a tooltip naming the cause."""
        if not self._tts_available:
            self._mp3_chk.setChecked(False)
            self._mp3_chk.setEnabled(False)
            self._mp3_chk.setToolTip(
                "Install Kokoro to enable MP3 output — see kokoro.md."
            )
        elif not self._fmt_txt.isChecked():
            self._mp3_chk.setChecked(False)
            self._mp3_chk.setEnabled(False)
            self._mp3_chk.setToolTip(
                "Enable plain-text output to use MP3 audiobook generation."
            )
        else:
            self._mp3_chk.setEnabled(True)
            self._mp3_chk.setToolTip("")

    def _set_running(self, running: bool) -> None:
        self._start_btn.setEnabled(not running)
        self._abort_btn.setEnabled(running)
        if running:
            self._resume_btn.setVisible(False)

    # ──────────────────────────────────────────────────────────────────
    #  SLOTS
    # ──────────────────────────────────────────────────────────────────
    def _start_worker(self, cfg: dict) -> None:
        self._set_running(True)
        # A finishing worker may still be inside run()'s finally (mlx unload
        # releases a multi-GB model after `finished` is emitted). Rebinding
        # self._worker while its QThread is still executing would let Python
        # GC destroy a running QThread → qFatal. Wait for the prior run's
        # thread to actually return first.
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait()
        self._worker = ProcessingWorker(cfg)
        self._worker.log.connect(lambda msg, lvl: self._log.append_line(msg, lvl))
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_start(self) -> None:
        cfg = self._build_config()
        if cfg is None:
            return
        self._resume_state = None
        self._resume_btn.setVisible(False)
        self._log.clear()
        self._progress.reset()
        self._log.append_line(
            f"Starting: backend={cfg['backend']}  model={cfg['model']}  "
            f"level={cfg['level']}  "
            f"mode={cfg['mode']}  chunk={cfg['chunk_size']}w  "
            f"creativity={cfg['creativity']}/10  "
            f"format={cfg['out_format']}  → {cfg['out_folder']}",
            "info",
        )
        self._start_worker(cfg)

    def _on_resume(self) -> None:
        if not self._resume_state:
            return
        cfg = {
            **self._resume_state["config"],
            "timeout": self._timeout_spin.value(),
            "chunk_size": self._chunk_spin.value(),
            "resume_from": self._resume_state["from_chapter"],
            "prior_results": self._resume_state["results"],
        }
        self._log.append_line(
            f"\n⏩  Resuming from chapter {self._resume_state['from_chapter'] + 1} "
            f"with timeout={cfg['timeout']}s…",
            "info",
        )
        self._start_worker(cfg)

    def _on_abort(self) -> None:
        if self._worker:
            self._worker.abort()

    def _on_progress(self, current: int, total: int) -> None:
        self._progress.setMaximum(total)
        self._progress.setValue(current)

    def _on_finished(self, success: bool, path: str) -> None:
        self._set_running(False)
        if success:
            self._resume_state = None
            self._resume_btn.setVisible(False)
            self._progress.setMaximum(1)
            self._progress.setValue(1)
            self._log.append_line(f"\n🎉  All done!  Output: {path}", "success")
        else:
            self._log.append_line(
                "\n❌  Processing failed. See messages above.", "error"
            )
            # Offer resume if at least one chapter completed.
            if self._worker and self._worker.completed_results:
                self._resume_state = {
                    "config": self._worker.config,
                    "results": self._worker.completed_results,
                    "from_chapter": self._worker.failed_at_chapter,
                }
                n = len(self._worker.completed_results)
                self._log.append_line(
                    f"💾  {n} chapter(s) saved. Adjust the timeout and press "
                    f"Resume to continue from chapter "
                    f"{self._worker.failed_at_chapter + 1}.",
                    "warning",
                )
                self._resume_btn.setVisible(True)
