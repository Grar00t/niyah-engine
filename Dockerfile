FROM python:3.12-slim

LABEL maintainer="Sulaiman Alshammari <dragon403@khawrizm.sa>"
LABEL description="NIYAH Engine v5 — Sovereign Three-Lobe AI"

WORKDIR /opt/niyah

COPY engine/ ./engine/
COPY config/ ./config/

RUN mkdir -p /var/log/niyah /var/lib/niyah && \
    chmod +x engine/niyah_core.py

ENV NIYAH_OLLAMA_URL=http://ollama:11434
ENV NIYAH_LOG_DIR=/var/log/niyah
ENV NIYAH_DATA_DIR=/var/lib/niyah
ENV PYTHONUNBUFFERED=1

EXPOSE 7474

HEALTHCHECK --interval=30s --timeout=5s \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:7474/health')" || exit 1

ENTRYPOINT ["python3", "engine/niyah_core.py"]
CMD ["--server", "--port", "7474"]
