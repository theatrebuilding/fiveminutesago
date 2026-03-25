FROM ghcr.io/tailscale/tailscale:v1.94.2 AS tailscale

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    TS_STATE_DIR=/var/lib/tailscale \
    TS_SOCKET=/var/run/tailscale/tailscaled.sock \
    TS_USERSPACE=false

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    iproute2 \
    iptables \
    tini \
    gir1.2-gst-plugins-base-1.0 \
    gir1.2-gstreamer-1.0 \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-tools \
    python3 \
    python3-gi \
    python3-gst-1.0 \
    python3-venv \
 && rm -rf /var/lib/apt/lists/*

COPY --from=tailscale /usr/local/bin/tailscale /usr/local/bin/tailscale
COPY --from=tailscale /usr/local/bin/tailscaled /usr/local/bin/tailscaled

WORKDIR /app
COPY requirements.txt /app/requirements.txt

RUN python3 -m venv --system-site-packages /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.txt

COPY . /app
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
 && mkdir -p /mnt/tbdrive/video /var/lib/tailscale /var/run/tailscale

VOLUME ["/mnt/tbdrive", "/var/lib/tailscale"]

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]
CMD ["python3", "/app/server.py"]