import argparse
import glob
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile


def _run(cmd, **kwargs):
    """Run a command, echoing it for visibility."""
    print("  $ " + " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, **kwargs)


def _ensure_cython():
    try:
        import Cython  # noqa: F401
    except ImportError:
        sys.exit("ERROR: Cython not installed. Run: python -m pip install cython")


def cython_to_c(src_py, out_c):
    """Transpile .py -> .c. Pure Python; needs NO C compiler."""
    result = _run([
        sys.executable, "-m", "cython", src_py,
        "-3",
        "-X", "annotation_typing=False",
        "-o", out_c,
    ])
    if result.returncode != 0 or not os.path.isfile(out_c):
        sys.exit("ERROR: Cython transpile (.py -> .c) failed.")


# ----------------------------------------------------------------------------
# TCC backend: compile .c -> .pyd with the bundled Tiny C Compiler.
# No Microsoft C++ Build Tools required.
# ----------------------------------------------------------------------------

def find_tcc():
    """Locate a tcc.exe: bundled copy first, then PATH."""
    here = os.path.dirname(os.path.abspath(__file__))
    bundled = os.path.join(here, "vendor", "tcc-win64", "tcc.exe")
    if os.path.isfile(bundled):
        return bundled
    on_path = shutil.which("tcc")
    if on_path:
        return on_path
    return None


def find_python_dll():
    """Find the running interpreter's pythonXY.dll (to build an import lib)."""
    tag = f"python{sys.version_info.major}{sys.version_info.minor}"
    name = tag + ".dll"
    candidates = [
        os.path.join(sys.base_prefix, name),
        os.path.join(os.path.dirname(sys.executable), name),
        os.path.join(sys.base_exec_prefix, name),
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", name),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c, tag
    return None, tag


def build_native_tcc(input_path, module_name, output_dir):
    _ensure_cython()

    tcc = find_tcc()
    if not tcc:
        sys.exit(
            "ERROR: tcc.exe not found.\n"
            "Expected it at vendor/tcc-win64/tcc.exe (bundled) or on PATH."
        )

    dll, tag = find_python_dll()
    if not dll:
        sys.exit(
            f"ERROR: could not locate {tag}.dll for the current interpreter.\n"
            f"Looked near {sys.base_prefix} and {os.path.dirname(sys.executable)}."
        )

    include = sysconfig.get_path("include")
    ext_suffix = sysconfig.get_config_var("EXT_SUFFIX") or ".pyd"

    print(f"Compiler : {tcc}")
    print(f"Python   : {tag} (dll: {dll})")
    print(f"Headers  : {include}")
    print(f"Compiling via TCC -> {module_name}{ext_suffix}")

    with tempfile.TemporaryDirectory() as workdir:
        local_src = os.path.join(workdir, module_name + ".py")
        shutil.copyfile(input_path, local_src)

        # 1) .py -> .c  (pure Cython, no compiler)
        c_path = os.path.join(workdir, module_name + ".c")
        cython_to_c(local_src, c_path)

        # 2) build an import definition for pythonXY.dll that TCC can link.
        #    (TCC cannot read MSVC-format .lib files.)
        def_path = os.path.join(workdir, tag + ".def")
        if _run([tcc, "-impdef", dll, "-o", def_path]).returncode != 0 \
                or not os.path.isfile(def_path):
            sys.exit("ERROR: 'tcc -impdef' failed to build the Python import lib.")

        # 3) .c -> .pyd
        pyd_path = os.path.join(workdir, module_name + ext_suffix)
        compile_cmd = [
            tcc, "-shared", c_path, "-o", pyd_path,
            "-I", include,
            "-L", workdir, f"-l{tag}",
            # TCC mis-evaluates sizeof() in an enum constant, tripping a Cython
            # static assert; this disables Cython's PyLong fast path (correct,
            # marginally slower integer math) to sidestep it.
            "-DCYTHON_USE_PYLONG_INTERNALS=0",
        ]
        if _run(compile_cmd).returncode != 0 or not os.path.isfile(pyd_path):
            sys.exit(
                "\nERROR: TCC compile (.c -> .pyd) failed.\n"
                "This can happen if the strategy uses C-level deps (e.g. 'cimport').\n"
                "Try '--backend setuptools' if you have MS C++ Build Tools installed."
            )

        dest = os.path.join(output_dir, os.path.basename(pyd_path))
        shutil.move(pyd_path, dest)
    return [dest]


# ----------------------------------------------------------------------------
# setuptools backend: original path, uses the system C compiler (MSVC on
# Windows). Kept as a fallback for cases TCC cannot handle.
# ----------------------------------------------------------------------------

def build_native_setuptools(input_path, module_name, output_dir):
    _ensure_cython()

    setup_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "setup_build.py")
    if not os.path.isfile(setup_py):
        sys.exit(f"ERROR: setup_build.py not found next to convert.py ({setup_py}).")

    print(f"Compiling via setuptools -> {'.pyd' if os.name == 'nt' else '.so'}")
    with tempfile.TemporaryDirectory() as workdir:
        local_src = os.path.join(workdir, module_name + ".py")
        shutil.copyfile(input_path, local_src)

        # Point the committed setup_build.py at our copied source via env var,
        # and run it in the temp dir so generated .c/build files land there.
        env = dict(os.environ, CYTHONIZE_SRC=local_src)
        result = _run(
            [sys.executable, setup_py, "build_ext", "--inplace"],
            cwd=workdir, env=env,
        )
        if result.returncode != 0:
            sys.exit(
                "\nERROR: compile failed.\n"
                "Windows needs 'Microsoft C++ Build Tools' (Desktop development with C++).\n"
                "Linux needs: build-essential python3-dev\n"
                "Tip: on Windows use the default '--backend tcc' to avoid Build Tools."
            )

        built = glob.glob(os.path.join(workdir, "*.pyd")) + glob.glob(os.path.join(workdir, "*.so"))
        if not built:
            sys.exit("ERROR: no compiled file produced.")

        final = []
        for b in built:
            dest = os.path.join(output_dir, os.path.basename(b))
            shutil.move(b, dest)
            final.append(dest)
    return final


# ----------------------------------------------------------------------------
# Docker backend: build a Linux .so (gcc lives inside the container).
# ----------------------------------------------------------------------------

def build_docker(input_path, output_dir, module_name):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    folder = os.path.dirname(input_path)
    fname = os.path.basename(input_path)

    print("Building Docker image (first time only; cached after)...")
    if _run(["docker", "build", "-t", "pycompile", script_dir]).returncode != 0:
        sys.exit("ERROR: 'docker build' failed. Is Docker Desktop installed and running?")

    print("Compiling inside Docker -> .so")
    # Override the image's default command so we can name the module and force
    # the setuptools backend (gcc lives in the container; TCC is Windows-only).
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{folder}:/src",
        "-v", f"{output_dir}:/output",
        "pycompile",
        "python", "convert.py",
        "--input", f"/src/{fname}",
        "--output", "/output",
        "--name", module_name,
        "--backend", "setuptools",
    ]
    if _run(cmd).returncode != 0:
        sys.exit("ERROR: 'docker run' failed. Is Docker Desktop running? Is the drive shared?")
    return glob.glob(os.path.join(output_dir, "*.so"))


