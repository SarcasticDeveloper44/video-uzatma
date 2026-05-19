"""Source picker: a folder, a single video, or multiple videos.

Drag-drop accepts:
  - a folder       → all videos in it (recursive optional)
  - a single video → process just that one
  - multiple videos → process exactly that set

A single "Seç…" button opens ONE non-native QFileDialog where both files
AND folders are visible. The dialog grew a "Bu klasörü kullan" button via
injection so the user can confirm whichever they want (files via "Aç",
folder via the custom button). Native OS dialogs can't mix the two modes
(Windows IFileDialog, macOS NSOpenPanel, Linux GtkFileChooser all separate
file vs folder selection), so non-native + custom button is the only way
to get one-click-one-dialog UX.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from video_extender.utils.paths import is_video


class FolderPicker(QWidget):
    folder_changed = Signal(Path)
    files_chosen = Signal(list)         # list[Path] — explicit video files
    recursive_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._folder: Path | None = None

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.path_label = QLabel(
            "<i>Klasör veya video dosyalarını buraya sürükle — ya da seç düğmelerini kullan.</i>"
        )
        self.path_label.setStyleSheet(
            "padding: 14px; border: 2px dashed #888; border-radius: 6px;"
        )
        self.path_label.setMinimumHeight(60)
        self.btn_select = QPushButton("Seç…")
        self.btn_select.setToolTip(
            "Tek dialog'ta hem video dosyaları hem klasör seçebilirsin"
        )
        self.btn_select.clicked.connect(self._pick)
        row.addWidget(self.path_label, 1)
        row.addWidget(self.btn_select)
        layout.addLayout(row)

        self.recursive_cb = QCheckBox("Alt klasörleri de tara")
        self.recursive_cb.toggled.connect(self.recursive_toggled)
        layout.addWidget(self.recursive_cb)

        self.setAcceptDrops(True)

    @property
    def folder(self) -> Path | None:
        return self._folder

    @property
    def recursive(self) -> bool:
        return self.recursive_cb.isChecked()

    # --- pick handlers ---
    def _pick(self) -> None:
        """Single dialog: shows both files and folders, lets user confirm
        EITHER by selecting video files + "Aç", OR by navigating to a folder
        and clicking the injected "Bu klasörü kullan" button.
        """
        start = str(self._folder or Path.home())
        dialog = QFileDialog(self, "Klasör veya video(lar) seç", start)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, False)
        dialog.setNameFilter(
            "Video (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.flv *.wmv "
            "*.mpg *.mpeg *.ts *.m2ts *.3gp *.ogv *.mxf *.f4v);;"
            "Tüm dosyalar (*)"
        )

        # Inject a "use this folder" action button into the dialog's button
        # box. Clicking it captures the current directory and accepts the
        # dialog with an early-exit flag we can read after exec().
        use_folder_flag = {"clicked": False}
        button_box = dialog.findChild(QDialogButtonBox)
        if button_box is not None:
            btn = QPushButton("Bu klasörü kullan")
            btn.setToolTip(
                "İçinde bulunduğun klasörü seç (klasördeki tüm videolar işlenir)"
            )

            def _on_use_folder() -> None:
                use_folder_flag["clicked"] = True
                dialog.accept()

            btn.clicked.connect(_on_use_folder)
            button_box.addButton(btn, QDialogButtonBox.ButtonRole.ActionRole)

        if not dialog.exec():
            return

        if use_folder_flag["clicked"]:
            current_dir = Path(dialog.directory().absolutePath())
            if current_dir.is_dir():
                self._set_folder(current_dir)
            return

        # Default OK path: user multi-selected video files.
        selected = [Path(f) for f in dialog.selectedFiles()]
        # Defensive: if Qt somehow returned a single directory (rare in
        # ExistingFiles mode), treat it as folder mode.
        if len(selected) == 1 and selected[0].is_dir():
            self._set_folder(selected[0])
            return
        files = [p for p in selected if p.is_file() and is_video(p)]
        if files:
            self._set_files(files)

    # --- internal state setters (emit appropriate signal) ---
    def _set_folder(self, p: Path) -> None:
        self._folder = p
        self.path_label.setText(f"<b>{p}</b>")
        self.folder_changed.emit(p)

    def _set_files(self, files: list[Path]) -> None:
        if not files:
            return
        # The parent of the first file becomes the "source folder" for
        # output/state purposes. All explicit files are passed downstream.
        self._folder = files[0].parent
        if len(files) == 1:
            self.path_label.setText(
                f"<b>{files[0].name}</b><br>"
                f"<small style='color:#888;'>{files[0].parent}</small>"
            )
        else:
            preview = ", ".join(f.name for f in files[:3])
            suffix = "…" if len(files) > 3 else ""
            self.path_label.setText(
                f"<b>{len(files)} video</b><br>"
                f"<small style='color:#888;'>{preview}{suffix} — {files[0].parent}</small>"
            )
        self.files_chosen.emit(files)

    # --- drag & drop ---
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        urls = event.mimeData().urls()
        # Accept if ANY url is a directory or a recognised video file.
        for u in urls:
            p = Path(u.toLocalFile())
            if p.is_dir() or is_video(p):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        paths = [Path(u.toLocalFile()) for u in urls]
        # Prefer a directory drop over a mixed/files drop: if any path is a
        # dir, treat the whole drop as that single directory.
        for p in paths:
            if p.is_dir():
                self._set_folder(p)
                event.acceptProposedAction()
                return
        # Otherwise collect every video file in the drop.
        files = [p for p in paths if is_video(p)]
        if files:
            self._set_files(files)
            event.acceptProposedAction()
            return
        event.ignore()
