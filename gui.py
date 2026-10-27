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
from PySide6.QtGui import (
    QColor, QDesktopServices, QFont, QIcon, QPalette, QPixmap,
)
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
LOGO_SVG = os.path.join(APP_DIR, "resources", "logo.svg")


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
        self.setMinimumSize(560, 460)
        self.resize(820, 860)
        if os.path.isfile(LOGO_SVG):
            self.setWindowIcon(QIcon(LOGO_SVG))

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- Docker-style top app bar ----
        outer.addWidget(self._build_appbar())

        # Scrollable body — stays usable at any window size (scrollbar appears
        # instead of widgets overlapping when the window is short).
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll, stretch=1)

        root = QWidget()
        scroll.setWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(16)

        intro = QLabel(
            "Compile a Python strategy into a protected native module (.pyd / .so)."
        )
        intro.setObjectName("subtitle")
        intro.setWordWrap(True)
        layout.addWidget(intro)

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
    def _build_appbar(self):
        bar = QFrame()
        bar.setObjectName("appbar")
        bar.setFixedHeight(62)
        h = QHBoxLayout(bar)
        h.setContentsMargins(22, 0, 22, 0)
        h.setSpacing(12)

        logo = QLabel()
        if os.path.isfile(LOGO_SVG):
            pix = QPixmap(LOGO_SVG)
            if not pix.isNull():
                logo.setPixmap(pix.scaled(
                    30, 30, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        h.addWidget(logo)

        name = QLabel("Strategy Encryptor")
        name.setObjectName("appTitle")
        h.addWidget(name)
        h.addStretch(1)

        tag = QLabel("Finesse")
        tag.setObjectName("appTag")
        h.addWidget(tag)
        return bar

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
* { font-family: "Roboto", "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif; }
QMainWindow, QWidget { background: #16181d; color: #e9ecf1; }

QFrame#appbar { background: #1e2127; border: none; border-bottom: 1px solid #2b2f36; }
#appTitle { font-size: 16px; font-weight: 700; color: #f4f5f7; }
#appTag { font-size: 12px; font-weight: 600; color: #6e7784; }

#subtitle { font-size: 13px; color: #9ba4b2; }
#fieldLabel { font-size: 12px; font-weight: 600; color: #aab2bf; margin-top: 2px; }

QLineEdit {
    background: #22262d; border: 1px solid #343a43; border-radius: 6px;
    padding: 10px 12px; font-size: 13px; color: #e9ecf1;
    selection-background-color: #1d63ed; selection-color: #ffffff;
}
QLineEdit:focus { border: 1px solid #1d63ed; background: #262b33; }
QLineEdit:read-only { color: #c7ced9; }

QPushButton {
    background: #262b33; border: 1px solid #3a414b; border-radius: 6px;
    padding: 9px 16px; font-size: 13px; font-weight: 600; color: #dfe3ea;
}
QPushButton:hover { background: #2d333c; border-color: #454d59; }
QPushButton:pressed { background: #20252c; }
QPushButton:disabled { color: #5c6470; background: #1c2026; border-color: #2a2f37; }

QPushButton#primary {
    background: #1d63ed; border: none; color: #ffffff;
    padding: 12px 18px; font-size: 14px; font-weight: 700;
}
QPushButton#primary:hover { background: #3b7bf0; }
QPushButton#primary:pressed { background: #1551c4; }
QPushButton#primary:disabled { background: #27385f; color: #93a6cf; }

QScrollArea { background: #16181d; border: none; }
QFrame#card { background: #1e2127; border: 1px solid #2b2f36; border-radius: 8px; }
#cardHeader { font-size: 12px; font-weight: 700; color: #aab2bf; }

QCheckBox { font-size: 13px; font-weight: 500; spacing: 10px; padding: 4px 0;
    color: #dfe3ea; min-height: 24px; }
QCheckBox:disabled { color: #5c6470; }
QCheckBox::indicator { width: 20px; height: 20px; border-radius: 4px;
    border: 1px solid #3f4650; background: #22262d; }
QCheckBox::indicator:hover { border: 1px solid #1d63ed; }
QCheckBox::indicator:checked { background: #1d63ed; border: 1px solid #1d63ed;
    image: url("__CHECK_URL__"); }
QCheckBox::indicator:disabled { background: #1c2026; border: 1px solid #2a2f37; }

QPlainTextEdit#log {
    background: #0e1013; color: #c3cad8; border: 1px solid #262b33;
    border-radius: 8px; padding: 10px;
}
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #353b45; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #434a56; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QStatusBar { background: #1e2127; color: #9ba4b2; font-size: 12px;
    border-top: 1px solid #2b2f36; }
QToolTip { background: #22262d; color: #e9ecf1; border: 1px solid #343a43;
    padding: 4px 6px; }
"""


def _apply_dark_palette(app):
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor("#16181d"))
    pal.setColor(QPalette.WindowText, QColor("#e9ecf1"))
    pal.setColor(QPalette.Base, QColor("#22262d"))
    pal.setColor(QPalette.AlternateBase, QColor("#1e2127"))
    pal.setColor(QPalette.Text, QColor("#e9ecf1"))
    pal.setColor(QPalette.Button, QColor("#262b33"))
    pal.setColor(QPalette.ButtonText, QColor("#e9ecf1"))
    pal.setColor(QPalette.Highlight, QColor("#1d63ed"))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor("#22262d"))
    pal.setColor(QPalette.ToolTipText, QColor("#e9ecf1"))
    pal.setColor(QPalette.PlaceholderText, QColor("#6e7784"))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor("#5c6470"))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#5c6470"))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#5c6470"))
    app.setPalette(pal)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Strategy Encryptor")
    app.setOrganizationName("FinesseBroking")
    if os.path.isfile(LOGO_SVG):
        app.setWindowIcon(QIcon(LOGO_SVG))
    app.setStyle("Fusion")
    _apply_dark_palette(app)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
