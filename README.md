# Driftpak — Robot Control Server

Flask API server that exposes ESP32 camera, GPS, LED and EPOS audio
as clean HTTP endpoints for an AI agent to consume.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Raspberry Pi 5  (hostname: smartbag)                           │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  OpenClaw Agent ("Driftpak")          port 18789           │ │
│  │  AI brain — reads transcripts, decides actions, speaks     │ │
│  │  Connected to: Telegram bot (@smartbag_hackbot)            │ │
│  └──────────────────────┬─────────────────────────────────────┘ │
│                         │ curl commands                          │
│  ┌──────────────────────▼─────────────────────────────────────┐ │
│  │  Flask Server (app.py)                port 5000            │ │
│  │                                                            │ │
│  │  /audio/say ──────→ ElevenLabs TTS ──→ EPOS speaker       │ │
│  │  /audio/listen ←── EPOS mic ──→ ElevenLabs STT            │ │
│  │  /audio/transcripts  (continuous background listener)      │ │
│  │  /camera/capture ─────→ HTTP GET ──→ ESP32-CAM             │ │
│  │  /camera/detect ──────→ capture + YOLOv8 (offline)         │ │
│  │  /camera/identify ────→ YOLO + Claude Vision (cloud)       │ │
│  │  /gps ────────────────→ HTTP GET ──→ ESP32-GPS             │ │
│  │  /led ────────────────→ HTTP POST ─→ ESP32-CAM             │ │
│  │  /admin/scan ─────────→ discover new ESP32 devices         │ │
│  └──────────┬──────────────────────────────────┬──────────────┘ │
│             │ USB                              │ WiFi            │
│  ┌──────────▼──────────┐          ┌────────────▼─────────────┐  │
│  │  EPOS Adapt 660     │          │  ESP32 Devices           │  │
│  │  Microphone + Speaker│          │  Camera (192.168.137.52) │  │
│  │  (USB-C to Pi)      │          │  GPS    (192.168.137.xx) │  │
│  └─────────────────────┘          │  LEDs   (on camera board)│  │
│                                   └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
         │                                    │
         │ Internet (cloud APIs)              │ All on same WiFi
         ▼                                    │ hotspot network
  ┌──────────────┐                            │
  │ ElevenLabs   │                     ┌──────▼──────┐
  │ (TTS + STT)  │                     │ WiFi Hotspot│
  ├──────────────┤                     │ 192.168.137 │
  │ Anthropic    │                     └─────────────┘
  │ (Claude      │
  │  Vision)     │
  └──────────────┘
```

## Setup

```bash
pip install -r requirements.txt
```

> On Raspberry Pi you may also need:
> ```bash
> sudo apt-get install portaudio19-dev mpg123
> ```

## Config

Copy `.env.example` to `.env.local` and fill in your API keys (ElevenLabs, Anthropic, etc.).

Edit the IPs at the top of `app.py`:
```python
ESP_CAM_IP = "192.168.137.52"   # GOOUUU ESP32-S3-CAM
ESP_GPS_IP = "192.168.137.xx"   # ESP32 WROOM-32 GPS node
```

## Run

```bash
python app.py
```

Server starts at http://localhost:5000

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /docs | Full API documentation |
| GET | /devices/status | Ping all ESP32 devices |
| GET | /camera/capture | Single JPEG photo |
| GET | /camera/stream | MJPEG stream for YOLO |
| GET | /gps | GPS location |
| POST | /led?state=on&brightness=200 | Control LEDs |
| GET | /audio/devices | List audio devices |
| POST | /audio/say | Text to speech via EPOS |
| POST | /audio/listen | Record + transcribe via ElevenLabs |
| GET | /camera/detect | YOLO object detection |
| GET | /camera/identify | YOLO + Claude Vision |

## EPOS Device

The server auto-detects the EPOS headset by name.
If it's not found it falls back to system default.

Run `GET /audio/devices` to see all detected devices and confirm
which one is active.

## Test it

```bash
# Health check
curl http://localhost:5000/devices/status

# Take a photo
curl http://localhost:5000/camera/capture --output photo.jpg

# Get GPS
curl http://localhost:5000/gps

# Turn LEDs on
curl -X POST "http://localhost:5000/led?state=on&brightness=200"

# Speak
curl -X POST http://localhost:5000/audio/say \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, I am your robot"}'

# Listen for 5 seconds and transcribe
curl -X POST http://localhost:5000/audio/listen \
  -H "Content-Type: application/json" \
  -d '{"duration_seconds": 5}'
```
