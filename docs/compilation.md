# How the strategy encryptor compiles `.py` → `.pyd` / `.so`

This document explains what `convert.py` does under the hood, **why** a C
compiler is bundled, how to fall back to Microsoft's compiler if a build fails,
and where the bundled compiler came from.

If you just want to run it, see the [README](../README.md). This is the "why and
how" for maintainers.

---

## 1. What problem this solves

To hide a strategy's logic we compile the `.py` into a native binary
(`.pyd` on Windows, `.so` on Linux). That binary is machine code — there is no
readable source and no bytecode to decompile.

Producing that binary normally requires a **C compiler** on the machine doing the
build. On Windows that traditionally means **Microsoft C++ Build Tools** — a
multi-gigabyte install every developer would otherwise need. The goal of this
tool is to make the Windows build work **without anyone installing Build Tools.**

---

## 2. The pipeline

Compiling `.py → .pyd` is really **two separate steps**, and only the second one
needs a C compiler:

```
strategy.py  ──►  strategy.c  ──►  strategy.pyd
             (1)              (2)

(1) Cython "transpile"   : pure Python, NO compiler needed
(2) C compiler           : THIS is the step that used to need Build Tools
```

So instead of removing the compiler, we **replace** the heavy one (MSVC) with a
tiny one we can legally ship: **TCC (Tiny C Compiler, ~1.6 MB)**, vendored in
this repo at `vendor/tcc-win64/`.

### What `convert.py` actually runs (TCC backend)

1. **`.py → .c`** — `python -m cython strategy.py -3 -X annotation_typing=False -o strategy.c`
   Pure Python. No compiler involved.
2. **Build a Python import library** — `tcc -impdef python312.dll -o python312.def`
   TCC cannot read Microsoft-format `.lib` files, so it generates its own link
   definition directly from the running interpreter's `pythonXY.dll`.
3. **`.c → .pyd`** — `tcc -shared strategy.c -o strategy.<tag>.pyd -I<python include> -L<tmp> -lpython312 -DCYTHON_USE_PYLONG_INTERNALS=0`

Steps 2 and 3 use only files that ship in `vendor/tcc-win64/` plus the headers
from the developer's own Python install (see §5).

---

## 3. Why TCC, and why it's committed to the repo

- **MSVC can't be bundled.** Microsoft's Build Tools are large and not
  redistributable inside a repo. TCC is tiny and freely redistributable (LGPL).
- **It travels with the tool.** Because the compiler is in the repo, a developer
  needs only Python + `pip install cython`. Nothing else to install.
- **It produces a real, importable `.pyd`** — verified end to end against a
  sample strategy (class, methods, module globals) that imported and ran with the
  source `.py` deleted.

### Why the whole `vendor/tcc-win64/` folder is required (not just `tcc.exe`)

`tcc.exe` alone will **not** compile. It needs its support files:

| Folder / file | Why it's needed |
|---|---|
| `tcc.exe` | the compiler driver |
| `lib/libtcc1-64.a` | TCC's own link-time runtime (required to link any binary) |
| `lib/kernel32.def`, `lib/msvcrt.def`, … | import defs every Windows `.pyd` links against |
| `include/*.h` | TCC's bundled C headers |

This matters for `.gitignore`: the standard Python `.gitignore` contains a
generic `lib/` rule that would hide `vendor/tcc-win64/lib/`. This repo re-includes
it explicitly:

```gitignore
# --- Bundled TCC compiler ---
!vendor/tcc-win64/lib/
!vendor/tcc-win64/**
```

If someone clones the repo and TCC fails to link, the first thing to check is
whether `vendor/tcc-win64/lib/` actually made it into the checkout.

---

## 4. The two non-obvious flags (don't remove them)

Plain TCC fails on Cython-generated C in two ways. Both are worked around in
`convert.py`:

1. **`-DCYTHON_USE_PYLONG_INTERNALS=0`**
   TCC mis-evaluates `sizeof()` inside an `enum` constant, which trips a Cython
   static assertion (`error: division by zero in constant`). This flag disables
   Cython's integer fast path, so that code is never generated. Results are
   correct; integer math is marginally slower.

