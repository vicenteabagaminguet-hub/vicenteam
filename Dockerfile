# ==================================================
# SEC Research Terminal
# Imagen con Chromium para imprimir los filings a PDF
# ==================================================

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CHROME_PATH=/usr/bin/chromium

# Chromium + tipografías (sin ellas los PDF salen con
# cuadros en vez de texto en algunos filings)
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        fonts-liberation \
        fonts-dejavu-core \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000

# Un solo worker con hilos: generar un PDF consume
# bastante memoria, y el timeout largo permite que
# una descarga de varios documentos termine.
CMD gunicorn app:app \
    --bind 0.0.0.0:${PORT:-8000} \
    --workers 1 \
    --threads 4 \
    --timeout 600 \
    --access-logfile -
