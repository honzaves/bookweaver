"""
widgets.py
----------
Reusable custom Qt widgets used by the main application window.

Classes
-------
SummarizationSlider  — labelled slider controlling chapter compression.
CreativitySlider     — labelled slider controlling LLM elaboration freedom.
FilePickerRow        — inline path display + browse button for EPUB files.
FolderPickerRow      — inline path display + browse button for directories.
LogWidget            — colour-coded read-only log pane.
ProgressBar          — thin custom amber progress bar.
"""

import html
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from settings import (
    C_AMBER,
    C_ERROR,
    C_MUTED,
    C_SUCCESS,
    C_SWEET,
    C_TEXT,
    C_WARNING,
    C_BORDER,
    creativity_to_temperature,
)


# ──────────────────────────────────────────────────────────────
#  SUMMARISATION SLIDER
# ──────────────────────────────────────────────────────────────
class SummarizationSlider(QWidget):
    """
    Horizontal slider (10–90 %) controlling how much of each chapter
    is retained after summarisation.

    The readout turns green inside the recommended 30–50 % sweet spot.
    """

    valueChanged = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._readout = QLabel("Keep  40%  of original")
        self._readout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._readout.setStyleSheet(
            f"color: {C_AMBER}; font-size: 13px; font-weight: 600;"
        )
        layout.addWidget(self._readout)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(10)
        self._slider.setMaximum(90)
        self._slider.setValue(40)
        self._slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._slider.setTickInterval(10)
        layout.addWidget(self._slider)

        tick_row = QHBoxLayout()
        tick_row.setContentsMargins(2, 0, 2, 0)
        for v in range(10, 91, 10):
            lbl = QLabel(f"{v}%")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"font-size: 10px; color: {C_MUTED};")
            tick_row.addWidget(lbl)
        layout.addLayout(tick_row)

        legend = QLabel("🟢  Sweet spot: 30–50% keeps core story without noise")
        legend.setStyleSheet(
            f"font-size: 11px; color: {C_MUTED}; margin-top: 2px;"
        )
        legend.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(legend)

        self._slider.valueChanged.connect(self._on_change)

    def _on_change(self, v: int) -> None:
        reduction = 100 - v
        in_sweet = 30 <= v <= 50
        colour = C_SWEET if in_sweet else C_AMBER
        tag = "  ✦ sweet spot" if in_sweet else ""
        self._readout.setText(
            f"Keep  {v}%  of original  (↓ {reduction}% reduction){tag}"
        )
        self._readout.setStyleSheet(
            f"color: {colour}; font-size: 13px; font-weight: 600;"
        )
        self.valueChanged.emit(v)

    def value(self) -> int:
        return self._slider.value()


# ──────────────────────────────────────────────────────────────
#  CREATIVITY SLIDER
# ──────────────────────────────────────────────────────────────
class CreativitySlider(QWidget):
    """
    Horizontal slider (1–10) controlling how freely the LLM may add
    details beyond what the summary states.  Also determines the Ollama
    temperature that is passed to the model.
    """

    valueChanged = pyqtSignal(int)

    # (label, colour) pairs for each notch
    LABELS: dict[int, tuple[str, str]] = {
        1: ("Verbatim", C_MUTED),
        2: ("Faithful", C_MUTED),
        3: ("Faithful+", C_TEXT),
        4: ("Enriched", C_TEXT),
        5: ("Enriched+", C_SWEET),   # sweet-spot start
        6: ("Vivid", C_SWEET),       # sweet-spot end
        7: ("Expressive", C_AMBER),
        8: ("Inventive", C_AMBER),
        9: ("Free", C_WARNING),
        10: ("Unbound", C_ERROR),
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._readout = QLabel()
        self._readout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._readout)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(1)
        self._slider.setMaximum(10)
        self._slider.setValue(5)
        self._slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._slider.setTickInterval(1)
        layout.addWidget(self._slider)

        tick_row = QHBoxLayout()
        tick_row.setContentsMargins(2, 0, 2, 0)
        for v in range(1, 11):
            lbl = QLabel(str(v))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"font-size: 10px; color: {C_MUTED};")
            tick_row.addWidget(lbl)
        layout.addLayout(tick_row)

        legend = QLabel(
            "🟢  Sweet spot: 5–6 adds vivid prose without inventing plot events"
        )
        legend.setStyleSheet(
            f"font-size: 11px; color: {C_MUTED}; margin-top: 2px;"
        )
        legend.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(legend)

        self._slider.valueChanged.connect(self._on_change)
        self._on_change(5)  # initialise readout

    def _on_change(self, v: int) -> None:
        label, colour = self.LABELS.get(v, ("Custom", C_TEXT))
        temp = creativity_to_temperature(v)
        tag = "  ✦ sweet spot" if 5 <= v <= 6 else ""
        self._readout.setText(
            f"{label}  —  level {v}/10   (temperature ≈ {temp}){tag}"
        )
        self._readout.setStyleSheet(
            f"color: {colour}; font-size: 13px; font-weight: 600;"
        )
        self.valueChanged.emit(v)

    def value(self) -> int:
        return self._slider.value()


