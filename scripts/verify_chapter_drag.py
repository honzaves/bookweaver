"""Manual drag check: prints which model signal a real drop emits.

    python scripts/verify_chapter_drag.py <book.epub>

pytest stubs PyQt6 and the offscreen harness cannot synthesise a real
QDrag, so this is the only way to learn whether an InternalMove DROP
routes through QListModel::moveRows (emitting rowsMoved, which
TriStateChapterList listens for) or through take/insert (emitting
rowsInserted/rowsRemoved, which would leave the relabel handler dead).

Drag ONE row, then read the output:
  SIGNAL rowsMoved + a labels: line   -> the design is correct.
  SIGNAL rowsInserted/rowsRemoved and
  NO labels: line                     -> relabelling is dead on the drag
                                         path; report before fixing.
The SIGNAL tracers hang off the model, so they print either way; the
labels: line only prints when selectionChanged actually fired.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import epub_io  # noqa: E402
import wizard_logic as wl  # noqa: E402
from wizard_widgets import TriStateChapterList  # noqa: E402

app = QApplication([])
lst = TriStateChapterList()
lst.set_chapters([wl.ChapterRow(c.index, c.title, True)
                  for c in epub_io.extract_chapters(sys.argv[1])])


def _state() -> list[str]:
    """Position label + the row's source index, so a reorder is visible.
    (The bare '01.'-'20.' prefixes are identical after ANY correct
    relabel, so printing them alone proves nothing about order.)"""
    return [f"{lst._list.item(i).text().split('.')[0]}"
            f"<-{lst._list.item(i).data(Qt.ItemDataRole.UserRole).index}"
            for i in range(lst._list.count())]


for name in ("rowsMoved", "rowsInserted", "rowsRemoved"):
    getattr(lst._list.model(), name).connect(
        lambda *a, n=name: print("SIGNAL", n)
    )
lst.selectionChanged.connect(lambda: print("  relabelled ->", _state()))
lst.resize(520, 400)
lst.show()
app.exec()

# The verdict. Qt can fire further structural signals AFTER the relabel
# handler runs (a drop that moves rows and then re-does it through the
# mime path), which would leave a row holding a stale number or, worse,
# no ▲▼ widget at all. Only the state after the window closes proves it.
print("\nFINAL STATE")
bad_label, no_widget = [], []
for i in range(lst._list.count()):
    item = lst._list.item(i)
    row = item.data(Qt.ItemDataRole.UserRole)
    has_widget = lst._list.itemWidget(item) is not None
    print(f"  {item.text()!r:<40} src_index={row.index:<3} "
          f"buttons={'yes' if has_widget else 'NO'}")
    if not item.text().startswith(f"{i + 1:02d}."):
        bad_label.append(i)
    if not has_widget:
        no_widget.append(i)
print(f"\nrows={lst._list.count()}  "
      f"stale labels at {bad_label or 'none'}  "
      f"missing ▲▼ at {no_widget or 'none'}")
print("PASS — drag path is sound" if not (bad_label or no_widget)
      else "FAIL — see above; report before fixing")
