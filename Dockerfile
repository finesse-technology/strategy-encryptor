FROM python:3.12.10-slim-bookworm

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential python3-dev && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir cython setuptools

WORKDIR /app
COPY convert.py /app/convert.py
COPY setup_build.py /app/setup_build.py

ENV SRC=strategy.py

CMD ["sh", "-c", "python convert.py --input /src/$SRC --output /output"]