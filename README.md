# Five Minutes Ago

This repository contains the production scripts for a two-site, low-latency audiovisual link built with Python, GStreamer, and SRT, plus a small web control app for monitoring and operating the relay server.

In practical terms, it connects two fixed locations, identified in the code as `tn` and `dk`, and does three jobs:

- captures local video and audio at each site
- relays those streams through a central server
- plays back the remote site on the opposite end while recording the incoming video feeds on the server

The media pipeline remains Linux-specific and operational, but the repo now also includes a lightweight FastAPI dashboard that can supervise the relay process, show logs and recording activity, and update `production/config.yaml` from a browser.

## What The System Does

The system is split into three runtime roles:

1. `production/1_sender`
   Captures a local camera feed and sends it to the relay server. It can also run a companion audio process that captures microphone input, sends it to the server, receives the remote site's audio back from the server, and plays it locally.

2. `production/2_server`
   Acts as the relay hub. It listens for incoming audio and video from both sites, forwards each site's media to the opposite site, records the raw incoming video streams to disk, and restarts failed pipelines automatically.

3. `production/3_receiver`
   Receives the relayed video feed for a site and displays it fullscreen via `kmssink`. If the live feed stalls, it switches to a fallback snow pattern until the primary feed recovers.

One important architectural detail: the receiver is video-only. Audio playback happens on the sender machine via `send_audio.py`, not in `production/3_receiver/receive.py`.

The repository also includes a separate control-plane role:

4. `control_app`
   A browser-based dashboard that starts/stops the relay server, tails its logs, shows recording file activity under `/mnt/tbdrive`, and lets an operator edit `production/config.yaml` and apply changes by restarting the relay.

## Signal Flow

### Video

```text
Tunisia sender (tn)  -> \
                         \
                          Relay server -> Denmark receiver (dk)
                         /
Denmark sender (dk)  -> /

Denmark sender (dk)  -> \
                         \
                          Relay server -> Tunisia receiver (tn)
                         /
Tunisia sender (tn)  -> /
```

Each sender transmits an MPEG-TS/H.264 video stream over SRT to the server. The server forwards each incoming stream to the opposite site's receiver port and also writes the incoming stream to a local `.ts` file.

### Audio

```text
Tunisia audio sender  -> Relay server -> Denmark audio sender
Denmark audio sender  -> Relay server -> Tunisia audio sender
```

The audio path is bidirectional between the two sender machines. Each sender:

- captures local audio from ALSA
- sends it to the server as RTP L16 over SRT
- simultaneously receives the remote site's audio from the server
- plays the remote audio locally

The sender-side audio pipeline includes WebRTC echo-control elements so local playback can be used as an echo reference.

## Repository Layout

```text
control_app/
  main.py                     FastAPI app and HTTP routes
  settings.py                 App paths and env-driven settings
  services/
    config_service.py         Reads, validates, and writes config.yaml
    relay_supervisor.py       Starts/stops the relay subprocess and captures logs
    storage_service.py        Summarizes working and archived recording files
    dashboard_service.py      Composes API-ready dashboard status
  static/
    index.html                Browser UI shell
    styles.css                Dashboard styling
    app.js                    Polling and control logic
Dockerfile                    Container image for the control app + relay runtime
requirements.txt              Python web dependency list
production/
  config.yaml                 Shared runtime configuration
  config_loader.py            Loads config.yaml relative to production/
  1_sender/
    send.py                   Video sender entry point; can launch audio subprocess
    send_audio.py             Full-duplex audio sender/playback process
  2_server/
    server.py                 Main relay/recording supervisor
    audio_pipeline.py         Builds cross-routed audio relay pipeline
    video_pipeline.py         Builds cross-routed video relay + raw recording pipelines
    modules/
      check_streams.py        Polls configured ports with tcpdump
      record.py               Alternate MP4 recorder for incoming send ports
      timed_volume.py         Utility for time-based Gst volume fades
    backups/                  Historical iterations
    wip/                      Work-in-progress experiments
  3_receiver/
    receive.py                Video receiver with fallback switching
    backups/                  Historical iterations
    wip/                      Work-in-progress experiments
```

