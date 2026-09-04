FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DRIFT_DATA_DIR=/data
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-pol tesseract-ocr-fra tesseract-ocr-jpn \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home drift && mkdir /data && chown drift:drift /data
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py discord_notify.py service.py storage.py sources.yaml ./
COPY parsers ./parsers
USER drift
VOLUME /data
HEALTHCHECK --interval=60s --timeout=10s --start-period=35m --retries=3 CMD python service.py --healthcheck
CMD ["python", "service.py"]
