from flask import Flask, jsonify, request, Response
from device_manager import DeviceManager
from audio_manager import AudioManager
from device_registry import DeviceRegistry
from route_builder import build_routes, build_all_routes
from vision_manager import VisionManager
import logging
import threading
from collections import deque

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ── Config — update these IPs after checking Serial Monitor ──
ESP_CAM_IP  = "192.168.137.52"   # GOOUUU ESP32-S3-CAM
ESP_GPS_IP  = "192.168.137.xx"   # ESP32 WROOM-32 GPS node  ← update this

devices  = DeviceManager(cam_ip=ESP_CAM_IP, gps_ip=ESP_GPS_IP)
audio    = AudioManager()
vision   = VisionManager(devices=devices)
registry = DeviceRegistry()

# ── Continuous listening buffer ──
transcripts = deque(maxlen=50)  # keeps last 50 transcriptions

def _on_transcript(result):
    transcripts.append(result)

listener_thread = threading.Thread(
    target=audio.listen_continuous,
    kwargs={"chunk_seconds": 5, "callback": _on_transcript},
    daemon=True,
)

# ═══════════════════════════════════════════════════════════
#  DOCS — agent reads this first
# ═══════════════════════════════════════════════════════════

@app.route("/docs", methods=["GET"])
def docs():
    return jsonify({
        "server": "Robot Control Server",
        "description": "Flask API for controlling ESP32 camera, GPS, LEDs and EPOS audio",
        "base_url": "http://localhost:5000",
        "endpoints": [
            {
                "path": "/docs",
                "method": "GET",
                "description": "This documentation"
            },
            {
                "path": "/devices/status",
                "method": "GET",
                "description": "Ping all ESP32 devices and return online status"
            },
            {
                "path": "/camera/capture",
                "method": "GET",
                "description": "Capture a single JPEG image from ESP32-S3-CAM",
                "response": "image/jpeg"
            },
            {
                "path": "/camera/stream",
                "method": "GET",
                "description": "Proxy MJPEG stream from ESP32-S3-CAM for YOLO inference"
            },
            {
                "path": "/camera/detect",
                "method": "GET",
                "description": "Run YOLOv8 object detection on camera image. Fast, offline, 80 COCO classes.",
                "response": {"detections": [{"class": "backpack", "confidence": 0.95, "bbox": []}], "count": 1}
            },
            {
                "path": "/camera/identify",
                "method": "GET",
                "description": "YOLO + Claude Vision for comprehensive object identification. Recognizes brands, text, anything.",
                "params": {"prompt": "optional custom question about the image"},
                "response": {"detections": [], "yolo_count": 0, "claude": "detailed description"}
            },
            {
                "path": "/gps",
                "method": "GET",
                "description": "Get current GPS location from GPS node",
                "response": {"lat": 0.0, "lng": 0.0, "sats": 0, "kmh": 0.0, "fix": True}
            },
            {
                "path": "/led",
                "method": "POST",
                "description": "Control LED strip on ESP32-S3-CAM",
                "params": {"state": "on | off", "brightness": "0-255"},
                "example": "POST /led?state=on&brightness=200"
            },
            {
                "path": "/audio/say",
                "method": "POST",
                "description": "Convert text to speech and play through EPOS device",
                "body": {"text": "Hello world"}
            },
            {
                "path": "/audio/listen",
                "method": "POST",
                "description": "Record audio from EPOS mic and transcribe with ElevenLabs",
                "body": {"duration_seconds": 5},
                "response": {"transcript": "...", "language": "en"}
            },
            {
                "path": "/audio/transcripts",
                "method": "GET",
                "description": "Get recent transcripts from continuous listening",
                "response": [{"transcript": "...", "language": "en", "duration_seconds": 5}]
            },
            {
                "path": "/audio/devices",
                "method": "GET",
                "description": "List available audio input/output devices"
            },
            {
                "path": "/admin/scan",
                "method": "POST",
                "description": "Scan the network for new ESP32 devices with /docs endpoints",
                "params": {"subnet": "192.168.137", "start": 1, "end": 255},
                "response": {"new_devices": [], "routes_added": []}
            },
            {
                "path": "/admin/devices",
                "method": "GET",
                "description": "List all registered devices and their docs"
            },
            {
                "path": "/admin/register",
                "method": "POST",
                "description": "Manually register an ESP32 device by IP. Fetches /docs and creates proxy routes.",
                "body": {"ip": "192.168.137.xx"},
                "response": {"device": {}, "routes_added": []}
            },
            {
                "path": "/admin/unregister",
                "method": "POST",
                "description": "Remove a registered device",
                "body": {"ip": "192.168.137.xx"}
            },
            {
                "path": "/admin/routes",
                "method": "GET",
                "description": "List all dynamic proxy routes currently active"
            }
        ]
    })

# ═══════════════════════════════════════════════════════════
#  DEVICES
# ═══════════════════════════════════════════════════════════

@app.route("/devices/status", methods=["GET"])
def device_status():
    return jsonify(devices.ping_all())

# ═══════════════════════════════════════════════════════════
#  CAMERA
# ═══════════════════════════════════════════════════════════

@app.route("/camera/capture", methods=["GET"])
def camera_capture():
    img_bytes = devices.capture()
    if img_bytes is None:
        return jsonify({"error": "Camera unavailable"}), 503
    return Response(img_bytes, mimetype="image/jpeg")

