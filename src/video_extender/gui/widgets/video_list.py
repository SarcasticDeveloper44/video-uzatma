"""Video list with per-row progress bars and status."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QProgressBar, QTableWidget, QTableWidgetItem, QWidget,
)

from video_extender.core.job import Job, JobStatus
from video_extender.utils.duration import format_duration

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

    COLS = ["Dosya", "Süre", "Çözünürlük", "Durum", "İlerleme"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, len(self.COLS), parent)
        self.setHorizontalHeaderLabels(self.COLS)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        h = self.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, len(self.COLS)):
            h.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self._row_for_source: dict[Path, int] = {}

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
                status_item.setData(Qt.ForegroundRole, None)
                status_item.setBackground(Qt.NoBrush)
        bar = self.cellWidget(row, 4)
        if isinstance(bar, QProgressBar):
            pct = int(job.progress * 100)
            bar.setValue(pct)
