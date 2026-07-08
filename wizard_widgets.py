"""
wizard_widgets.py
-----------------
Custom-painted, reusable widgets for the Guided Wizard frontend.

Imports wizard_theme (for W_* colours) and wizard_logic (for ramp keys and
readout text) only. Never settings, never app, never worker.

widgets.py is the OLD UI's widget module and is not touched, imported, or
subclassed here.
"""

import html
from dataclasses import replace

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QRadioButton,
    QScrollArea, QSizePolicy, QSlider, QTextEdit, QVBoxLayout, QWidget,
)

import wizard_logic as wl
from wizard_theme import (
    LOG_COLORS, RAMP, W_AMBER, W_AMBER_DIM, W_BADGE_DONE_BG, W_BORDER,
    W_BORDER_CTRL, W_ERROR, W_FAINT2, W_FILL_START, W_INSET, W_KNOB_RING,
    W_MUTED, W_ROW_HOVER, W_SURFACE, W_TEXT_SECONDARY, W_TILE_SELECTED,
    W_TRACK,
)


class Card(QFrame):
    """The repeated group container: uppercase title row + a body layout."""

    def __init__(self, title: str, meta: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 13, 14, 13)
        outer.setSpacing(11)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        title_lbl = QLabel(title.upper())
        title_lbl.setObjectName("cardTitle")
        head.addWidget(title_lbl)
        head.addStretch()
        self._meta = QLabel(meta)
        self._meta.setObjectName("cardMeta")
        head.addWidget(self._meta)
        outer.addLayout(head)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(9)
        outer.addLayout(self.body)

    def set_meta(self, text: str) -> None:
        self._meta.setText(text)


class Note(QFrame):
    """A bordered info frame: one word-wrapped helper line, no title row.

    Distinct from Card because a Card always carries an uppercase title
    label; an empty one would leave a phantom row in every note.
    """

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("note")
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 10, 12, 10)
        label = QLabel(text)
        label.setObjectName("helper")
        label.setWordWrap(True)
        box.addWidget(label)


class _ProgressPill(QWidget):
    """8px pill with rounded caps; fill is an amber-dim → amber gradient."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(8)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._fraction = 0.0

    def set_fraction(self, f: float) -> None:
        self._fraction = max(0.0, min(1.0, f))
        self.update()

    def paintEvent(self, _event) -> None:      # noqa: N802 (Qt naming)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        r = self.rect()
        p.setBrush(QColor(W_TRACK))
        p.drawRoundedRect(r, 4, 4)
        if self._fraction <= 0:
            return
        fill = r.adjusted(0, 0, -int(r.width() * (1 - self._fraction)), 0)
        grad = QLinearGradient(fill.left(), 0, fill.right(), 0)
        grad.setColorAt(0.0, QColor(W_AMBER_DIM))
        grad.setColorAt(1.0, QColor(W_AMBER))
        p.setBrush(grad)
        p.drawRoundedRect(fill, 4, 4)


class RunConsole(QWidget):
    """Progress pill + % readout + the colour-coded, auto-scrolling log."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(11)

        header = QLabel("RUN CONSOLE")
        header.setObjectName("cardTitle")
        layout.addWidget(header)

        row = QHBoxLayout()
        row.setSpacing(12)
        self._pill = _ProgressPill()
        row.addWidget(self._pill, 1)
        self._pct = QLabel("0%")
        self._pct.setObjectName("cardMeta")
        self._pct.setFixedWidth(44)
        align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        self._pct.setAlignment(align)
        row.addWidget(self._pct)
        layout.addLayout(row)

        self._log = QTextEdit()
        self._log.setObjectName("logView")
        self._log.setReadOnly(True)
        layout.addWidget(self._log, 1)

    def append(self, msg: str, level: str = "info") -> None:
        """Append one colour-coded line. Unknown levels fall back to info."""
        colour = LOG_COLORS.get(level, LOG_COLORS["info"])
        safe = html.escape(msg).replace("\n", "<br>")
        self._log.append(
            f'<span style="color:{colour}; line-height:1.7">{safe}</span>'
        )
        bar = self._log.verticalScrollBar()
        bar.setValue(bar.maximum())

    def clear_log(self) -> None:
        self._log.clear()

    def set_progress(self, current: int, total: int) -> None:
        fraction = (current / total) if total else 0.0
        self._pill.set_fraction(fraction)
        self._pct.setText(f"{round(fraction * 100)}%")

    def reset(self) -> None:
        self.clear_log()
        self.set_progress(0, 1)


