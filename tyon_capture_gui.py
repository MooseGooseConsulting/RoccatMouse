# SPDX-License-Identifier: MIT
"""Small, dedicated launcher for Tyon paddle and wheel diagnostic captures."""

from __future__ import annotations

import argparse
import sys
import threading

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QApplication, QLabel, QMainWindow, QMessageBox, QPushButton,
    QVBoxLayout, QHBoxLayout, QWidget,
)

from tyon_monitor import CaptureProgress, CaptureRequest, CaptureResult, run_capture
from tyon_widgets import apply_theme


def capture_status(result: CaptureResult) -> str:
    if result.cancelled:
        return "Capture stopped."
    if result.exit_code != 0:
        return f"Capture failed (exit code {result.exit_code})."
    return "Capture complete."


def format_summary(result: CaptureResult) -> str:
    """Return the concise, human-readable completion card shown by the window."""
    if result.cancelled:
        return "Capture stopped. No result summary was produced."
    if result.exit_code != 0:
        return f"{capture_status(result)}\nSaved: {result.output.resolve()}"
    if result.request.raw:
        data = result.summary
        low, high = data.get("raw_range", ("?", "?"))
        return (
            f"{data.get('reports', 0):,} raw reports · baseline {data.get('baseline', '?')} "
            f"(span {data.get('baseline_span', '?')}) · range {low}\N{EN DASH}{high}\n"
            f"Scroll events: {data.get('scroll_events', 0)} · "
            f"Unmatched reports: {data.get('unmatched', 0)}\n"
            f"Saved: {result.output.resolve()}"
        )
    data = result.summary
    return (
        f"{data.get('samples', 0):,} samples · scroll events: {data.get('scroll_events', 0)} · "
        f"largest axis: {data.get('primary_axis', '?')} (span {data.get('primary_span', '?')})\n"
        f"Saved: {result.output.resolve()}"
    )


class CaptureWorker(QObject):
    progress = Signal(object)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, request: CaptureRequest) -> None:
        super().__init__()
        self.request = request
        self.stop_event = threading.Event()

    @Slot()
    def run(self) -> None:
        try:
            self.completed.emit(run_capture(self.request, self.progress.emit, self.stop_event))
        except Exception as exc:
            self.failed.emit(str(exc))

    @Slot()
    def stop(self) -> None:
        self.stop_event.set()


class CaptureWindow(QMainWindow):
    def __init__(self, selected_trial: str = "paddle") -> None:
        super().__init__()
        self.setWindowTitle("Roccat Tyon — Capture")
        self.setMinimumWidth(560)
        self.setFixedHeight(360)
        self._thread: QThread | None = None
        self._worker: CaptureWorker | None = None
        self._close_when_finished = False

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(14)

        title = QLabel("X-Celerator diagnostic capture")
        title.setObjectName("h2")
        layout.addWidget(title)
        note = QLabel(
            "Choose a trial. After a 1-second warning, keep both controls untouched for "
            "2 seconds, then use only the selected control for 10 seconds."
        )
        note.setObjectName("note")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QHBoxLayout()
        self.paddle_button = QPushButton("Capture paddle")
        self.wheel_button = QPushButton("Capture wheel")
        for button in (self.paddle_button, self.wheel_button):
            button.setObjectName("primary")
            button.setMinimumHeight(46)
            buttons.addWidget(button)
        self.paddle_button.clicked.connect(lambda: self.start_capture("paddle"))
        self.wheel_button.clicked.connect(lambda: self.start_capture("wheel"))
        layout.addLayout(buttons)

        self.stop_button = QPushButton("Stop capture")
        self.stop_button.setObjectName("ghost")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_capture)
        layout.addWidget(self.stop_button)

        self.status = QLabel(
            "Paddle is selected." if selected_trial == "paddle" else "Wheel is selected."
        )
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.summary = QLabel("")
        self.summary.setObjectName("note")
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(self.summary.textInteractionFlags())
        layout.addWidget(self.summary)
        layout.addStretch(1)

        selected_button = self.paddle_button if selected_trial == "paddle" else self.wheel_button
        selected_button.setDefault(True)
        selected_button.setFocus()

    def start_capture(self, trial: str) -> None:
        if self._thread is not None:
            return
        request = CaptureRequest(trial)
        self.summary.clear()
        self.status.setText("Preparing capture…")
        self.paddle_button.setEnabled(False)
        self.wheel_button.setEnabled(False)
        self.stop_button.setEnabled(True)

        self._thread = QThread(self)
        self._worker = CaptureWorker(request)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.on_progress)
        self._worker.completed.connect(self.on_completed)
        self._worker.failed.connect(self.on_failed)
        self._worker.completed.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self.on_thread_finished)
        self._thread.start()

    @Slot(object)
    def on_progress(self, progress: CaptureProgress) -> None:
        self.status.setText(progress.message)

    @Slot()
    def stop_capture(self) -> None:
        if self._worker is not None:
            self._worker.stop()
            self.status.setText("Stopping capture and restoring normal device mode…")
            self.stop_button.setEnabled(False)

    @Slot(object)
    def on_completed(self, result: CaptureResult) -> None:
        self.status.setText(capture_status(result))
        self.summary.setText(format_summary(result))

    @Slot(str)
    def on_failed(self, message: str) -> None:
        self.status.setText("Capture failed.")
        self.summary.setText(message)
        QMessageBox.critical(self, "Tyon capture failed", message)

    @Slot()
    def on_thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self.paddle_button.setEnabled(True)
        self.wheel_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        if self._close_when_finished:
            self._close_when_finished = False
            self.close()

    def closeEvent(self, event) -> None:
        if self._thread is not None:
            self._close_when_finished = True
            self.stop_capture()
            event.ignore()
            return
        event.accept()


def main() -> int:
    parser = argparse.ArgumentParser(description="Open the compact Tyon capture window")
    parser.add_argument("--trial", choices=("paddle", "wheel"), default="paddle")
    args = parser.parse_args()
    app = QApplication(sys.argv)
    apply_theme(app)
    window = CaptureWindow(args.trial)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
