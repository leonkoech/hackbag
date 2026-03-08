import requests
import logging

logger = logging.getLogger(__name__)

TIMEOUT = 3  # seconds

class DeviceManager:
    def __init__(self, cam_ip: str, gps_ip: str, air_ip: str = None):
        self.cam_base = f"http://{cam_ip}"
        self.gps_base = f"http://{gps_ip}"
        self.air_base = f"http://{air_ip}" if air_ip else None

    # ── Helpers ───────────────────────────────────────────

    def _get(self, url: str, stream: bool = False):
        try:
            return requests.get(url, timeout=TIMEOUT, stream=stream)
        except requests.exceptions.RequestException as e:
            logger.warning(f"GET {url} failed: {e}")
            return None

    def _post(self, url: str, params: dict = None):
        try:
            return requests.post(url, params=params, timeout=TIMEOUT)
        except requests.exceptions.RequestException as e:
            logger.warning(f"POST {url} failed: {e}")
            return None

    # ── Status ────────────────────────────────────────────

    def ping_all(self) -> dict:
        cam_ok = self._get(f"{self.cam_base}/ping")
        gps_ok = self._get(f"{self.gps_base}/ping")
        status = {
            "camera_esp": {
                "ip":     self.cam_base,
                "online": cam_ok is not None and cam_ok.status_code == 200
            },
            "gps_esp": {
                "ip":     self.gps_base,
                "online": gps_ok is not None and gps_ok.status_code == 200
            }
        }
        if self.air_base:
            air_ok = self._get(self.air_base)
            status["air_quality"] = {
                "ip":     self.air_base,
                "online": air_ok is not None and air_ok.status_code == 200
            }
        return status

    # ── Camera ────────────────────────────────────────────

    def capture(self) -> bytes | None:
        res = self._get(f"{self.cam_base}/capture")
        if res and res.status_code == 200:
            return res.content
        return None

    def stream(self):
        """Generator that proxies MJPEG frames from ESP32."""
        res = self._get(f"{self.cam_base}/stream", stream=True)
        if res is None:
            return
        try:
            for chunk in res.iter_content(chunk_size=4096):
                yield chunk
        except Exception as e:
            logger.warning(f"Stream interrupted: {e}")

    # ── GPS ───────────────────────────────────────────────

    def get_gps(self) -> dict | None:
        res = self._get(f"{self.gps_base}/gps")
        if res and res.status_code == 200:
            return res.json()
        return None

    # ── Air Quality ─────────────────────────────────────────

    def get_air(self) -> dict | None:
        if not self.air_base:
            return None
        res = self._get(f"{self.air_base}/air")
        if res and res.status_code == 200:
            return res.json()
        # Try root endpoint as fallback
        res = self._get(self.air_base)
        if res and res.status_code == 200:
            try:
                return res.json()
            except Exception:
                pass
        return None

    # ── LED ───────────────────────────────────────────────

    def set_led(self, state: str = "off", brightness: str = "255") -> dict | None:
        res = self._post(
            f"{self.cam_base}/led",
            params={"state": state, "brightness": brightness}
        )
        if res and res.status_code == 200:
            return res.json()
        return None
