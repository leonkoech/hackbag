# Robot Control Server — Agent API Reference

Base URL: `http://localhost:5000`

---

## System Architecture

```
AI Agent ──HTTP──> Flask Server (:5000) ──proxy──> ESP32 Devices (192.168.137.x)
                        |                               |
                        |── API Endpoints                |── ESP32-S3-CAM (.52)
                        |   /docs                        |   OV Camera (MJPEG)
                        |   /devices/status              |   LED Strip (PWM GPIO21)
                        |   /camera/capture              |
                        |   /camera/stream               |── ESP32 WROOM-32 (.xx)
                        |   /gps                         |   Neo-6M GPS (UART 9600)
                        |   /led                         |
                        |   /audio/say                   |── New ESP32 ? (auto-discovered)
                        |   /audio/listen                |   Any sensor with /docs
                        |   /audio/transcripts           |
                        |   /audio/devices               |
                        |                                |
                        |── Admin Endpoints              |
                        |   /admin/scan                  |
                        |   /admin/register              |
                        |   /admin/unregister            |
                        |   /admin/devices               |
                        |   /admin/routes                |
                        |                                |
                        |── Dynamic Proxy Routes         |
                        |   /device/{ip}/...        ─────┘
                        |
                        |── Audio (ElevenLabs Cloud)
                            TTS: eleven_multilingual_v2
                            STT: scribe_v1
                            Hardware: EPOS Adapt 660 (USB-C)
                                Microphone (continuous listen)
                                Speaker (TTS output)
```

See `roboflow.html` for the interactive architecture diagram (open in browser).
See `image.png` for a static screenshot of the architecture.

### Data Flow: New Device Discovery

```
New ESP32 plugged in
    -> POST /admin/scan (or agent triggers scan)
    -> Server scans 192.168.137.1-255
    -> Finds device with HTTP on port 80
    -> Fetches GET /docs from the device
    -> Parses endpoints from docs JSON
    -> Creates proxy routes: /device/{ip}/{path}
    -> Saves to devices.json (persists across restarts)
    -> Agent can now call /device/{ip}/{path} immediately
```

---

## Project Files

| File | Purpose |
|------|---------|
| `app.py` | Flask server — all endpoints, continuous listener, startup |
| `device_manager.py` | Hardcoded ESP32 device proxying (camera, GPS, LED) |
| `device_registry.py` | Network scanner, /docs fetcher, devices.json persistence |
| `route_builder.py` | Dynamic Flask route generation from device docs |
| `audio_manager.py` | ElevenLabs TTS/STT, PyAudio recording, continuous listening |
| `devices.json` | Auto-generated — persisted registry of discovered devices |
| `.env` | API keys (`ELEVENLABS_API_KEY`) |
| `roboflow.html` | Interactive SVG architecture diagram |
| `image.png` | Static screenshot of the architecture diagram |
| `requirements.txt` | Python dependencies |

### Hardcoded Device IPs (in app.py)

| Device | IP | Role |
|--------|----|------|
| GOOUUU ESP32-S3-CAM | 192.168.137.52 | Camera, LED strip |
| ESP32 WROOM-32 | 192.168.137.xx | GPS node (update after checking Serial Monitor) |

---

## Endpoint Reference

### GET /docs

Returns the full API documentation as JSON. This is the first thing an agent should read.

```bash
curl http://localhost:5000/docs
```

**Response:** JSON object with `server`, `description`, `base_url`, and `endpoints` array.

---

## Device Status

### GET /devices/status

Ping all hardcoded ESP32 devices and return online status.

```bash
curl http://localhost:5000/devices/status
```

**Response:**
```json
{
  "camera_esp": {"ip": "http://192.168.137.52", "online": true},
  "gps_esp": {"ip": "http://192.168.137.xx", "online": false}
}
```

---

## Camera

### GET /camera/capture

Capture a single JPEG image from the ESP32-S3-CAM.

```bash
curl http://localhost:5000/camera/capture --output photo.jpg
```

**Response:** Binary `image/jpeg`

**Errors:**
- `503` — Camera ESP unreachable: `{"error": "Camera unavailable"}`

