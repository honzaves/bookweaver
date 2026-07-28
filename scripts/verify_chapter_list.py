"""Offscreen behaviour check for the reorderable TriStateChapterList.
pytest stubs PyQt6, so this runs as a plain script:
    QT_QPA_PLATFORM=offscreen python scripts/verify_chapter_list.py
Prints PASS/FAIL per check; exits non-zero on any FAIL."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QModelIndex, Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication, QStyle, QStyleOptionViewItem,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import wizard_logic as wl  # noqa: E402
from wizard_widgets import TriStateChapterList  # noqa: E402

app = QApplication([])
failures = []


def check(name: str, cond: bool) -> None:
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        failures.append(name)


lst = TriStateChapterList()
emitted = []
lst.selectionChanged.connect(lambda: emitted.append(1))
rows = [wl.ChapterRow(0, "Intro", True), wl.ChapterRow(1, "One", True),
        wl.ChapterRow(2, "Two", False), wl.ChapterRow(3, "Epilogue", True)]
lst.set_chapters(rows)

check("initial order", [r.index for r in lst.rows()] == [0, 1, 2, 3])
check("initial checked",
      [r.checked for r in lst.rows()] == [True, True, False, True])
check("initial labels renumbered",
      lst._list.item(0).text() == "01.  Intro" and lst._list.item(3).text() == "04.  Epilogue")

# ▲▼ buttons: move Epilogue (row 3) up one.
emitted.clear()
lst._move_item(lst._list.item(3), -1)
check("button move: order", [r.index for r in lst.rows()] == [0, 1, 3, 2])
check("button move: relabel", lst._list.item(2).text() == "03.  Epilogue")
check("button move: emits selectionChanged", len(emitted) == 1)

# "Drag" path — CAVEAT: this calls model().moveRow directly, which is
# VERIFIED to emit rowsMoved (probed, PyQt6 6.11). It does NOT prove that a
# real InternalMove DROP takes the same route: QListWidget::dropEvent might
# instead take/insert rows, which emits rowsInserted/rowsRemoved and would
# leave _on_rows_moved dead (labels stop renumbering after a drag while every
# check here still prints PASS). Only Step 7 can settle that — do not treat a
# green run of this script as proof the drag path works.
emitted.clear()
lst._list.model().moveRow(QModelIndex(), 2, QModelIndex(), 0)
check("drag move: order", [r.index for r in lst.rows()] == [3, 0, 1, 2])
check("drag move: relabel", lst._list.item(0).text() == "01.  Epilogue")
check("drag move: emits selectionChanged", len(emitted) >= 1)
check("drag move: item widgets restored",
      all(lst._list.itemWidget(lst._list.item(i)) is not None
          for i in range(lst._list.count())))

# Checked state survives reorders; toggling still works.
check("checked survives moves",
      [r.checked for r in lst.rows()] == [True, True, True, False])
emitted.clear()
lst._list.item(0).setCheckState(Qt.CheckState.Unchecked)
check("toggle: rows() reflects", lst.rows()[0].checked is False)
check("toggle: emits selectionChanged", len(emitted) == 1)

# Edge buttons disabled at the ends.
top = lst._list.itemWidget(lst._list.item(0))
bottom = lst._list.itemWidget(lst._list.item(3))
check("top row ▲ disabled", not top._up.isEnabled() and top._down.isEnabled())
check("bottom row ▼ disabled",
      bottom._down.isEnabled() is False and bottom._up.isEnabled())

# rows() round-trips through set_chapters (StepBook load_from path).
lst.set_chapters(lst.rows())
check("round-trip keeps order", [r.index for r in lst.rows()] == [3, 0, 1, 2])

# A REAL mouse click on the check indicator must toggle the row.
# setCheckState() above proves the model side only; it cannot catch the
# failure mode that setItemWidget introduces. Qt registers an item widget
# as a PERSISTENT EDITOR for that index, and QAbstractItemView::edit()
# returns early when an index has one — so the delegate that toggles the
# check state never sees the release, and every checkbox goes dead even
# though the ▲▼ overlay never covers the indicator.
lst.show()          # geometry is only real once shown
lst2 = lst


def _indicator_center(i: int):
    view = lst2._list
    opt = QStyleOptionViewItem()
    opt.initFrom(view)
    opt.rect = view.visualRect(view.indexFromItem(view.item(i)))
    opt.features |= QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
    return view.style().subElementRect(
        QStyle.SubElement.SE_ItemViewItemCheckIndicator, opt, view).center()


emitted.clear()
before = lst._list.item(0).checkState()
QTest.mouseClick(lst._list.viewport(), Qt.MouseButton.LeftButton,
                 Qt.KeyboardModifier.NoModifier, _indicator_center(0))
check("click on indicator toggles the row",
      lst._list.item(0).checkState() != before)
check("click toggle reaches rows()",
      lst.rows()[0].checked == (before != Qt.CheckState.Checked))
check("click toggle emits selectionChanged", len(emitted) == 1)

# Clicking the row's TEXT must not toggle it — only the indicator does.
emitted.clear()
state = lst._list.item(1).checkState()
text_point = lst._list.visualRect(
    lst._list.indexFromItem(lst._list.item(1))).center()
QTest.mouseClick(lst._list.viewport(), Qt.MouseButton.LeftButton,
                 Qt.KeyboardModifier.NoModifier, text_point)
check("click on text does not toggle",
      lst._list.item(1).checkState() == state)

# 'Select all' master, driven by a real click (it fires on `clicked`, so
# setCheckState alone would never exercise _on_master_clicked).
lst._master.setCheckState(Qt.CheckState.Unchecked)
lst._master.click()
check("master click checks every row",
      all(r.checked for r in lst.rows()))
lst._master.click()
check("master click again unchecks every row",
      not any(r.checked for r in lst.rows()))

lst.grab().save("/tmp/chapter_list.png")
print("screenshot -> /tmp/chapter_list.png")
sys.exit(1 if failures else 0)