def main():
    parser = argparse.ArgumentParser(
        description="Compile a .py into a native .pyd (Windows) or .so (Linux via --linux)."
    )
    parser.add_argument("--input", required=True,
                        help="Absolute path of the .py file to compile.")
    parser.add_argument("--output", default=None,
                        help="Output folder (default: ./output next to this script).")
    parser.add_argument("--name", default=None,
                        help="Module name for the compiled file (default: input "
                             "file name). The import name is baked into the binary.")
    parser.add_argument("--backend", choices=["tcc", "setuptools"], default=None,
                        help="Native backend. Default: 'tcc' on Windows (bundled, no "
                             "Build Tools), 'setuptools' elsewhere (system compiler).")
    parser.add_argument("--linux", action="store_true",
                        help="Build a Linux .so inside Docker instead of compiling natively.")
    args = parser.parse_args()

    input_path = os.path.abspath(args.input)
    if not os.path.isfile(input_path):
        sys.exit(f"ERROR: input file not found: {input_path}")
    if not input_path.endswith(".py"):
        sys.exit(f"ERROR: input must be a .py file: {input_path}")

    module_name = args.name or os.path.splitext(os.path.basename(input_path))[0]
    if not module_name.isidentifier():
        sys.exit(f"ERROR: '{module_name}' is not a valid Python module name.")

    if args.output:
        output_dir = os.path.abspath(args.output)
    else:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(output_dir, exist_ok=True)

    print(f"Input  : {input_path}")
    print(f"Output : {output_dir}")
    print("-" * 60)

    if args.linux:
        final = build_docker(input_path, output_dir, module_name)
    else:
        backend = args.backend or ("tcc" if os.name == "nt" else "setuptools")
        if backend == "setuptools":
            final = build_native_setuptools(input_path, module_name, output_dir)
        else:
            final = build_native_tcc(input_path, module_name, output_dir)

    print("-" * 60)
    print("SUCCESS. Compiled file(s):")
    for p in final:
        print("  " + p)


if __name__ == "__main__":
    main()