### GET /camera/stream

Proxy the MJPEG stream from ESP32-S3-CAM. Use for real-time video or YOLO inference.

```bash
curl http://localhost:5000/camera/stream --output stream.mjpeg
```

**Response:** `multipart/x-mixed-replace; boundary=frame`

---

## Vision

### GET /camera/detect

Run YOLOv8 object detection on a camera capture. Fast (~50ms), runs offline, recognizes 80 COCO classes (person, backpack, bottle, phone, laptop, etc).

```bash
curl http://localhost:5000/camera/detect
```

**Response:**
```json
{
  "detections": [
    {"class": "backpack", "confidence": 0.95, "bbox": [10.0, 20.0, 200.0, 400.0]},
    {"class": "bottle", "confidence": 0.87, "bbox": [150.0, 100.0, 200.0, 300.0]}
  ],
  "count": 2
}
```

**Errors:**
- `503` — YOLO not installed or camera unavailable

### GET /camera/identify

Comprehensive identification using YOLO first, then Claude Vision. Claude recognizes anything YOLO can't: keys, wallet, cables, brands, text on objects, context.

**Query params (optional):**
| Param | Type | Description |
|-------|------|-------------|
| prompt | string | Custom question about the image (e.g. "Is there a wallet here?") |

```bash
# Default: identify everything
curl http://localhost:5000/camera/identify

# Custom prompt
curl "http://localhost:5000/camera/identify?prompt=What%20items%20are%20missing%20from%20this%20backpack?"
```

**Response:**
```json
{
  "detections": [{"class": "backpack", "confidence": 0.95, "bbox": [...]}],
  "yolo_count": 1,
  "claude": "I can see a navy blue backpack open on a table. Inside I can see a laptop, a water bottle, and a charging cable. I don't see sunscreen, a hat, or a first aid kit which you might want for a hike.",
  "prompt": null
}
```

**Fallback:** If `ANTHROPIC_API_KEY` is not set, returns YOLO-only results with `"claude": null`.

**Errors:**
- `503` — Camera unavailable

---

## GPS

### GET /gps

Get current GPS location from the GPS node.

```bash
curl http://localhost:5000/gps
```

**Response:**
```json
{
  "lat": 37.7749,
  "lng": -122.4194,
  "sats": 8,
  "kmh": 0.0,
  "fix": true
}
```

**Errors:**
- `503` — GPS node unreachable: `{"error": "GPS node unavailable"}`

---

## LED

### POST /led

Control the LED strip on the ESP32-S3-CAM.

**Query params:**
| Param | Type | Values | Default | Description |
|-------|------|--------|---------|-------------|
| state | string | `on`, `off` | `off` | Turn LEDs on or off |
| brightness | string | `0`-`255` | `255` | LED brightness level |

```bash
# Turn on at half brightness
curl -X POST "http://localhost:5000/led?state=on&brightness=128"

# Turn off
curl -X POST "http://localhost:5000/led?state=off"
```

**Response:**
```json
{"state": "on", "brightness": 128}
```

**Errors:**
- `503` — Camera ESP unreachable: `{"error": "Camera ESP unavailable"}`

---

## Audio (ElevenLabs)

Audio uses ElevenLabs cloud APIs. The EPOS Adapt 660 headset is auto-detected by name (keywords: "epos", "sennheiser", "headset", "usb audio"). Falls back to system default if not found.

**Continuous listener:** A background thread records 5-second audio chunks and transcribes each one. Non-empty transcripts are stored in a rolling buffer (last 50).

### POST /audio/say

Convert text to speech using ElevenLabs and play through the speaker.

**Body:**
```json
{"text": "Hello, I am your robot"}
```

```bash
curl -X POST http://localhost:5000/audio/say \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, I am your robot"}'
```

**Response:**
```json
{"status": "ok", "spoken": "Hello, I am your robot"}
```

**Details:**
- Voice: Rachel (default)
- Model: `eleven_multilingual_v2` (supports 29 languages)
- Output: MP3 44100Hz 128kbps
- Audio plays on the server machine via the EPOS speaker

### POST /audio/listen

Record a single audio clip from the microphone and transcribe it.

