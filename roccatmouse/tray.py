"""On-demand Windows tray controller for continuous Tyon observation."""

from __future__ import annotations

import argparse
from pathlib import Path
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QSystemTrayIcon

from roccatmouse.config import load_config, save_config
from roccatmouse.diagnostics.observation import ObservationRuntime, ObservationStatus


class RuntimeSignals(QObject):
    started = Signal(object)
    stopped = Signal(object)
    failed = Signal(str)


class TrayController(QObject):
    def __init__(self, runtime: ObservationRuntime, *, show: bool = True) -> None:
        super().__init__()
        self.runtime = runtime
        self.signals = RuntimeSignals()
        self.signals.started.connect(self._on_started)
        self.signals.stopped.connect(self._on_stopped)
        self.signals.failed.connect(self._on_failed)
        self._busy = False
        self._capture_windows = []

        icon_path = Path(__file__).resolve().parents[1] / "tyon.ico"
        self.tray = QSystemTrayIcon(QIcon(str(icon_path)) if icon_path.exists() else QIcon(), self)
        self.tray.setToolTip("RoccatMouse — observation stopped")
        menu = QMenu()
        self.start_action = QAction("Start continuous observation", self)
        self.stop_action = QAction("Stop observation", self)
        self.marker_action = QAction("Mark symptom now", self)
        self.noted_marker_action = QAction("Mark symptom with note…", self)
        self.diagnostics_action = QAction("Open short capture proofs", self)
        self.quit_action = QAction("Exit RoccatMouse", self)
        self.start_action.triggered.connect(self.start_observation)
        self.stop_action.triggered.connect(self.stop_observation)
        self.marker_action.triggered.connect(self.mark_symptom)
        self.noted_marker_action.triggered.connect(self.mark_symptom_with_note)
        self.diagnostics_action.triggered.connect(self.open_diagnostics)
        self.quit_action.triggered.connect(self.quit)
        for action in (self.start_action, self.stop_action):
            menu.addAction(action)
        menu.addSeparator()
        menu.addAction(self.marker_action)
        menu.addAction(self.noted_marker_action)
        menu.addSeparator()
        menu.addAction(self.diagnostics_action)
        menu.addSeparator()
        menu.addAction(self.quit_action)
        self.tray.setContextMenu(menu)
        self._apply_status(runtime.status)
        if show:
            self.tray.show()

    @Slot()
    def start_observation(self) -> None:
        if self._busy or self.runtime.status.active:
            return
        self._set_busy(True)
        threading.Thread(target=self._start_worker, name="tray-start", daemon=True).start()

    @Slot()
    def stop_observation(self) -> None:
        if self._busy or not self.runtime.status.active:
            return
        self._set_busy(True)
        threading.Thread(target=self._stop_worker, name="tray-stop", daemon=True).start()

    @Slot()
    def mark_symptom(self) -> None:
        try:
            marker = self.runtime.mark_symptom()
        except Exception as exc:
            self._on_failed(str(exc))
            return
        self.tray.showMessage(
            "RoccatMouse",
            f"Symptom marker #{marker} saved with before/after context.",
            QSystemTrayIcon.Information,
            4000,
        )
        self._apply_status(self.runtime.status)

    @Slot()
    def mark_symptom_with_note(self) -> None:
        note, accepted = QInputDialog.getText(None, "Mark Tyon symptom", "What happened?")
        if not accepted:
            return
        try:
            marker = self.runtime.mark_symptom(note or "symptom")
        except Exception as exc:
            self._on_failed(str(exc))
            return
        self.tray.showMessage(
            "RoccatMouse",
            f"Symptom marker #{marker} saved.",
            QSystemTrayIcon.Information,
            4000,
        )
        self._apply_status(self.runtime.status)

    @Slot()
    def open_diagnostics(self) -> None:
        from tyon_capture_gui import CaptureWindow

        window = CaptureWindow("paddle_only")
        window.setAttribute(Qt.WA_DeleteOnClose, True)
        window.destroyed.connect(lambda: self._capture_windows.remove(window) if window in self._capture_windows else None)
        self._capture_windows.append(window)
        window.show()
        window.raise_()
        window.activateWindow()

    @Slot()
    def quit(self) -> None:
        try:
            self.runtime.close()
        finally:
            self.tray.hide()
            QApplication.quit()

    def _start_worker(self) -> None:
        try:
            self.signals.started.emit(self.runtime.start())
        except Exception as exc:
            self.signals.failed.emit(str(exc))

    def _stop_worker(self) -> None:
        try:
            self.signals.stopped.emit(self.runtime.stop())
        except Exception as exc:
            self.signals.failed.emit(str(exc))

    @Slot(object)
    def _on_started(self, status: ObservationStatus) -> None:
        self._set_busy(False)
        self._apply_status(status)
        self.tray.showMessage("RoccatMouse", "Continuous observation started.")

    @Slot(object)
    def _on_stopped(self, status: ObservationStatus) -> None:
        self._set_busy(False)
        self._apply_status(status)
        self.tray.showMessage("RoccatMouse", "Observation stopped and drained cleanly.")

    @Slot(str)
    def _on_failed(self, error: str) -> None:
        self._set_busy(False)
        self._apply_status(self.runtime.status)
        self.tray.showMessage("RoccatMouse error", error, QSystemTrayIcon.Critical, 8000)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._apply_status(self.runtime.status)

    def _apply_status(self, status: ObservationStatus) -> None:
        active = status.active
        self.start_action.setEnabled(not active and not self._busy)
        self.stop_action.setEnabled(active and not self._busy)
        self.marker_action.setEnabled(active and not self._busy)
        self.noted_marker_action.setEnabled(active and not self._busy)
        state = "running" if active else "stopped"
        if status.error:
            state = f"error: {status.error}"
        self.tray.setToolTip(f"RoccatMouse — observation {state}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the RoccatMouse observation tray")
    parser.add_argument(
        "--start",
        action="store_true",
        help="start continuous observation immediately after the tray opens",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = load_config()
    save_config(config)
    runtime = ObservationRuntime.windows_default(config)
    controller = TrayController(runtime)
    app.setProperty("roccatmouse_tray_controller", controller)
    if args.start:
        QTimer.singleShot(0, controller.start_observation)
    return app.exec()
