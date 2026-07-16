# SPDX-License-Identifier: MIT
"""Small, dedicated launcher for Tyon paddle and wheel diagnostic captures."""

from __future__ import annotations

import argparse
import queue
import sys
import threading

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QApplication, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
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
        issues = result.summary.get("acceptance_issues", [])
        detail = ""
        if issues:
            detail = "\n" + "\n".join(f"• {issue}" for issue in issues)
        return f"{capture_status(result)}{detail}\nSaved: {result.output.resolve()}"
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
        f"Input source: {data.get('input_source', '?')} · "
        f"clean shutdown: {data.get('clean_shutdown', False)}\n"
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
        self.marker_queue: queue.SimpleQueue[str] = queue.SimpleQueue()

    @Slot()
    def run(self) -> None:
        try:
            self.completed.emit(
                run_capture(
                    self.request,
                    self.progress.emit,
                    self.stop_event,
                    self.marker_queue,
                )
            )
        except Exception as exc:
            self.failed.emit(str(exc))

    @Slot()
    def stop(self) -> None:
        self.stop_event.set()

    def mark_symptom(self, note: str) -> None:
        self.marker_queue.put(note or "symptom")


class CaptureWindow(QMainWindow):
    def __init__(self, selected_trial: str = "paddle") -> None:
        super().__init__()
        self.setWindowTitle("Roccat Tyon — Capture")
        self.setMinimumWidth(560)
        self.setFixedHeight(470)
        self._thread: QThread | None = None
        self._worker: CaptureWorker | None = None
        self._close_when_finished = False
        self._active_request: CaptureRequest | None = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(14)

        title = QLabel("X-Celerator diagnostic capture")
        title.setObjectName("h2")
        layout.addWidget(title)
        note = QLabel(
            "This short proof window answers whether RoccatMouse can capture the paddle. "
            "Direct sensor temporarily reads its analog value; normal output records the "
            "scroll events Windows receives. It is not the continuous symptom logger."
        )
        note.setObjectName("note")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QHBoxLayout()
        self.paddle_button = QPushButton("1. Direct paddle sensor")
        self.normal_paddle_button = QPushButton("2. Normal paddle output")
        self.wheel_button = QPushButton("Wheel comparison")
        self.paddle_button.setToolTip(
            "Temporary raw mode: records the paddle's direct 0–255 analog sensor value."
        )
        self.normal_paddle_button.setToolTip(
            "Normal mode: records Tyon wheel events after the active profile mapping."
        )
        self.wheel_button.setToolTip(
            "Normal mode: records the physical wheel as a comparison signal."
        )
        for button in (self.paddle_button, self.normal_paddle_button, self.wheel_button):
            button.setObjectName("primary")
            button.setMinimumHeight(46)
            buttons.addWidget(button)
        self.paddle_button.clicked.connect(lambda: self.start_capture("paddle"))
        self.normal_paddle_button.clicked.connect(lambda: self.start_capture("paddle_only"))
        self.wheel_button.clicked.connect(lambda: self.start_capture("wheel_only"))
        layout.addLayout(buttons)

        self.stop_button = QPushButton("Stop capture")
        self.stop_button.setObjectName("ghost")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_capture)
        layout.addWidget(self.stop_button)

        marker_row = QHBoxLayout()
        self.marker_note = QLineEdit()
        self.marker_note.setPlaceholderText("Optional note for this short run")
        self.marker_button = QPushButton("Mark moment in this run")
        self.marker_button.setObjectName("ghost")
        self.marker_button.setEnabled(False)
        self.marker_button.clicked.connect(self.mark_symptom)
        marker_row.addWidget(self.marker_note, 1)
        marker_row.addWidget(self.marker_button)
        layout.addLayout(marker_row)

        self.status = QLabel(
            "Raw paddle sensor is selected."
            if selected_trial == "paddle"
            else "Normal Windows-output trial is selected."
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

        selected_button = {
            "paddle": self.paddle_button,
            "paddle_only": self.normal_paddle_button,
            "wheel": self.wheel_button,
            "wheel_only": self.wheel_button,
        }.get(selected_trial, self.paddle_button)
        selected_button.setDefault(True)
        selected_button.setFocus()

    def start_capture(self, trial: str) -> None:
        if self._thread is not None:
            return
        request = CaptureRequest(trial)
        self._active_request = request
        self.summary.clear()
        self.status.setText("Preparing capture…")
        self.paddle_button.setEnabled(False)
        self.normal_paddle_button.setEnabled(False)
        self.wheel_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.marker_button.setEnabled(not request.raw)

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

    @Slot()
    def mark_symptom(self) -> None:
        if self._worker is None or self._active_request is None or self._active_request.raw:
            return
        note = self.marker_note.text().strip() or "symptom"
        self._worker.mark_symptom(note)
        self.marker_note.clear()
        self.summary.setText(f"Symptom marker recorded: {note}")

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
        self._active_request = None
        self.paddle_button.setEnabled(True)
        self.normal_paddle_button.setEnabled(True)
        self.wheel_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.marker_button.setEnabled(False)
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
    parser.add_argument(
        "--trial",
        choices=("paddle", "wheel", "paddle_only", "wheel_only"),
        default="paddle",
    )
    args = parser.parse_args()
    app = QApplication(sys.argv)
    apply_theme(app)
    window = CaptureWindow(args.trial)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
