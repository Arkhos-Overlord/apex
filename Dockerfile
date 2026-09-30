# APEX — single-stage build
FROM python:3.11-slim

WORKDIR /app

# curl is used by the container healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Copy application source first, then install the package (better layer caching)
COPY apex/ ./apex/
COPY dashboard/ ./dashboard/
COPY content/ ./content/
COPY pyproject.toml README.md ./

RUN pip install --no-cache-dir .

# Directories for persistence and generated artifacts
RUN mkdir -p /data /output && chmod 777 /data /output
ENV APEX_DB=/data/apex.db \
    APEX_CONTENT_DIR=/app/content \
    APEX_OUTPUT_DIR=/output

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

COPY docker-entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "dashboard.server:app", "--host", "0.0.0.0", "--port", "8080"]