The active production entry points are the top-level scripts under `1_sender`, `2_server`, and `3_receiver`. The web control entry point is `control_app/main.py`. The `backups/` and `wip/` directories appear to be archived experiments and earlier revisions rather than the current runtime path.

## Core Runtime Behavior

### `production/1_sender/send.py`

- Requires `--country tn` or `--country dk`.
- Builds a video capture pipeline from `production/config.yaml`.
- Uses the configured video source, which currently defaults to `v4l2src device=/dev/video0`.
- Encodes video with `x264enc`, wraps it in MPEG-TS, and sends it to the configured SRT port on the relay server.
- Prompts interactively to decide whether to launch `send_audio.py` as a subprocess.
- If the video pipeline exits or errors, it restarts after 5 seconds.

### `production/1_sender/send_audio.py`

- Requires `--country tn` or `--country dk`.
- Optionally accepts `--device` to override the ALSA device.
- Captures local audio from ALSA and sends it to the server.
- Receives the opposite site's audio from the server and plays it locally.
- Uses `webrtcechoprobe` on playback and `webrtcdsp` on capture to support echo cancellation.
- If the pipeline exits or errors, it restarts after 5 seconds.

### `production/2_server/server.py`

- Starts one audio relay pipeline and two video relay pipelines.
- Relays `tn -> dk` and `dk -> tn` independently.
- Monitors all pipelines via the GStreamer bus.
- On EOS or error, restarts the failed pipeline instead of exiting.
- For video pipelines, copies the current raw recording file to a timestamped archive before restarting.
- On shutdown, copies both raw recording files before setting all pipelines to `NULL`.

Video recordings are written to these active working files:

- `/mnt/tbdrive/video_tn.ts`
- `/mnt/tbdrive/video_dk.ts`

Archived copies are written to:

- `/mnt/tbdrive/video/`

The copy operation is now handled inside Python with `shutil.copy2`, so the server environment just needs a mounted and writable `/mnt/tbdrive/video`.

### `control_app/main.py`

- Serves a small browser UI plus JSON APIs.
- Starts the relay server automatically on app startup by default.
- Supervises `production/2_server/server.py` as a subprocess.
- Captures a rolling log tail from the relay process.
- Reports whether the relay is running, its PID, uptime, and last exit code.
- Reports current working recording files and recent archived recordings from `/mnt/tbdrive`.
- Lets an operator save `production/config.yaml` and optionally restart the relay immediately to apply the change.
- Supports optional HTTP Basic Auth via `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD`.

### `production/3_receiver/receive.py`

- Requires `--country tn` or `--country dk`.
- Connects to the server's site-specific receive port over SRT.
- Demuxes MPEG-TS, decodes H.264, scales to `1920x1080`, and displays via `kmssink`.
- Uses an `input-selector` with two branches:
  - primary live video
  - fallback `videotestsrc pattern=snow`
- Monitors the primary path by observing buffers on a tee branch.
- If no primary buffers are seen for 5 seconds, it switches to the fallback feed.
- If primary buffers resume, it switches back automatically.
- If the receiver stops unexpectedly, the manager restarts it after 5 seconds.

## Configuration

All shared runtime settings live in `production/config.yaml`.

### Network

- `server_ip`
  IP address or hostname of the central relay server.
- `streaming_settings_audio`
  Extra SRT query parameters appended to audio sender URIs.
- `streaming_settings_video`
  Extra SRT query parameters appended to video sender URIs.

### Port Mapping

| Key | Purpose |
| --- | --- |
| `audio_send_tn` | Tunisia sender -> server audio ingest |
| `audio_send_dk` | Denmark sender -> server audio ingest |
| `audio_receive_tn` | server -> Tunisia sender audio playback feed |
| `audio_receive_dk` | server -> Denmark sender audio playback feed |
| `video_send_tn` | Tunisia sender -> server video ingest |
| `video_send_dk` | Denmark sender -> server video ingest |
| `video_receive_tn` | server -> Tunisia receiver video feed |
| `video_receive_dk` | server -> Denmark receiver video feed |

### Audio Settings

