FROM node:22-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json ./
RUN npm install --ignore-scripts --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM ubuntu:24.04
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates software-properties-common \
    && add-apt-repository -y ppa:kicad/kicad-9.0-releases \
    && apt-get update && apt-get install -y --no-install-recommends \
       kicad git python3 python3-venv fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt \
    && kicad-cli version | grep '^9\.'
ENV PATH="/opt/venv/bin:${PATH}" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV KICADDIFFVIEW_DATA=/data HOME=/data/home TMPDIR=/data/tmp XDG_CONFIG_HOME=/data/config XDG_CACHE_HOME=/data/cache
WORKDIR /app
COPY LICENSE ./LICENSE
COPY app/ ./app/
COPY --from=frontend /build/frontend/dist/ ./frontend/dist/
COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh
EXPOSE 8080
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "-m", "app.server", "--host", "0.0.0.0", "--port", "8080"]
