"""Setuptools build script for the `setuptools` backend of convert.py.

Kept as a committed file (instead of being written to a temp dir each run) so
the build logic is visible and editable. The source file to compile is passed in
via the CYTHONIZE_SRC environment variable, so the same script compiles any
strategy:

    CYTHONIZE_SRC=<path to file.py>  python setup_build.py build_ext --inplace

convert.py runs this with the working directory set to a temp folder, so the
generated .c / build artifacts land there and the .pyd/.so is produced inplace.
"""

import os
import sys

from setuptools import setup
from Cython.Build import cythonize

src = os.environ.get("CYTHONIZE_SRC")
if not src:
    sys.exit("setup_build.py: set CYTHONIZE_SRC to the .py file to compile.")

setup(
    ext_modules=cythonize(
        src,
        language_level=3,
        compiler_directives={"annotation_typing": False},
    )
)