**Body:**
```json
{"duration_seconds": 5}
```

`duration_seconds` defaults to 5 if omitted.

```bash
curl -X POST http://localhost:5000/audio/listen \
  -H "Content-Type: application/json" \
  -d '{"duration_seconds": 5}'
```

**Response:**
```json
{
  "transcript": "turn on the lights please",
  "language": "en",
  "duration_seconds": 5
}
```

**Details:**
- Records at 16kHz mono 16-bit PCM
- Saves to temp WAV file, sends to ElevenLabs `scribe_v1`
- Language is auto-detected

### GET /audio/transcripts

Get recent transcripts from the continuous background listener. Returns the last 50 non-empty transcriptions, oldest first.

```bash
curl http://localhost:5000/audio/transcripts
```

**Response:**
```json
[
  {"transcript": "hello robot", "language": "en", "duration_seconds": 5},
  {"transcript": "what is the temperature", "language": "en", "duration_seconds": 5},
  {"transcript": "turn on the lights", "language": "en", "duration_seconds": 5}
]
```

**Agent usage:** Poll this endpoint to know what the user is saying in real time. New transcripts appear every ~5 seconds (recording chunk size).

### GET /audio/devices

List all detected audio input/output devices and which ones are active.

```bash
curl http://localhost:5000/audio/devices
```

**Response:**
```json
{
  "inputs": [
    {"index": 0, "name": "EPOS Adapt 660"},
    {"index": 1, "name": "Realtek Microphone"}
  ],
  "outputs": [
    {"index": 2, "name": "EPOS Adapt 660"},
    {"index": 3, "name": "Realtek Speakers"}
  ],
  "active_mic": {"index": 0, "name": "EPOS Adapt 660"},
  "active_speaker": {"index": 2, "name": "EPOS Adapt 660"}
}
```

---

## Admin — Device Discovery & Dynamic Routes

These endpoints allow the agent (or a human) to discover new ESP32 devices on the network, register them, and automatically create proxy routes based on their `/docs`.

### POST /admin/scan

Scan the local network for ESP32 devices that expose a `/docs` endpoint. For each new device found, fetches its docs and creates proxy routes.

**Query params (all optional):**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| subnet | string | `192.168.137` | Subnet prefix to scan |
| start | int | `1` | First host octet |
| end | int | `255` | Last host octet |

```bash
# Scan the default subnet
curl -X POST http://localhost:5000/admin/scan

# Scan a specific range
curl -X POST "http://localhost:5000/admin/scan?subnet=192.168.1&start=100&end=200"
```

**Response:**
```json
{
  "new_devices": ["192.168.137.53", "192.168.137.60"],
  "routes_added": [
    {"path": "/device/192.168.137.53/temperature", "method": "GET", "description": "Read temperature in Celsius"},
    {"path": "/device/192.168.137.53/humidity", "method": "GET", "description": "Read humidity percentage"},
    {"path": "/device/192.168.137.60/motion", "method": "GET", "description": "Check PIR motion sensor"}
  ]
}
```

**Details:**
- Scans up to 255 IPs in parallel (50 workers)
- Probes port 80 with a TCP socket (3s timeout per IP)
- If HTTP responds, fetches `GET /docs`
- Only devices with a valid `/docs` JSON response are registered
- Previously known devices are skipped (not duplicated)
- New devices are saved to `devices.json`

### POST /admin/register

Manually register a device by IP. The server fetches `/docs` from the device and creates proxy routes.

**Body:**
```json
{"ip": "192.168.137.53"}
```

Optionally pass docs directly (useful if the device is temporarily offline or you want to pre-register):
```json
{
  "ip": "192.168.137.53",
  "docs": {
    "server": "Temperature Sensor",
    "description": "DHT22 temperature and humidity sensor",
    "endpoints": [
      {"path": "/temperature", "method": "GET", "description": "Read temperature in Celsius"},
      {"path": "/humidity", "method": "GET", "description": "Read humidity percentage"},
      {"path": "/led", "method": "POST", "description": "Control status LED", "params": {"state": "on | off"}}
    ]
  }
}
```