2. **The `tcc -impdef` step**
   Without it, linking fails with `library 'python312' not found`, because TCC
   can't parse MSVC's `.lib`. Generating a `.def` from the Python DLL gives TCC
   something it can link against.

---

## 5. How it adapts to your Python (auto-discovery)

The tool does not hard-code any paths. For whatever Python interpreter you run
it with, it discovers:

- **Headers** — `sysconfig.get_path("include")`
- **The Python DLL** — searches near `sys.base_prefix` / `sys.executable` for
  `python<major><minor>.dll`
- **Output name** — `sysconfig.get_config_var("EXT_SUFFIX")`, e.g.
  `strategy.cp312-win_amd64.pyd`

**Consequence:** the `.pyd` is built for *exactly* the Python you ran the
converter with. Run it under Python 3.14 → the output only imports in Python
3.14. To support multiple Python versions, run the converter once under each.
See the README's "Python version MUST match" section.

> Note: very new Python releases can occasionally emit C that TCC (v0.9.27, from
> 2017) doesn't accept. If a brand-new Python version fails to compile, use the
> Build Tools fallback below.

---

## 6. Fallback: Microsoft C++ Build Tools

The TCC backend handles ordinary `.py` strategies. It can fail on a strategy that
pulls in **C-level dependencies** — for example Cython `cimport`, or `.pyx`-style
C features. The error looks like:

```
ERROR: TCC compile (.c -> .pyd) failed.
This can happen if the strategy uses C-level deps (e.g. 'cimport').
```

When that happens, build with the system Microsoft compiler instead:

1. **Install Microsoft C++ Build Tools** — tick **"Desktop development with
   C++"** during setup:
   https://visualstudio.microsoft.com/visual-cpp-build-tools/
2. **Install the Python build packages:**
   ```powershell
   python -m pip install cython setuptools
   ```
3. **Build with the `setuptools` backend:**
   ```powershell
   python convert.py --input <path to strategy.py> --backend setuptools
   ```

This path uses Cython's normal `setuptools` + MSVC build. It's the original
behaviour, kept as a fallback. The output `.pyd` is identical in use — only the
compiler differs.

---

## 7. Linux `.so` (Docker)

Linux builds don't use TCC; they use `gcc` inside a Docker container, so no build
tools are needed on the Windows host either — just Docker Desktop:

```powershell
python convert.py --input <path to strategy.py> --linux
```

The container's Python version (set in the `Dockerfile`) determines which Python
the `.so` works with. See the README for version-matching rules.

---

## 8. Limitations

- **TCC output is unoptimized** → slower than MSVC. Negligible for strategy
  *logic*; heavy pure-Python numeric loops would be slower. Code that calls into
  numpy/pandas stays fast (those are precompiled and only imported at runtime).
- **One `.pyd` per Python minor version / OS / architecture.** This is inherent
  to native extensions, not specific to TCC.
- **Strings and constants are still extractable.** Only program *logic* is
  protected, not embedded text or keys.

---

## 9. Provenance of the bundled compiler

The contents of `vendor/tcc-win64/` were **not built in this repo** — they are an
official prebuilt TCC release, downloaded and copied in (with `doc/` and
`examples/` removed).

| | |
|---|---|
| Project | TinyCC (TCC) — https://bellard.org/tcc/ , https://repo.or.cz/w/tinycc.git |
| Version | 0.9.27 (x86_64, Windows) — the last tagged release (2017) |
| Source | `http://download.savannah.gnu.org/releases/tinycc/tcc-0.9.27-win64-bin.zip` |
| Zip size | 489,586 bytes |
| Zip SHA256 | `34A721949A2583FDFF725312DA092FA0F5F1F284B702E6F811C6954714FAABB2` |
| `tcc.exe` SHA256 | `E9CB3E89E20A9EFEAD83CC9E6B100314275634C2F705056DA71F424EA9B0CDF0` |

> The download URL is plain `http://` (Savannah's mirror), so it was not
> transport-verified. The hashes above let you confirm the committed binary
> matches what was downloaded. For maximum trust, rebuild `tcc.exe` from the
> TinyCC source and vendor your own build.
