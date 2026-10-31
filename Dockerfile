# Pont Venice en conteneur : bibliothèque standard seule (+ poppler-utils pour l'OCR des PDF scannés), utilisateur non root, aucune clé dans l'image.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    VENICE_PONT_ENV=/data/venice.env \
    VENICE_PONT_CREDITS=/data/credits.json \
    VENICE_PONT_ECOUTE=0.0.0.0:8700
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --no-create-home pont && mkdir /data && chown pont /data
COPY pont/venice_pont.py pont/formats.py /app/
USER pont
VOLUME /data
EXPOSE 8700
HEALTHCHECK --interval=60s --timeout=10s --start-period=15s \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8700/health', timeout=8).status == 200 else 1)"]
CMD ["python", "/app/venice_pont.py"]