```bash
curl -X POST http://localhost:5000/admin/register \
  -H "Content-Type: application/json" \
  -d '{"ip": "192.168.137.53"}'
```

**Response:**
```json
{
  "device": {
    "ip": "192.168.137.53",
    "port": 80,
    "base_url": "http://192.168.137.53",
    "docs": {"server": "Temperature Sensor", "endpoints": [...]},
    "status": "registered"
  },
  "routes_added": [
    {"path": "/device/192.168.137.53/temperature", "method": "GET", "description": "Read temperature in Celsius"}
  ]
}
```

**Errors:**
- `400` — Missing `ip`: `{"error": "Missing 'ip' in request body"}`
- `502` — Cannot reach device: `{"error": "Could not fetch /docs from http://192.168.137.53"}`

### POST /admin/unregister

Remove a registered device and its entry from `devices.json`.

**Body:**
```json
{"ip": "192.168.137.53"}
```

```bash
curl -X POST http://localhost:5000/admin/unregister \
  -H "Content-Type: application/json" \
  -d '{"ip": "192.168.137.53"}'
```

**Response:**
```json
{"removed": true, "ip": "192.168.137.53"}
```

**Note:** Dynamic proxy routes created for this device remain active until server restart. The device will not be re-registered on restart since it's removed from `devices.json`.

### GET /admin/devices

List all registered devices (from `devices.json`) and their full docs.

```bash
curl http://localhost:5000/admin/devices
```

**Response:**
```json
{
  "192.168.137.53": {
    "ip": "192.168.137.53",
    "port": 80,
    "base_url": "http://192.168.137.53",
    "docs": {
      "server": "Temperature Sensor",
      "endpoints": [
        {"path": "/temperature", "method": "GET", "description": "Read temperature in Celsius"}
      ]
    },
    "status": "registered"
  }
}
```

### GET /admin/routes

List all dynamic proxy routes currently active on the server.

```bash
curl http://localhost:5000/admin/routes
```

**Response:**
```json
[
  {"path": "/device/192.168.137.53/temperature", "methods": ["GET"]},
  {"path": "/device/192.168.137.53/humidity", "methods": ["GET"]},
  {"path": "/device/192.168.137.60/motion", "methods": ["GET"]}
]
```

---

## Dynamic Proxy Routes

When a device is registered (via scan or manual register), the server automatically creates Flask routes that proxy requests to the device.

### Route Pattern

```
/device/{device_ip}/{endpoint_path}
```

### How Proxying Works

| What | How |
|------|-----|
| Query params | Forwarded as-is to the device |
| JSON body | Forwarded as-is (POST/PUT) |
| Binary responses | Streamed back (images, audio, multipart) |
| JSON responses | Parsed and re-serialized |
| Errors | `503` with `{"error": "Device unreachable: ..."}` |
| Supported methods | GET, POST, PUT, DELETE |

### Example

If device `192.168.137.53` has these docs:
```json
{
  "endpoints": [
    {"path": "/temperature", "method": "GET", "description": "Read temp"},
    {"path": "/relay", "method": "POST", "description": "Toggle relay", "params": {"state": "on | off"}}
  ]
}
```

Then these proxy routes are created:
```bash
# Read temperature
curl http://localhost:5000/device/192.168.137.53/temperature
# -> proxies to http://192.168.137.53/temperature

# Toggle relay
curl -X POST "http://localhost:5000/device/192.168.137.53/relay?state=on"
# -> proxies to http://192.168.137.53/relay?state=on
```

### Persistence

- Registered devices are saved to `devices.json`
- On server startup, all devices from `devices.json` have their proxy routes restored
- No manual re-registration needed after restart

---

## ESP32 Device /docs Contract

For a device to be auto-discovered and integrated, it must serve `GET /docs` on port 80 returning JSON in this format:

