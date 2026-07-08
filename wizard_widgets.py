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
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QSlider, QTextEdit, QVBoxLayout,
    QWidget,
)

import wizard_logic as wl
from wizard_theme import (
    LOG_COLORS, RAMP, W_AMBER, W_AMBER_DIM, W_BORDER, W_CONSOLE_BG, W_FAINT2,
    W_FILL_START, W_INSET, W_KNOB_RING, W_MUTED, W_SURFACE, W_TEXT,
    W_TILE_SELECTED, W_TRACK, W_BORDER_CTRL, W_BADGE_DONE_BG, W_ERROR,
    W_TEXT_SECONDARY, W_ROW_HOVER,
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