class _SliderTrack(QWidget):
    """Paint surface for WizardSlider. Delegates painting to its owner.

    A subclass rather than a monkeypatched paintEvent: assigning onto the
    instance defeats Qt's C++ virtual dispatch in some builds and is opaque
    to type checkers.
    """

    def __init__(self, painter, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._painter = painter

    def paintEvent(self, _event) -> None:          # noqa: N802 (Qt naming)
        self._painter()


class WizardSlider(QWidget):
    """Custom-painted slider with a live readout and sweet-spot pill.

    Two flavours, built via the classmethods. The kind determines the range,
    the snap, the readout text, and where the sweet spot lies — all of which
    come from wizard_logic, never from this file.
    """

    valueChanged = pyqtSignal(int)

    _TRACK_H = 6
    _KNOB_R = 8            # 17px diameter, minus the 1px ring allowance
    _ROW_H = 26

    def __init__(self, kind: str, lo: int, hi: int, step: int, default: int,
                 legend: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind = kind          # "keep" | "creativity"
        self._lo, self._hi, self._step = lo, hi, step

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._track_area = _SliderTrack(self._paint_track)
        self._track_area.setFixedHeight(self._ROW_H)
        layout.addWidget(self._track_area)

        # Invisible native slider laid over the painted track: it owns
        # interaction (drag, click, arrow keys, page-up/down) so we do not
        # reimplement hit-testing.
        self._slider = QSlider(Qt.Orientation.Horizontal, self._track_area)
        self._slider.setRange(lo, hi)
        self._slider.setSingleStep(step)
        self._slider.setPageStep(step)
        self._slider.setValue(default)
        self._slider.setStyleSheet("background: transparent;")
        self._slider.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True
        )
        self._slider.lower()
        self._slider.valueChanged.connect(self._on_change)

        readout_row = QHBoxLayout()
        readout_row.setSpacing(9)
        self._readout = QLabel()
        readout_row.addWidget(self._readout)
        readout_row.addStretch()
        self._pill = QLabel("✦ sweet spot")
        self._pill.setStyleSheet(
            f"color:{RAMP['green']}; background:{W_TILE_SELECTED};"
            f"border-radius:9px; padding:2px 9px; font-size:10px;"
        )
        readout_row.addWidget(self._pill)
        layout.addLayout(readout_row)

        ends = QHBoxLayout()
        lo_lbl, hi_lbl = QLabel(self._end_label(lo)), QLabel(self._end_label(hi))
        for lbl in (lo_lbl, hi_lbl):
            lbl.setStyleSheet(f"color:{W_FAINT2}; font-size:10px;")
        ends.addWidget(lo_lbl)
        ends.addStretch()
        ends.addWidget(hi_lbl)
        layout.addLayout(ends)

        legend_lbl = QLabel(legend)
        legend_lbl.setObjectName("helper")
        layout.addWidget(legend_lbl)

        self._on_change(default)

    # ── constructors ──
    @classmethod
    def keep_pct(cls, parent: QWidget | None = None) -> "WizardSlider":
        return cls(
            "keep", 10, 90, 10, 40,
            "🟢  30–50% keeps the core story without noise", parent,
        )

    @classmethod
    def creativity(cls, parent: QWidget | None = None) -> "WizardSlider":
        return cls(
            "creativity", 1, 10, 1, 5,
            "🟢  5–6 adds vivid prose without inventing plot", parent,
        )

    # ── value ──
    def value(self) -> int:
        return self._slider.value()

    def set_value(self, v: int) -> None:
        self._slider.setValue(v)

    def resizeEvent(self, event) -> None:              # noqa: N802
        super().resizeEvent(event)
        self._slider.setGeometry(self._track_area.rect())

    # ── presentation, all sourced from wizard_logic ──
    def _end_label(self, v: int) -> str:
        if self._kind == "keep":
            return f"{v}%"
        return f"{v} · {wl.creativity_notch(v)[0]}"

    def _readout_for(self, v: int) -> tuple[str, str, bool]:
        """(text, hex colour, is_sweet). Ramp keys become hexes only here."""
        if self._kind == "keep":
            text, sweet = wl.keep_pct_readout(v)
            colour = RAMP["green"] if sweet else W_MUTED
            return text, colour, sweet
        sweet = wl.is_creativity_sweet(v)
        _, ramp_key = wl.creativity_notch(v)
        return wl.creativity_readout(v), RAMP[ramp_key], sweet

    def _on_change(self, v: int) -> None:
        text, colour, sweet = self._readout_for(v)
        self._readout.setText(text)
        self._readout.setStyleSheet(
            f"color:{colour}; font-size:12px; font-weight:600;"
        )
        self._pill.setVisible(sweet)
        self._current_colour = colour
        self._track_area.update()
        self.valueChanged.emit(v)

    def _paint_track(self) -> None:
        """Called by _SliderTrack.paintEvent. Draws track, ticks, fill, knob."""
        p = QPainter(self._track_area)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._track_area.rect()
        cy = r.center().y()
        x0, x1 = r.left() + self._KNOB_R, r.right() - self._KNOB_R
        span = max(1, x1 - x0)
        frac = (self.value() - self._lo) / max(1, self._hi - self._lo)
        knob_x = x0 + int(span * frac)

        # track
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(W_TRACK))
        p.drawRoundedRect(x0, cy - self._TRACK_H // 2, span, self._TRACK_H, 3, 3)

        # ticks
        p.setPen(QPen(QColor(W_FAINT2), 1))
        n_ticks = (self._hi - self._lo) // self._step
        for i in range(n_ticks + 1):
            tx = x0 + int(span * i / n_ticks)
            p.drawLine(tx, cy + 5, tx, cy + 8)

        # fill: W_FILL_START → current ramp colour
        if knob_x > x0:
            grad = QLinearGradient(x0, 0, knob_x, 0)
            grad.setColorAt(0.0, QColor(W_FILL_START))
            grad.setColorAt(1.0, QColor(self._current_colour))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawRoundedRect(
                x0, cy - self._TRACK_H // 2, knob_x - x0, self._TRACK_H, 3, 3
            )

        # knob: amber disc with a dark ring
        p.setPen(QPen(QColor(W_KNOB_RING), 2))
        p.setBrush(QColor(self._current_colour))
        p.drawEllipse(knob_x - self._KNOB_R, cy - self._KNOB_R,
                      self._KNOB_R * 2, self._KNOB_R * 2)


class _ClickableLabel(QLabel):
    """A QLabel that emits clicked. Used for the step-rail badges + labels."""

    clicked = pyqtSignal()

    def mousePressEvent(self, _event) -> None:     # noqa: N802 (Qt naming)
        self.clicked.emit()


class _ClickableTile(QFrame):
    """A QFrame that emits clicked. Used for the mode tiles."""

    clicked = pyqtSignal()

    def mousePressEvent(self, _event) -> None:     # noqa: N802 (Qt naming)
        self.clicked.emit()


_STEP_LABELS = ("Book", "Transform", "Output", "Run")


class StepRail(QWidget):
    """Four numbered badges joined by connector lines. The whole step is clickable."""

    stepClicked = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(9)
        self._badges: list[_ClickableLabel] = []
        self._labels: list[_ClickableLabel] = []
        for i, name in enumerate(_STEP_LABELS, start=1):
            badge = _ClickableLabel(str(i))
            badge.setFixedSize(23, 23)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setCursor(Qt.CursorShape.PointingHandCursor)
            badge.clicked.connect(lambda s=i: self.stepClicked.emit(s))
            label = _ClickableLabel(name)
            label.setCursor(Qt.CursorShape.PointingHandCursor)
            label.clicked.connect(lambda s=i: self.stepClicked.emit(s))
            self._badges.append(badge)
            self._labels.append(label)
            row.addWidget(badge)
            row.addWidget(label)
            if i < len(_STEP_LABELS):
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setStyleSheet(f"color:{W_BORDER};")
                row.addWidget(line, 1)
        self.set_state(1, set(), set())

    def set_state(self, current: int, completed: set[int],
                  errors: set[int]) -> None:
        for i, (badge, label) in enumerate(zip(self._badges, self._labels), 1):
            if i in errors:
                badge.setText("!")
                badge.setStyleSheet(
                    f"border:1px solid {W_ERROR}; border-radius:11px;"
                    f"color:{W_ERROR}; font-size:11px; font-weight:700;"
                )
                label.setStyleSheet(f"color:{W_ERROR}; font-size:12px;")
            elif i == current:
                badge.setText(str(i))
                badge.setStyleSheet(
                    f"background:{W_AMBER}; border-radius:11px;"
                    f"color:{W_KNOB_RING}; font-size:11px; font-weight:700;"
                )
                label.setStyleSheet(f"color:{W_AMBER}; font-size:12px; font-weight:600;")
            elif i in completed:
                badge.setText("✓")
                badge.setStyleSheet(
                    f"background:{W_BADGE_DONE_BG}; border-radius:11px;"
                    f"color:{W_TEXT_SECONDARY}; font-size:11px;"
                )
                label.setStyleSheet(f"color:{W_TEXT_SECONDARY}; font-size:12px;")
            else:
                badge.setText(str(i))
                badge.setStyleSheet(
                    f"border:1px solid {W_BORDER_CTRL}; border-radius:11px;"
                    f"color:{W_MUTED}; font-size:11px;"
                )
                label.setStyleSheet(f"color:{W_MUTED}; font-size:12px;")


_MODE_TILES = (
    ("sr", "Summarise → rewrite",
     "condense, then retell in Spanish at your level"),
    ("full", "Full translation", "whole text, nothing cut — slower"),
    ("sum", "Summarise only (EN)", "condensed English, no translation"),
    ("key", "Summary + key ideas", "+ a book-wide synthesis at the end"),
)


class ModeTileGrid(QWidget):
    """2×2 grid of radio tiles. Selected tile: amber border + tinted fill."""

    modeChanged = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        self._group = QButtonGroup(self)
        self._tiles: dict[str, _ClickableTile] = {}
        self._radios: dict[str, QRadioButton] = {}

        for i, (key, title, desc) in enumerate(_MODE_TILES):
            tile = _ClickableTile()
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            box = QVBoxLayout(tile)
            box.setContentsMargins(12, 11, 12, 11)
            box.setSpacing(3)
            radio = QRadioButton(title)
            radio.setStyleSheet("font-size:13px; font-weight:600;")
            self._group.addButton(radio)
            box.addWidget(radio)
            sub = QLabel(desc)
            sub.setObjectName("helper")
            sub.setContentsMargins(25, 0, 0, 0)
            box.addWidget(sub)
            grid.addWidget(tile, i // 2, i % 2)
            self._tiles[key] = tile
            self._radios[key] = radio
            radio.toggled.connect(
                lambda checked, k=key: checked and self._select(k)
            )
            tile.clicked.connect(lambda k=key: self._radios[k].setChecked(True))

        self._mode = "sr"
        self._radios["sr"].setChecked(True)
        self._restyle()

    def _select(self, key: str) -> None:
        if key == self._mode:
            return
        self._mode = key
        self._restyle()
        self.modeChanged.emit(key)

    def _restyle(self) -> None:
        for key, tile in self._tiles.items():
            if key == self._mode:
                tile.setStyleSheet(
                    f"background:{W_TILE_SELECTED}; border:1px solid {W_AMBER};"
                    f"border-radius:9px;"
                )
            else:
                tile.setStyleSheet(
                    f"background:{W_SURFACE}; border:1px solid {W_BORDER};"
                    f"border-radius:9px;"
                )

    def mode(self) -> str:
        return self._mode

    def set_mode(self, key: str) -> None:
        self._radios[key].setChecked(True)


class TriStateChapterList(QWidget):
    """'Select all' tri-state master + a scrollable list of chapter checkboxes."""

    selectionChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._master = QCheckBox("Select all")
        self._master.setTristate(True)
        self._master.clicked.connect(self._on_master_clicked)
        layout.addWidget(self._master)

        self._inner = QWidget()
        self._inner_layout = QVBoxLayout(self._inner)
        self._inner_layout.setContentsMargins(8, 6, 8, 6)
        self._inner_layout.setSpacing(2)
        self._inner_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._inner)
        scroll.setMaximumHeight(188)
        scroll.setStyleSheet(
            f"background:{W_INSET}; border:1px solid {W_BORDER};"
            f"border-radius:8px;"
        )
        layout.addWidget(scroll)

        # Store the ChapterRow itself, never re-parse it out of the label:
        # the display format ("01.  Title") must not be load-bearing data.
        self._boxes: list[tuple[wl.ChapterRow, QCheckBox]] = []

    def clear(self) -> None:
        for _, box in self._boxes:
            box.setParent(None)
        self._boxes = []
        self._sync_master()

    def set_chapters(self, rows: list["wl.ChapterRow"]) -> None:
        self.clear()
        for row in rows:
            box = QCheckBox(f"{row.index + 1:02d}.  {row.title}")
            box.setChecked(row.checked)
            box.setStyleSheet(f"QCheckBox:hover {{ background:{W_ROW_HOVER}; }}")
            box.stateChanged.connect(self._on_child_changed)
            self._inner_layout.insertWidget(self._inner_layout.count() - 1, box)
            self._boxes.append((row, box))
        self._sync_master()

    def rows(self) -> list["wl.ChapterRow"]:
        return [replace(row, checked=box.isChecked())
                for row, box in self._boxes]

    def _on_master_clicked(self) -> None:
        # A tri-state master must drive children to a definite state, never
        # leave them Partially — clicking it always means "all" or "none".
        target = self._master.checkState() != Qt.CheckState.Unchecked
        for _, box in self._boxes:
            box.blockSignals(True)
            box.setChecked(target)
            box.blockSignals(False)
        self._sync_master()
        self.selectionChanged.emit()

    def _on_child_changed(self, _state: int) -> None:
        self._sync_master()
        self.selectionChanged.emit()

    def _sync_master(self) -> None:
        total = len(self._boxes)
        checked = sum(1 for _, box in self._boxes if box.isChecked())
        self._master.blockSignals(True)
        if total and checked == total:
            self._master.setCheckState(Qt.CheckState.Checked)
        elif checked == 0:
            self._master.setCheckState(Qt.CheckState.Unchecked)
        else:
            self._master.setCheckState(Qt.CheckState.PartiallyChecked)
        self._master.blockSignals(False)