# ──────────────────────────────────────────────────────────────
#  FILE PICKER ROW
# ──────────────────────────────────────────────────────────────
class FilePickerRow(QWidget):
    """
    Inline read-only path display with a Browse button that filters
    for EPUB files.

    Emits *fileSelected(path)* whenever the user picks a file.
    """

    fileSelected = pyqtSignal(str)

    def __init__(
        self, placeholder: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText(placeholder)
        self._edit.setReadOnly(True)
        layout.addWidget(self._edit, 1)

        btn = QPushButton("Browse…")
        btn.setFixedWidth(90)
        btn.clicked.connect(self._browse)
        layout.addWidget(btn)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select EPUB file",
            "",
            "EPUB files (*.epub);;All files (*)",
        )
        if path:
            self._edit.setText(path)
            self.fileSelected.emit(path)

    def path(self) -> str:
        return self._edit.text()


# ──────────────────────────────────────────────────────────────
#  FOLDER PICKER ROW
# ──────────────────────────────────────────────────────────────
class FolderPickerRow(QWidget):
    """Inline editable path display with a Browse button for directories."""

    def __init__(
        self, placeholder: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText(placeholder)
        layout.addWidget(self._edit, 1)

        btn = QPushButton("Browse…")
        btn.setFixedWidth(90)
        btn.clicked.connect(self._browse)
        layout.addWidget(btn)

    def _browse(self) -> None:
        start = self._edit.text() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(
            self, "Select output folder", start
        )
        if folder:
            self._edit.setText(folder)

    def path(self) -> str:
        return self._edit.text().strip()

    def set_path(self, p: str) -> None:
        self._edit.setText(p)


# ──────────────────────────────────────────────────────────────
#  LOG WIDGET
# ──────────────────────────────────────────────────────────────
class LogWidget(QTextEdit):
    """Read-only HTML log pane with colour-coded severity levels."""

    COLOURS: dict[str, str] = {
        "info": C_TEXT,
        "success": C_SUCCESS,
        "warning": C_WARNING,
        "error": C_ERROR,
        "muted": C_MUTED,
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMinimumHeight(180)

    def append_line(self, msg: str, level: str = "info") -> None:
        colour = self.COLOURS.get(level, C_TEXT)
        escaped = html.escape(msg)
        self.append(f'<span style="color:{colour};">{escaped}</span>')
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().maximum()
        )


# ──────────────────────────────────────────────────────────────
#  PROGRESS BAR
# ──────────────────────────────────────────────────────────────
class ProgressBar(QWidget):
    """Thin custom amber progress bar (6 px tall, rounded caps)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(6)
        self._value = 0
        self._maximum = 1

    def setValue(self, v: int) -> None:
        self._value = v
        self.update()

    def setMaximum(self, m: int) -> None:
        self._maximum = max(1, m)
        self.update()

    def reset(self) -> None:
        self._value = 0
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = h // 2

        # track
        p.setBrush(QBrush(QColor(C_BORDER)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, w, h, r, r)

        # fill
        fill_w = int(w * self._value / self._maximum)
        if fill_w > 0:
            p.setBrush(QBrush(QColor(C_AMBER)))
            p.drawRoundedRect(0, 0, fill_w, h, r, r)

        p.end()
