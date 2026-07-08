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
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)

import wizard_logic as wl
from wizard_theme import (
    LOG_COLORS, RAMP, W_AMBER, W_AMBER_DIM, W_BORDER, W_CONSOLE_BG, W_FAINT2,
    W_INSET, W_KNOB_RING, W_MUTED, W_SURFACE, W_TEXT, W_TILE_SELECTED,
    W_TRACK, W_FILL_START, W_BORDER_CTRL, W_BADGE_DONE_BG, W_ERROR,
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
