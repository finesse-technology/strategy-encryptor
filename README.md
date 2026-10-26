# Compile a `.py` into `.pyd` / `.so`

Replace a readable `strategy.py` with a compiled version that works the same
(`import strategy`) but whose logic **cannot be read** from the file.

- `.pyd` = Windows, `.so` = Linux. Both are machine code (like a compiled C
  program): no readable source, no bytecode to decompile.
- You cannot get the `.py` back, so **keep your original `.py` safe**.
- Text strings inside (messages, keys) can still be extracted — only the
  *logic* is protected.

You always just give the **absolute path** of the `.py` file. No mounting.

> **No Microsoft C++ Build Tools required.** The Windows build uses a small C
> compiler (TCC) bundled in this repo under `vendor/tcc-win64/`. See
> [docs/compilation.md](docs/compilation.md) for how it works and why.

---

## Desktop app (GUI)

The easiest way to use the tool. Everything runs from the project's `.venv`.

**One-time setup:**
```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```
(Linux / macOS: `python3 -m venv .venv` then `.venv/bin/python -m pip install -r requirements.txt`.)

**Launch:**
- **Windows:** double-click `launcher\run.bat`
- **Linux / macOS:** `./launcher/run.sh`  (first time only: `chmod +x launcher/run.sh`)

In the window: pick the `.py` file, enter a **strategy name**, optionally choose
an **output folder**, tick the build targets, and click **Compile**.

- If you **choose a folder**, files go to `<that folder>/output/<name>.pyd` / `.so`.
- If you **leave it empty**, files go to the default
  `<strategy-encryptor>\output\<name>\<name>.pyd` / `.so`.

Every build is also written to a timestamped file in the `logs\` folder
(`logs\<timestamp>_<name>.log`), so the full output is kept even after you close
the window.

- **Windows host** builds both `.pyd` and `.so` (the `.so` needs Docker Desktop).
- **Linux / macOS host** builds only the `.so` — a Windows `.pyd` can't be made
  off Windows, so that checkbox is disabled.

Prefer the command line? Use `convert.py` directly, as below.

---

## Setup (once)

**Windows `.pyd`** (default — no Build Tools):
```powershell
python -m pip install cython
```
That's it. The compiler ships with this repo.

**Linux `.so`:** install **Docker Desktop** and make sure it's running.

---

## Make the Windows `.pyd`

```powershell
python convert.py --input C:\finesse\nexus\src\core\strategy\strategies\sm20\strategy.py
```
Result: `output\strategy.cp312-win_amd64.pyd`

This uses the bundled TCC compiler by default (`--backend tcc`). If it fails on
an unusual strategy (e.g. one using Cython `cimport` / C-level extensions), fall
back to the system Microsoft compiler — see
[Fallback: VS Build Tools](#fallback-vs-build-tools) below.

## Make the Linux `.so`

Same command, add `--linux`. It builds and runs Docker for you.
```powershell
python convert.py --input C:\finesse\nexus\src\core\strategy\strategies\sm20\strategy.py --linux
```
Result: `output\strategy.cpython-312-x86_64-linux-gnu.so`

Both land in the `output` folder next to `convert.py`. Use `--output <folder>`
to change that, and `--name <module_name>` to set the compiled module's import
name (otherwise the input file name is used).

---

## Use it

Put **only** the compiled file (not the `.py`) where your program runs, then:
```python
import strategy
```

---

## Fallback: VS Build Tools

The default TCC backend handles ordinary `.py` strategies. If a build fails and
the error mentions C-level dependencies, use the system Microsoft compiler
instead:

1. Install **Microsoft C++ Build Tools** (tick "Desktop development with C++"):
   https://visualstudio.microsoft.com/visual-cpp-build-tools/
2. `python -m pip install cython setuptools`
3. Build with the `setuptools` backend:
   ```powershell
   python convert.py --input <path to strategy.py> --backend setuptools
   ```

Full explanation and troubleshooting: [docs/compilation.md](docs/compilation.md).

---

## ⚠️ Python version MUST match

A compiled module is locked to the Python version it was built with — you can
see it in the file name:

```
strategy.cp312-win_amd64.pyd            <- cp312  = Python 3.12
strategy.cpython-312-x86_64-linux-gnu.so <- 312   = Python 3.12
```

It will **only import on the same Python version**. A file built for Python 3.12
will NOT load in Python 3.11 or 3.13 — Python just ignores it and acts as if the
module isn't there.

So the Python used to RUN the module must match the Python used to BUILD it:
- **Windows `.pyd`:** build with the same Python version your program runs on.
  (Check yours with `python --version`.) The tool auto-detects whichever Python
  you run it with and builds for that version.
- **Linux `.so`:** this project builds with Python **3.12** (set in the
  `Dockerfile`: `python:3.12.10-slim-bookworm`). Your Linux machine/server must
  also run Python 3.12. To target a different version, change that line in the
  `Dockerfile` (e.g. `python:3.11-slim-bookworm`) and rebuild.

The OS and CPU must match too (Windows vs Linux, 64-bit). For any different
Python version, OS, or architecture, just compile again in that environment.
