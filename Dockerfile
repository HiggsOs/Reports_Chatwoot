# 1) El frontend de React: se compila con Node y solo se copia el resultado.
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# 2) La API (FastAPI) y la sincronización, en Python.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=America/Bogota \
    DATA_DIR=/data

WORKDIR /app

# ffmpeg convierte las grabaciones de CloudTalk a MP3.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py chatwoot.py reporte.py ringover.py reporte_ringover.py cloudtalk.py reporte_cloudtalk.py app.py generar_hash.py alembic.ini ./
COPY panel ./panel
COPY ui ./ui
COPY .streamlit ./.streamlit
COPY api ./api
COPY --from=web /web/dist ./web/dist

RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8501

# El servicio de sincronización (python -m panel.sync) no sirve web: para él
# basta con que su proceso siga vivo; si no, Docker lo daría por caído y lo
# reiniciaría a mitad de un ciclo.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD grep -qa panel.sync /proc/1/cmdline || python -c "import urllib.request as u; exec('try: u.urlopen(\'http://localhost:8501/api/salud\')\nexcept Exception: u.urlopen(\'http://localhost:8501/_stcore/health\')')"

# Las migraciones se aplican en cada arranque: si no hay cambios pendientes no
# hacen nada, y si fallan el contenedor no arranca con un esquema viejo.
# Panel (API + React). Durante la transición, la versión Streamlit se arranca con:
#   sh -c "alembic upgrade head && streamlit run app.py --server.address=0.0.0.0 --server.port=8501 --server.headless=true"
# y la sincronización, como siempre, con: python -m panel.sync
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn api.main:crear_app --factory --host 0.0.0.0 --port 8501 --proxy-headers --forwarded-allow-ips='*'"]
