"""
conftest.py
-----------
Adds the project root to sys.path so that test modules can import
prompts, worker, settings, etc. without installation.

Also installs lightweight PyQt6 stubs so that worker.py (which imports
QThread / pyqtSignal at module level) can be collected in environments
where Qt is not installed.  The stubs are just enough to satisfy the
import; actual Qt behaviour is not needed for any of our unit tests.
"""
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

# ── project root on path ───────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── PyQt6 stubs (only installed when PyQt6 is absent) ─────────
def _make_pyqt6_stubs() -> None:
    """
    Create just enough of the PyQt6 namespace for worker.py to import
    without a real Qt installation.  Tests that exercise the worker
    bypass __init__ and mock the signals themselves.
    """
    if "PyQt6" in sys.modules:
        return  # real Qt is available — nothing to do

    # Minimal pyqtSignal stub: returns a MagicMock descriptor
    # PyQt6.QtCore stub
    class _QThreadStub:
        """Minimal QThread replacement that lets ProcessingWorker.__init__ run."""
        def __init__(self):
            pass
        def start(self):
            pass
        def isRunning(self):
            return False
        def wait(self):
            pass

    def pyqtSignal(*args, **kwargs):  # noqa: N802
        return MagicMock()

    qtcore = ModuleType("PyQt6.QtCore")
    qtcore.QThread = _QThreadStub
    qtcore.pyqtSignal = pyqtSignal

    # PyQt6 package stub
    pyqt6 = ModuleType("PyQt6")
    pyqt6.QtCore = qtcore

    sys.modules["PyQt6"] = pyqt6
    sys.modules["PyQt6.QtCore"] = qtcore

_make_pyqt6_stubs()
