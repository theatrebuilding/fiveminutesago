FROM ghcr.io/tailscale/tailscale:v1.94.2 AS tailscale

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    TS_SOCKET=/var/run/tailscale/tailscaled.sock

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    alsa-utils \
    ca-certificates \
    ffmpeg \
    iproute2 \
    iptables \
    tini \
    gir1.2-gst-plugins-base-1.0 \
    gir1.2-gstreamer-1.0 \
    gstreamer1.0-libav \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-tools \
    python3 \
    python3-gi \
    python3-gst-1.0 \
    python3-venv \
    v4l-utils \
 && rm -rf /var/lib/apt/lists/*

COPY --from=tailscale /usr/local/bin/tailscale /usr/local/bin/tailscale
COPY --from=tailscale /usr/local/bin/tailscaled /usr/local/bin/tailscaled
COPY --from=tailscale /usr/local/bin/containerboot /usr/local/bin/containerboot

WORKDIR /app
COPY requirements.txt /app/requirements.txt

RUN python3 -m venv --system-site-packages /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.txt

COPY . /app
COPY start.sh /usr/local/bin/start.sh

RUN chmod +x /usr/local/bin/start.sh \
 && mkdir -p /var/lib/tailscale /var/run/tailscale

VOLUME ["/var/lib/tailscale"]

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/start.sh"]
CMD ["uvicorn", "control_app.main:app", "--host", "0.0.0.0", "--port", "8000"]
