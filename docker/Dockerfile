FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim-bookworm AS pgvector
RUN apt-get update && apt-get install -y --no-install-recommends build-essential postgresql-server-dev-15 curl ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN curl --fail --location --retry 3 https://codeload.github.com/pgvector/pgvector/tar.gz/refs/tags/v0.8.7 -o pgvector.tar.gz \
    && echo 'cac0b10c360f05b2d521200105ba3697e773d4cd3731f5a915a7e37ebe0bea85  pgvector.tar.gz' | sha256sum -c - \
    && tar -xzf pgvector.tar.gz \
    && make -C pgvector-0.8.7 OPTFLAGS='' \
    && make -C pgvector-0.8.7 install DESTDIR=/build/install

FROM python:3.13-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/usr/lib/postgresql/15/bin:${PATH}"
RUN apt-get update && apt-get install -y --no-install-recommends nginx postgresql-15 redis-server supervisor util-linux ca-certificates && rm -rf /var/lib/apt/lists/* && useradd --system --create-home gateway && usermod -a -G gateway postgres
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY --from=pgvector /build/install/usr/lib/postgresql/15/lib/vector.so /usr/lib/postgresql/15/lib/vector.so
COPY --from=pgvector /build/install/usr/share/postgresql/15/extension/ /usr/share/postgresql/15/extension/
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY models/compliance/ /app/compliance-model/
RUN echo "f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193  /app/compliance-model/model.onnx" | sha256sum -c - && echo "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39  /app/compliance-model/tokenizer.json" | sha256sum -c -
COPY backend/ ./
COPY config/ /app/config/
COPY --from=frontend /build/dist /app/frontend
COPY docker/nginx.conf /app/nginx.conf.template
COPY docker/supervisord.conf /etc/supervisor/supervisord.conf
COPY docker/redis.conf /etc/redis/gateway.conf
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
EXPOSE 80 443
HEALTHCHECK --interval=15s --timeout=10s --start-period=60s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1/health', timeout=8)"
ENTRYPOINT ["/app/entrypoint.sh"]
