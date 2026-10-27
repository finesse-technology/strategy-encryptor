"""
Strategy Encryptor — desktop GUI.

Select a .py strategy, give it a name and an output folder, and compile it into
a protected native module:
  - Windows host: builds both the Windows .pyd and the Linux .so (Docker).
  - Linux / macOS host: builds only the .so (a .pyd can't be produced off Windows).

Files are written to  <output folder>/output/<name>.<ext>.

The actual compilation is delegated to convert.py, so the GUI stays a thin,
testable shell over the already-verified build pipeline.
"""

import datetime
import os
import subprocess
import sys

from PySide6.QtCore import Qt, QThread, Signal, QUrl, QSettings
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

IS_WINDOWS = sys.platform.startswith("win")
APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONVERT_PY = os.path.join(APP_DIR, "convert.py")
LOGS_DIR = os.path.join(APP_DIR, "logs")
CHECK_SVG = os.path.join(APP_DIR, "resources", "check.svg")


# ---------------------------------------------------------------------------
# Build worker — runs convert.py jobs off the UI thread.
# ---------------------------------------------------------------------------

class BuildWorker(QThread):
    log = Signal(str)
    job_done = Signal(str, bool)   # label, success
    all_done = Signal()

    def __init__(self, jobs):
        super().__init__()
        self.jobs = jobs           # list of (label, [extra args])

    def run(self):
        for label, args in self.jobs:
            self.log.emit(f"\n======== Building {label} ========")
            cmd = [sys.executable, CONVERT_PY] + args
            self.log.emit("$ " + " ".join(cmd))
            ok = False
            try:
                flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
                proc = subprocess.Popen(
                    cmd, cwd=APP_DIR,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, creationflags=flags,
                )
                for line in proc.stdout:
                    self.log.emit(line.rstrip("\n"))
                proc.wait()
                ok = proc.returncode == 0
            except Exception as exc:  # noqa: BLE001
                self.log.emit(f"ERROR launching build: {exc}")
            self.job_done.emit(label, ok)
        self.all_done.emit()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker = None
        self._results = {}
        self._out_dir = ""
        self._log_file = None
        self._log_path = ""
        self.settings = QSettings("FinesseBroking", "StrategyEncryptor")

        self.setWindowTitle("Strategy Encryptor")
        self.setMinimumSize(520, 420)
        self.resize(760, 800)

        # Everything lives inside a scroll area so the UI stays fully usable at
        # any window size — if it gets too short, a scrollbar appears instead of
        # widgets overlapping.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setCentralWidget(scroll)

        root = QWidget()
        scroll.setWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(16)

        # ---- Header ----
        title = QLabel("Strategy Encryptor")
        title.setObjectName("title")
        subtitle = QLabel(
            "Compile a Python strategy into a protected native module "
            "(.pyd / .so)."
        )
        subtitle.setObjectName("subtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self._hline())

        # ---- Input file ----
        layout.addWidget(self._field_label("Strategy file  (.py)"))
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Select the .py file to compile…")
        self.input_edit.setReadOnly(True)
        browse_in = QPushButton("Browse…")
        browse_in.clicked.connect(self._pick_input)
        layout.addLayout(self._row(self.input_edit, browse_in))

        # ---- Strategy name ----
        layout.addWidget(self._field_label("Strategy name  (output folder name)"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. ladder  — names the output folder only")
        layout.addWidget(self.name_edit)

        # ---- Output folder ----
        layout.addWidget(self._field_label("Output folder  (optional)"))
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText(
            "Leave empty to use  <strategy-encryptor>\\output\\<name>  …"
        )
        self.out_edit.setReadOnly(True)
        browse_out = QPushButton("Browse…")
        browse_out.clicked.connect(self._pick_output)
        layout.addLayout(self._row(self.out_edit, browse_out))

        targets = QFrame()
        targets.setObjectName("card")
        tlay = QVBoxLayout(targets)
        tlay.setContentsMargins(16, 14, 16, 16)
        tlay.setSpacing(10)
        targets_header = QLabel("Build targets")
        targets_header.setObjectName("cardHeader")
        tlay.addWidget(targets_header)
        self.chk_pyd = QCheckBox("Windows module  (.pyd)")
        self.chk_so = QCheckBox("Linux module  (.so, via Docker)")
        self.chk_pyd.setChecked(True)
        self.chk_so.setChecked(True)
        if not IS_WINDOWS:
            self.chk_pyd.setChecked(False)
            self.chk_pyd.setEnabled(False)
            self.chk_pyd.setText("Windows module  (.pyd) — Windows only")
        tlay.addWidget(self.chk_pyd)
        tlay.addWidget(self.chk_so)
        layout.addWidget(targets)

        # ---- Build button ----
        self.build_btn = QPushButton("Compile")
        self.build_btn.setObjectName("primary")
        self.build_btn.clicked.connect(self._start_build)
        layout.addWidget(self.build_btn)

        # ---- Log ----
        layout.addWidget(self._field_label("Log"))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setObjectName("log")
        self.log_view.setFont(QFont("Consolas" if IS_WINDOWS else "Monospace", 9))
        self.log_view.setMinimumHeight(140)
        layout.addWidget(self.log_view, stretch=1)

        self.open_btn = QPushButton("Open output folder")
        self.open_btn.clicked.connect(self._open_output)
        self.open_btn.setEnabled(False)
        layout.addWidget(self.open_btn, alignment=Qt.AlignRight)

        env = f"Python {sys.version_info.major}.{sys.version_info.minor} · {sys.platform}"
        self.statusBar().showMessage(f"Ready — builds target {env}")

        check_url = CHECK_SVG.replace("\\", "/") if os.path.isfile(CHECK_SVG) else ""
        self.setStyleSheet(STYLESHEET.replace("__CHECK_URL__", check_url))

    # ---- small UI helpers ----
    def _hline(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setObjectName("hline")
        return line

    def _field_label(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("fieldLabel")
        return lbl

    def _row(self, widget, button):
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(widget, stretch=1)
        row.addWidget(button)
        return row

    # ---- actions ----
    def _pick_input(self):
        start = self.settings.value("last_input_dir", "", str)
        path, _ = QFileDialog.getOpenFileName(
            self, "Select strategy .py file", start, "Python files (*.py)"
        )
        if path:
            self.input_edit.setText(path)
            self.settings.setValue("last_input_dir", os.path.dirname(path))
            if not self.name_edit.text().strip():
                stem = os.path.splitext(os.path.basename(path))[0]
                self.name_edit.setText(stem)

    def _pick_output(self):
        start = self.settings.value("last_output_dir", "", str)
        path = QFileDialog.getExistingDirectory(self, "Select output folder", start)
        if path:
            self.out_edit.setText(path)
            self.settings.setValue("last_output_dir", path)

    def _start_build(self):
        in_path = self.input_edit.text().strip()
        name = self.name_edit.text().strip()
        out_base = self.out_edit.text().strip()

        if not in_path or not os.path.isfile(in_path):
            return self._warn("Please select a valid .py file.")
        if not name:
            return self._warn("Please enter a strategy name (used as the folder name).")
        bad = set('<>:"/\\|?*')
        if any(c in bad for c in name):
            return self._warn(
                "The strategy name is used as a folder name, so it can't contain "
                'any of:  < > : " / \\ | ? *'
            )
        if out_base and not os.path.isdir(out_base):
            return self._warn("The selected output folder does not exist.")
        if not self.chk_pyd.isChecked() and not self.chk_so.isChecked():
            return self._warn("Select at least one build target.")

        base = out_base if out_base else os.path.join(APP_DIR, "output")
        self._out_dir = os.path.join(base, name)
        common = ["--input", in_path, "--output", self._out_dir]

        jobs = []
        if self.chk_pyd.isChecked():
            jobs.append((".pyd (Windows)", list(common)))
        if self.chk_so.isChecked():
            jobs.append((".so (Linux / Docker)", list(common) + ["--linux"]))

        self._results = {}
        self.log_view.clear()
        self._open_log_file(name)
        self._log(f"Output folder: {self._out_dir}")
        self._set_running(True)

        self.worker = BuildWorker(jobs)
        self.worker.log.connect(self._log)
        self.worker.job_done.connect(self._on_job_done)
        self.worker.all_done.connect(self._on_all_done)
        self.worker.start()

    def _on_job_done(self, label, ok):
        self._results[label] = ok
        self._log(f"---- {label}: {'SUCCESS' if ok else 'FAILED'} ----")

    def _on_all_done(self):
        self._set_running(False)
        ok = sum(1 for v in self._results.values() if v)
        total = len(self._results)
        if self._log_path:
            self._log(f"\nLog saved to: {self._log_path}")
        self._close_log_file()
        self.open_btn.setEnabled(os.path.isdir(self._out_dir))
        if ok == total:
            self.statusBar().showMessage(f"Done — {ok}/{total} target(s) built.")
            self._info(f"Compiled {ok}/{total} target(s) into:\n{self._out_dir}")
        else:
            self.statusBar().showMessage(f"Finished with errors — {ok}/{total} built.")
            failed = ", ".join(k for k, v in self._results.items() if not v)
            self._warn(f"{ok}/{total} target(s) built.\nFailed: {failed}\n\n"
                       "See the log for details.")

    def _open_output(self):
        if os.path.isdir(self._out_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._out_dir))

    def _set_running(self, running):
        self.build_btn.setEnabled(not running)
        self.build_btn.setText("Compiling…" if running else "Compile")
        for w in (self.chk_pyd, self.chk_so):
            w.setEnabled(not running and (w is not self.chk_pyd or IS_WINDOWS))
        if running:
            self.statusBar().showMessage("Compiling…")

    def _open_log_file(self, name):
        try:
            os.makedirs(LOGS_DIR, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            self._log_path = os.path.join(LOGS_DIR, f"{stamp}_{name}.log")
            self._log_file = open(self._log_path, "w", encoding="utf-8")
            self._log_file.write(
                f"Strategy Encryptor build log — {name} — "
                f"{datetime.datetime.now().isoformat(timespec='seconds')}\n"
            )
        except OSError as exc:
            self._log_file = None
            self._log_path = ""
            self.log_view.appendPlainText(f"(could not open log file: {exc})")

    def _close_log_file(self):
        if self._log_file:
            try:
                self._log_file.flush()
                self._log_file.close()
            except OSError:
                pass
            self._log_file = None

    def _log(self, text):
        self.log_view.appendPlainText(text)
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum()
        )
        if self._log_file:
            try:
                self._log_file.write(text + "\n")
                self._log_file.flush()
            except OSError:
                pass

    def _warn(self, text):
        QMessageBox.warning(self, "Strategy Encryptor", text)

    def _info(self, text):
        QMessageBox.information(self, "Strategy Encryptor", text)


STYLESHEET = """
* { font-family: "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif; }
QMainWindow, QWidget { background: #0f1218; color: #e6e9ef; }
#title { font-size: 22px; font-weight: 700; color: #f3f5f9; }
#subtitle { font-size: 13px; color: #8b93a7; }
#hline { background: #232a35; max-height: 1px; border: none; }
#fieldLabel { font-size: 12px; font-weight: 600; color: #9aa3b7; margin-top: 2px; }
QLineEdit {
    background: #171b22; border: 1px solid #2a313d; border-radius: 8px;
    padding: 10px 12px; font-size: 13px; color: #e6e9ef;
    selection-background-color: #6366f1; selection-color: #ffffff;
}
QLineEdit:focus { border: 1px solid #6366f1; background: #1a1f28; }
QLineEdit:read-only { color: #c9d0dd; }
QPushButton {
    background: #20262f; border: 1px solid #323a47; border-radius: 8px;
    padding: 9px 16px; font-size: 13px; font-weight: 600; color: #d9dee8;
}
QPushButton:hover { background: #28303b; border-color: #3c4557; }
QPushButton:pressed { background: #1b212a; }
QPushButton:disabled { color: #5a6270; background: #171b22; border-color: #242b35; }
QPushButton#primary {
    background: #6366f1; border: none; color: #ffffff;
    padding: 12px 16px; font-size: 14px; font-weight: 700;
}
QPushButton#primary:hover { background: #7579f5; }
QPushButton#primary:pressed { background: #4f46e5; }
QPushButton#primary:disabled { background: #343862; color: #9aa0cf; }
QScrollArea { background: #0f1218; border: none; }
QFrame#card { background: #141821; border: 1px solid #262d39; border-radius: 10px; }
#cardHeader { font-size: 12px; font-weight: 600; color: #9aa3b7; }
QCheckBox { font-size: 13px; font-weight: 500; spacing: 10px; padding: 4px 0;
    color: #dce1ea; min-height: 24px; }
QCheckBox:disabled { color: #5a6270; }
QCheckBox::indicator { width: 20px; height: 20px; border-radius: 5px;
    border: 1px solid #3a4250; background: #1b2028; }
QCheckBox::indicator:hover { border: 1px solid #6366f1; }
QCheckBox::indicator:checked { background: #6366f1; border: 1px solid #6366f1;
    image: url("__CHECK_URL__"); }
QCheckBox::indicator:disabled { background: #1a1e26; border: 1px solid #2a313d; }
QPlainTextEdit#log {
    background: #0a0d12; color: #c3cad8; border: 1px solid #20262f;
    border-radius: 10px; padding: 10px;
}
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #333b48; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #3f4857; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QStatusBar { color: #8b93a7; font-size: 12px; }
QToolTip { background: #1a1e26; color: #e6e9ef; border: 1px solid #2a313d;
    padding: 4px 6px; }
"""


def _apply_dark_palette(app):
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor("#0f1218"))
    pal.setColor(QPalette.WindowText, QColor("#e6e9ef"))
    pal.setColor(QPalette.Base, QColor("#171b22"))
    pal.setColor(QPalette.AlternateBase, QColor("#141821"))
    pal.setColor(QPalette.Text, QColor("#e6e9ef"))
    pal.setColor(QPalette.Button, QColor("#20262f"))
    pal.setColor(QPalette.ButtonText, QColor("#e6e9ef"))
    pal.setColor(QPalette.Highlight, QColor("#6366f1"))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor("#1a1e26"))
    pal.setColor(QPalette.ToolTipText, QColor("#e6e9ef"))
    pal.setColor(QPalette.PlaceholderText, QColor("#6b7280"))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor("#5a6270"))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#5a6270"))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#5a6270"))
    app.setPalette(pal)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Strategy Encryptor")
    app.setOrganizationName("FinesseBroking")
    app.setStyle("Fusion")
    _apply_dark_palette(app)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
