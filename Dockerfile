# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    XDG_CACHE_HOME=/home/expense/.cache \
    UPLOAD_DIR=/app/data/uploads \
    DATABASE_PATH=/app/data/expenses.db \
    TESSERACT_CMD=/usr/bin/tesseract \
    PADDLE_DEVICE=cpu \
    OMP_NUM_THREADS=2

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates tesseract-ocr tesseract-ocr-eng libgomp1 libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 expense \
    && useradd --uid 10001 --gid expense --create-home --shell /usr/sbin/nologin expense \
    && mkdir -p /app/data /home/expense/.cache /home/expense/.paddlex /home/expense/.paddle \
    && chown -R expense:expense /app/data /home/expense

WORKDIR /app
COPY pyproject.toml ./
COPY app/ ./app/
RUN python -m pip install '.[ocr-paddle]' && python -m pip check

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"]
CMD ["python", "-m", "app.container"]

# Explicit test target; test code and test packages do not enter the runtime image.
FROM runtime AS test
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install '.[test]'
COPY tests/ ./tests/
USER 10001:10001
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