```json
{
  "server": "Device Name",
  "description": "Human-readable description of what this device does",
  "endpoints": [
    {
      "path": "/endpoint-path",
      "method": "GET",
      "description": "What this endpoint does"
    },
    {
      "path": "/another-endpoint",
      "method": "POST",
      "description": "What this does",
      "params": {"param_name": "allowed values"},
      "body": {"field": "example value"},
      "response": {"field": "example response"}
    }
  ]
}
```

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `endpoints` | array | List of endpoint objects |
| `endpoints[].path` | string | URL path (e.g. `/temperature`) |
| `endpoints[].method` | string | HTTP method: `GET`, `POST`, `PUT`, `DELETE` |
| `endpoints[].description` | string | What the endpoint does |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `server` | string | Device name |
| `description` | string | Device description |
| `endpoints[].params` | object | Query parameter descriptions |
| `endpoints[].body` | object | Request body example |
| `endpoints[].response` | object | Response example |

### Example: Minimal ESP32 Arduino Sketch

```cpp
#include <WiFi.h>
#include <WebServer.h>

WebServer server(80);

void setup() {
  WiFi.begin("SSID", "PASSWORD");
  while (WiFi.status() != WL_CONNECTED) delay(500);

  server.on("/docs", []() {
    server.send(200, "application/json",
      "{\"server\":\"Temp Sensor\","
      "\"endpoints\":["
      "{\"path\":\"/temperature\",\"method\":\"GET\",\"description\":\"Read temp in C\"}"
      "]}");
  });

  server.on("/temperature", []() {
    float temp = readTemperature();  // your sensor code
    server.send(200, "application/json",
      "{\"celsius\":" + String(temp) + "}");
  });

  server.begin();
}

void loop() { server.handleClient(); }
```

---

## Agent Workflow

### Startup Sequence

1. `GET /docs` — read the full endpoint list to understand available capabilities
2. `GET /devices/status` — check which hardcoded devices are online
3. `GET /admin/devices` — check if any devices were previously discovered
4. `POST /admin/scan` — scan the network for new ESP32 devices

### Main Loop

1. `GET /audio/transcripts` — poll for new user speech (every few seconds)
2. Process transcript — decide what action to take
3. Execute action — call the appropriate endpoint(s)
4. `POST /audio/say` — speak the result back to the user

### When a New Device Appears

1. `POST /admin/scan` or `POST /admin/register` — discover/register it
2. `GET /admin/devices` — read its docs to understand what it does
3. `GET /admin/routes` — see the new proxy routes
4. Call `/device/{ip}/{path}` — interact with the device

### Example Agent Session

```bash
# 1. Boot — understand the system
curl http://localhost:5000/docs
curl http://localhost:5000/devices/status

# 2. Discover devices
curl -X POST http://localhost:5000/admin/scan

# 3. Check what was found
curl http://localhost:5000/admin/devices
curl http://localhost:5000/admin/routes

# 4. User says "what's the temperature?"
curl http://localhost:5000/audio/transcripts
# -> [{"transcript": "what's the temperature", ...}]

# 5. Agent calls the discovered temperature sensor
curl http://localhost:5000/device/192.168.137.53/temperature
# -> {"celsius": 23.5}

# 6. Agent speaks the answer
curl -X POST http://localhost:5000/audio/say \
  -H "Content-Type: application/json" \
  -d '{"text": "The temperature is 23.5 degrees Celsius"}'

# 7. Take a photo for context
curl http://localhost:5000/camera/capture --output photo.jpg

# 8. Check GPS location
curl http://localhost:5000/gps
```

---

## Error Handling

All error responses follow this format:
```json
{"error": "Description of what went wrong"}
```

| HTTP Code | Meaning |
|-----------|---------|
| `400` | Bad request — missing required field in body |
| `502` | Bad gateway — could not reach device to fetch /docs |
| `503` | Service unavailable — device is offline or unreachable |

---

## Environment Variables

Set in `.env` file in the project root:

| Variable | Required | Description |
|----------|----------|-------------|
| `ELEVENLABS_API_KEY` | Yes | ElevenLabs API key for TTS and STT |

---

## Network Requirements

| Service | Connectivity | Notes |
|---------|-------------|-------|
| ESP32 devices | LAN `192.168.137.x` | Hotspot or local network |
| ElevenLabs API | Internet | Cloud TTS/STT — requires active internet |
| Flask server | `0.0.0.0:5000` | Accessible from any device on the network |