@app.route("/camera/stream", methods=["GET"])
def camera_stream():
    return Response(
        devices.stream(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )

# ═══════════════════════════════════════════════════════════
#  VISION — YOLO + Claude Vision
# ═══════════════════════════════════════════════════════════

@app.route("/camera/detect", methods=["GET"])
def camera_detect():
    """Run YOLOv8 object detection on a camera capture."""
    result = vision.detect()
    if "error" in result and not result.get("detections"):
        return jsonify(result), 503
    return jsonify(result)

@app.route("/camera/identify", methods=["GET"])
def camera_identify():
    """YOLO + Claude Vision for comprehensive identification."""
    prompt = request.args.get("prompt")
    result = vision.identify(prompt=prompt)
    if "error" in result and not result.get("detections"):
        return jsonify(result), 503
    return jsonify(result)

# ═══════════════════════════════════════════════════════════
#  GPS
# ═══════════════════════════════════════════════════════════

@app.route("/gps", methods=["GET"])
def gps():
    data = devices.get_gps()
    if data is None:
        return jsonify({"error": "GPS node unavailable"}), 503
    return jsonify(data)

# ═══════════════════════════════════════════════════════════
#  LED
# ═══════════════════════════════════════════════════════════

@app.route("/led", methods=["POST"])
def led():
    state      = request.args.get("state", "off")
    brightness = request.args.get("brightness", "255")
    result = devices.set_led(state=state, brightness=brightness)
    if result is None:
        return jsonify({"error": "Camera ESP unavailable"}), 503
    return jsonify(result)

# ═══════════════════════════════════════════════════════════
#  AUDIO
# ═══════════════════════════════════════════════════════════

@app.route("/audio/devices", methods=["GET"])
def audio_devices():
    return jsonify(audio.list_devices())

@app.route("/audio/say", methods=["POST"])
def audio_say():
    data = request.get_json()
    if not data or "text" not in data:
        return jsonify({"error": "Missing 'text' in request body"}), 400
    audio.say(data["text"])
    return jsonify({"status": "ok", "spoken": data["text"]})

@app.route("/audio/listen", methods=["POST"])
def audio_listen():
    data     = request.get_json() or {}
    duration = int(data.get("duration_seconds", 5))
    result   = audio.listen(duration_seconds=duration)
    return jsonify(result)

@app.route("/audio/transcripts", methods=["GET"])
def audio_transcripts():
    """Return recent transcripts from the continuous listener."""
    return jsonify(list(transcripts))

# ═══════════════════════════════════════════════════════════
#  ADMIN — device discovery & dynamic routes
# ═══════════════════════════════════════════════════════════

@app.route("/admin/scan", methods=["POST"])
def admin_scan():
    """Scan the network for new ESP32 devices, fetch their /docs, and create proxy routes."""
    subnet = request.args.get("subnet", "192.168.137")
    start = int(request.args.get("start", 1))
    end = int(request.args.get("end", 255))

    new_devices = registry.scan(subnet=subnet, ip_range=(start, end))
    routes_added = []
    for device in new_devices:
        routes = build_routes(app, device)
        routes_added.extend(routes)

    return jsonify({
        "new_devices": [d["ip"] for d in new_devices],
        "routes_added": routes_added,
    })

@app.route("/admin/devices", methods=["GET"])
def admin_devices():
    """List all registered devices and their docs."""
    return jsonify(registry.list_devices())

@app.route("/admin/register", methods=["POST"])
def admin_register():
    """Manually register a device by IP. Fetches /docs and creates proxy routes."""
    data = request.get_json()
    if not data or "ip" not in data:
        return jsonify({"error": "Missing 'ip' in request body"}), 400

    ip = data["ip"]
    docs = data.get("docs")  # optionally pass docs directly
    device = registry.register(ip, docs=docs)

    if "error" in device:
        return jsonify(device), 502

    routes = build_routes(app, device)
    return jsonify({"device": device, "routes_added": routes})

@app.route("/admin/unregister", methods=["POST"])
def admin_unregister():
    """Remove a registered device."""
    data = request.get_json()
    if not data or "ip" not in data:
        return jsonify({"error": "Missing 'ip' in request body"}), 400

    removed = registry.unregister(data["ip"])
    return jsonify({"removed": removed, "ip": data["ip"]})

@app.route("/admin/routes", methods=["GET"])
def admin_routes():
    """List all dynamic proxy routes."""
    routes = []
    for rule in app.url_map.iter_rules():
        if rule.rule.startswith("/device/"):
            routes.append({
                "path": rule.rule,
                "methods": list(rule.methods - {"OPTIONS", "HEAD"}),
            })
    return jsonify(routes)

# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Restore proxy routes for previously registered devices
    restored = build_all_routes(app, registry)
    for entry in restored:
        print(f"   Restored routes for {entry['ip']}: {len(entry['routes'])} endpoint(s)")

    print("\n🤖 Robot Control Server starting...")
    print(f"   CAM  → http://{ESP_CAM_IP}")
    print(f"   GPS  → http://{ESP_GPS_IP}")
    print(f"   API  → http://localhost:5000")
    print(f"   Docs → http://localhost:5000/docs\n")
    if audio.audio_available:
        listener_thread.start()
        print("   🎧 Continuous listener started")
    else:
        print("   ⚠️  Audio unavailable — listener disabled, non-audio endpoints still work")
    app.run(host="0.0.0.0", port=5000, debug=False)
