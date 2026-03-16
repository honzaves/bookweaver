#!/usr/bin/env python3
"""
main.py
-------
Entry point for BookWeaver.

Usage
-----
    python main.py
"""

import sys

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from app import BookWeaverApp
from settings import (
    C_BG,
    C_SURFACE,
    C_TEXT,
    C_SURFACE2,
    STYLESHEET,
)


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)

    # Force dark palette so macOS native controls don't fight the stylesheet.
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(C_BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(C_TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(C_SURFACE))
    palette.setColor(QPalette.ColorRole.Text, QColor(C_TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(C_SURFACE2))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(C_TEXT))
    app.setPalette(palette)

    win = BookWeaverApp()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
