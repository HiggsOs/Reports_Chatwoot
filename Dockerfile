FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=America/Bogota \
    DATA_DIR=/data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py chatwoot.py reporte.py ringover.py reporte_ringover.py cloudtalk.py reporte_cloudtalk.py app.py generar_hash.py alembic.ini ./
COPY panel ./panel

RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"

# Las migraciones se aplican en cada arranque: si no hay cambios pendientes no
# hacen nada, y si fallan el contenedor no arranca con un esquema viejo.
CMD ["sh", "-c", "alembic upgrade head && exec streamlit run app.py --server.address=0.0.0.0 --server.port=8501 --server.headless=true --browser.gatherUsageStats=false"]
