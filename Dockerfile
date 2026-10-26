# Dockerfile - builds a Linux .so from your .py file.
#
# Mount the folder with your .py as /src, set SRC to the file name,
# and mount an output folder as /output. See README.md for the command.

FROM python:3.12.10-slim-bookworm

# Linux C compiler (gcc) + Python headers, then the build packages.
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential python3-dev && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir cython setuptools

WORKDIR /app
COPY convert.py /app/convert.py
COPY setup_build.py /app/setup_build.py

# SRC = the .py file name inside the mounted /src folder.
ENV SRC=strategy.py

CMD ["sh", "-c", "python convert.py --input /src/$SRC --output /output"]