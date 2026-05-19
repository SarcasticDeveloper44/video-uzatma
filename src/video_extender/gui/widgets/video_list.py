"""Video list with per-row progress bars and status."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QMenu, QProgressBar, QTableWidget,
    QTableWidgetItem, QWidget,
)

from video_extender.core.job import Job, JobStatus
from video_extender.utils.duration import format_duration


def _format_eta(seconds: float) -> str:
    if seconds <= 0 or seconds > 86400:
        return "—"
    if seconds < 60:
        return f"{int(seconds)}s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


def _format_filesize(num_bytes: int) -> str:
    if num_bytes <= 0:
        return "—"
    units = ["B", "KB", "MB", "GB"]
    val = float(num_bytes)
    for u in units:
        if val < 1024 or u == "GB":
            return f"{val:.1f} {u}" if u != "B" else f"{int(val)} {u}"
        val /= 1024
    return f"{val:.1f} GB"

STATUS_TEXT = {
    JobStatus.PENDING:   "Bekliyor",
    JobStatus.PROBING:   "İnceleniyor",
    JobStatus.QUEUED:    "Kuyrukta",
    JobStatus.RUNNING:   "İşleniyor",
    JobStatus.COMPLETED: "Tamam",
    JobStatus.FAILED:    "HATA",
    JobStatus.CANCELLED: "İptal",
    JobStatus.SKIPPED:   "Atlandı",
}

STATUS_COLOR = {
    JobStatus.COMPLETED: "#2e7d32",
    JobStatus.FAILED:    "#c62828",
    JobStatus.CANCELLED: "#6a6a6a",
    JobStatus.SKIPPED:   "#1565c0",
    JobStatus.RUNNING:   "#ef6c00",
}


class VideoListWidget(QTableWidget):
    """Table showing each Job's status and progress."""
    row_open_log = Signal(Path)
    row_remove_requested = Signal(Path)  # emits source path of row to remove
    row_retry_requested = Signal(Path)   # emits source path of failed row to retry

    COLS = ["Dosya", "Süre", "Çözünürlük", "Durum", "İlerleme", "Hız", "ETA", "Boyut", "Worker"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, len(self.COLS), parent)
        self.setHorizontalHeaderLabels(self.COLS)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        h = self.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(self.COLS)):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self._row_for_source: dict[Path, int] = {}
        # Right-click context menu for removing pending rows.
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    def _on_context_menu(self, pos: QPoint) -> None:
        idx = self.indexAt(pos)
        if not idx.isValid():
            return
        row = idx.row()
        source = next((s for s, r in self._row_for_source.items() if r == row), None)
        if source is None:
            return
        status_item = self.item(row, 3)
        status_text = status_item.text() if status_item else ""
        menu = QMenu(self)
        if status_text == STATUS_TEXT[JobStatus.FAILED]:
            retry = QAction("Bu video'yu yeniden dene", self)
            retry.triggered.connect(lambda: self.row_retry_requested.emit(source))
            menu.addAction(retry)
        elif status_text in {STATUS_TEXT[JobStatus.PENDING], STATUS_TEXT[JobStatus.QUEUED]}:
            remove = QAction("Bu video'yu listeden çıkar", self)
            remove.triggered.connect(lambda: self.row_remove_requested.emit(source))
            menu.addAction(remove)
        else:
            return  # running/completed/cancelled/skipped — no actions
        menu.exec(self.viewport().mapToGlobal(pos))

    def remove_row_for(self, source: Path) -> bool:
        """Remove the row matching `source`. Re-indexes the source→row map."""
        if source not in self._row_for_source:
            return False
        row = self._row_for_source[source]
        self.removeRow(row)
        del self._row_for_source[source]
        # Shift all entries below the removed row up by one.
        for s, r in list(self._row_for_source.items()):
            if r > row:
                self._row_for_source[s] = r - 1
        return True

    def clear_rows(self) -> None:
        self.setRowCount(0)
        self._row_for_source.clear()

    def add_job(self, job: Job) -> None:
        row = self.rowCount()
        self.insertRow(row)
        self._row_for_source[job.source] = row

        name_item = QTableWidgetItem(job.source.name)
        name_item.setToolTip(str(job.source))
        self.setItem(row, 0, name_item)

        dur = format_duration(job.media.duration) if job.media else "—"
        self.setItem(row, 1, QTableWidgetItem(dur))

        res = "—"
        if job.media and job.media.video:
            res = f"{job.media.video.width}×{job.media.video.height}"
        self.setItem(row, 2, QTableWidgetItem(res))

        status_item = QTableWidgetItem(STATUS_TEXT[job.status])
        self.setItem(row, 3, status_item)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(True)
        self.setCellWidget(row, 4, bar)
        self.setItem(row, 5, QTableWidgetItem("—"))   # Speed
        self.setItem(row, 6, QTableWidgetItem("—"))   # ETA
        self.setItem(row, 7, QTableWidgetItem("—"))   # Output size
        self.setItem(row, 8, QTableWidgetItem(""))    # Worker

    def update_job(self, job: Job) -> None:
        row = self._row_for_source.get(job.source)
        if row is None:
            return
        status_item = self.item(row, 3)
        if status_item:
            tooltip = job.error or ""
            text = STATUS_TEXT[job.status]
            status_item.setText(text)
            status_item.setToolTip(tooltip)
            color = STATUS_COLOR.get(job.status)
            if color:
                status_item.setForeground(Qt.GlobalColor.red if job.status == JobStatus.FAILED else Qt.GlobalColor.black)
                status_item.setData(Qt.ItemDataRole.ForegroundRole, None)
                status_item.setBackground(Qt.BrushStyle.NoBrush)
        bar = self.cellWidget(row, 4)
        if isinstance(bar, QProgressBar):
            pct = int(job.progress * 100)
            bar.setValue(pct)
        # Speed / ETA / Worker
        speed_item = self.item(row, 5)
        if speed_item:
            speed_item.setText(f"{job.speed:.1f}x" if job.speed > 0 else "—")
        eta_item = self.item(row, 6)
        if eta_item:
            if job.status == JobStatus.RUNNING:
                eta_item.setText(_format_eta(job.eta_seconds))
            elif job.status == JobStatus.COMPLETED:
                eta_item.setText("✓")
            elif job.status in (JobStatus.FAILED, JobStatus.CANCELLED):
                eta_item.setText("—")
            elif job.status == JobStatus.SKIPPED:
                eta_item.setText("atlandı")
        size_item = self.item(row, 7)
        if size_item:
            if job.status == JobStatus.COMPLETED and job.output and job.output.exists():
                try:
                    size_item.setText(_format_filesize(job.output.stat().st_size))
                except OSError:
                    size_item.setText("—")
            elif job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
                size_item.setText("—")
        worker_item = self.item(row, 8)
        if worker_item and job.worker_label:
            worker_item.setText(job.worker_label)
