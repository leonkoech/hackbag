import json
import socket
import requests
import logging
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

DEVICES_FILE = Path(__file__).parent / "devices.json"
TIMEOUT = 3  # seconds per probe
SCAN_PORTS = [80]  # ESP32 devices typically serve on port 80


class DeviceRegistry:
    def __init__(self):
        self.devices = {}  # ip -> device info dict
        self._lock = threading.Lock()
        self._load()

    # ── Persistence ─────────────────────────────────────────

    def _load(self):
        if DEVICES_FILE.exists():
            try:
                data = json.loads(DEVICES_FILE.read_text())
                with self._lock:
                    self.devices = data
                logger.info(f"Loaded {len(data)} device(s) from {DEVICES_FILE}")
            except Exception as e:
                logger.warning(f"Failed to load {DEVICES_FILE}: {e}")

    def _save(self):
        with self._lock:
            snapshot = dict(self.devices)
        DEVICES_FILE.write_text(json.dumps(snapshot, indent=2))
        logger.info(f"Saved {len(snapshot)} device(s) to {DEVICES_FILE}")

    # ── Network scanning ────────────────────────────────────

    def _probe_ip(self, ip: str) -> dict | None:
        """Check if an IP has an HTTP server and try to fetch /docs."""
        for port in SCAN_PORTS:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(TIMEOUT)
                result = sock.connect_ex((ip, port))
                sock.close()
                if result != 0:
                    continue

                base = f"http://{ip}:{port}" if port != 80 else f"http://{ip}"
                docs = self._fetch_docs(base)
                if docs:
                    return {
                        "ip": ip,
                        "port": port,
                        "base_url": base,
                        "docs": docs,
                        "status": "discovered",
                    }
            except Exception:
                continue
        return None

    def _fetch_docs(self, base_url: str) -> dict | None:
        """Fetch /docs from a device. Returns the JSON or None."""
        try:
            resp = requests.get(f"{base_url}/docs", timeout=TIMEOUT)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    def scan(self, subnet: str = "192.168.137", ip_range: tuple = (1, 255),
             max_workers: int = 50) -> list[dict]:
        """
        Scan a subnet for ESP32 devices with /docs endpoints.
        Returns list of newly discovered devices.
        """
        logger.info(f"Scanning {subnet}.{ip_range[0]}-{ip_range[1]}...")
        new_devices = []
        ips = [f"{subnet}.{i}" for i in range(ip_range[0], ip_range[1] + 1)]

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(self._probe_ip, ip): ip for ip in ips}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    ip = result["ip"]
                    with self._lock:
                        is_new = ip not in self.devices
                        self.devices[ip] = result
                    if is_new:
                        new_devices.append(result)
                        logger.info(f"Discovered new device: {ip}")

        if new_devices:
            self._save()

        logger.info(f"Scan complete. {len(new_devices)} new device(s) found.")
        return new_devices

    # ── Manual registration ─────────────────────────────────

    def register(self, ip: str, docs: dict = None) -> dict:
        """
        Manually register a device. If docs not provided, fetches from /docs.
        """
        base_url = f"http://{ip}"

        if docs is None:
            docs = self._fetch_docs(base_url)
            if docs is None:
                return {"error": f"Could not fetch /docs from {base_url}"}

        device = {
            "ip": ip,
            "port": 80,
            "base_url": base_url,
            "docs": docs,
            "status": "registered",
        }

        with self._lock:
            self.devices[ip] = device
        self._save()

        logger.info(f"Registered device: {ip}")
        return device

    def unregister(self, ip: str) -> bool:
        with self._lock:
            if ip in self.devices:
                del self.devices[ip]
                self._save()
                return True
        return False

    def list_devices(self) -> dict:
        with self._lock:
            return dict(self.devices)

    def get_device(self, ip: str) -> dict | None:
        with self._lock:
            return self.devices.get(ip)