The `audio` section defines the RTP L16 payload format and ALSA-related defaults used by the sender-side audio pipeline:

- `format`
- `rate`
- `channels`
- `encoding_name`

### Video Settings

The `video` section controls the sender-side capture and encoding pipeline, including:

- source element string
- output width and height
- encoder and tuning settings
- bitrate
- GOP / keyframe interval
- MPEG-TS mux alignment

### WebRTC DSP Settings

`webrtcdsp_settings` configures the echo/noise processing behavior used by `send_audio.py`. Not every field is currently consumed everywhere, but the config clearly reflects an intent to tune live duplex audio behavior from a single file.

## Dependencies And Environment Assumptions

This repo expects a Linux machine with Python 3 and GStreamer bindings already available.

At minimum, the code relies on:

- Python packages:
  - `PyGObject`
  - `PyYAML`
  - `fastapi`
  - `uvicorn`
  - `psutil` for `production/kill.py`
- GStreamer 1.0 with plugins/elements used in the pipelines, including:
  - `srtsrc`, `srtsink`
  - `x264enc`
  - `mpegtsmux`, `tsdemux`
  - `h264parse`, `avdec_h264`
  - `rtpL16pay`, `rtpL16depay`
  - `webrtcdsp`, `webrtcechoprobe`
  - `alsasrc`, `alsasink`
  - `videoconvert`, `videoscale`, `videotestsrc`
  - `kmssink`

The scripts also assume hardware or OS resources such as:

- `/dev/video0` for the camera by default
- ALSA audio devices on sender machines
- KMS/DRM output support on receiver machines
- `/mnt/tbdrive` storage on the server

## Running The System

There is no single orchestrator. Each role is started manually.

### 1. Configure the shared settings

Edit `production/config.yaml` so all machines agree on:

- the relay server IP
- the audio/video port mapping
- the sender-side capture devices and encoding settings

### 2. Start the relay server

```bash
python3 production/2_server/server.py
```

### 3. Start each sender machine

Tunisia sender:

```bash
python3 production/1_sender/send.py --country tn
```

Denmark sender:

```bash
python3 production/1_sender/send.py --country dk
```

`send.py` will prompt whether it should also launch the audio subprocess. If you answer yes, it will optionally ask for an ALSA device override and then start `send_audio.py`.

### 4. Start each receiver machine

Tunisia receiver:

```bash
python3 production/3_receiver/receive.py --country tn
```

Denmark receiver:

```bash
python3 production/3_receiver/receive.py --country dk
```

## Utilities

### `production/2_server/modules/check_streams.py`

Continuously checks the configured audio and video ports with `tcpdump` and prints a simple live status view. It requires `sudo` because it shells out to `tcpdump`.

### `production/2_server/modules/record.py`

An alternate recorder that listens directly on the incoming send ports, muxes video and audio into MP4, and writes:

- `/mnt/tbdrive/video/recorded_tn.mp4`
- `/mnt/tbdrive/video/recorded_dk.mp4`

This is separate from the main server relay and appears to be an auxiliary or experimental recorder rather than the primary production path.

### `production/2_server/modules/timed_volume.py`

A helper module for attaching a `GstController` interpolation source to a volume element and fading that volume up or down based on the current minute of the hour.

### `production/kill.py`

A small cleanup script that terminates processes bound to a hard-coded list of ports. Its port list does not match the current `config.yaml`, so it should be treated as a legacy utility rather than a reliable operational tool.

## Practical Caveats

- Site handling is hard-coded around two locations: `tn` and `dk`.
- Runtime setup is manual; there are no service files, container definitions, or install scripts in the repo.
- Several paths are hard-coded for the deployment environment, especially `/dev/video0` and `/mnt/tbdrive`.
- The sender scripts are interactive because `send.py` prompts for audio subprocess startup.
- The server recording/archive path depends on `sudo cp`.
- Some helper scripts and backup folders are historical and may not reflect the current live path.

## In One Sentence

This is a Linux/GStreamer/SRT production toolkit for running a two-site live audio/video link, where sender nodes capture media, a central server relays and records it, and receiver nodes display the remote video with automatic fallback handling.
