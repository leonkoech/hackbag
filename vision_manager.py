import os
import io
import base64
import logging
from dotenv import load_dotenv

load_dotenv(".env.local")
load_dotenv()

logger = logging.getLogger(__name__)

# Try importing optional dependencies
try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    logger.warning("ultralytics not installed — YOLO detection disabled (pip install ultralytics)")

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("Pillow not installed — image processing disabled (pip install pillow)")

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    logger.warning("anthropic not installed — Claude Vision disabled (pip install anthropic)")


class VisionManager:
    def __init__(self, devices=None):
        self.devices = devices
        self.model = None
        self.claude = None
        self.yolo_available = False
        self.claude_available = False

        # Load YOLOv8 nano model
        if YOLO_AVAILABLE:
            try:
                self.model = YOLO("yolov8n.pt")
                self.yolo_available = True
                logger.info("YOLOv8n model loaded")
            except Exception as e:
                logger.error(f"Failed to load YOLOv8 model: {e}")
        else:
            logger.warning("YOLO not available — detect endpoint will return errors")

        # Init Claude client
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key and ANTHROPIC_AVAILABLE:
            try:
                self.claude = anthropic.Anthropic(api_key=api_key)
                self.claude_available = True
                logger.info("Claude Vision ready")
            except Exception as e:
                logger.error(f"Failed to init Anthropic client: {e}")
        else:
            if not api_key:
                logger.warning("ANTHROPIC_API_KEY not set — Claude Vision disabled, falling back to YOLO-only")
            if not ANTHROPIC_AVAILABLE:
                logger.warning("anthropic package not installed — Claude Vision disabled")

    # ── Helpers ───────────────────────────────────────────

    def _image_to_base64(self, image_bytes: bytes) -> str:
        """Convert image bytes to base64 string."""
        return base64.b64encode(image_bytes).decode("utf-8")

    def _get_image_bytes(self, image_bytes: bytes = None) -> bytes | None:
        """Get image bytes from arg or capture from camera."""
        if image_bytes:
            return image_bytes
        if self.devices:
            img = self.devices.capture()
            if img:
                return img
            logger.warning("Camera capture returned None")
        return None

    # ── Tier 1: YOLO Detection ───────────────────────────

    def detect(self, image_bytes: bytes = None) -> dict:
        """
        Run YOLOv8 on an image. Returns list of detections with
        class name, confidence, and bounding box.

        Fast (~50ms), offline, 80 COCO classes.
        """
        if not self.yolo_available:
            return {"error": "YOLO not available — install ultralytics", "detections": []}

        img_data = self._get_image_bytes(image_bytes)
        if not img_data:
            return {"error": "No image available — pass image_bytes or connect camera", "detections": []}

        try:
            # YOLO can take PIL images or numpy arrays
            if PIL_AVAILABLE:
                image = Image.open(io.BytesIO(img_data))
            else:
                # Save to temp file as fallback
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                    tmp.write(img_data)
                    image = tmp.name

            results = self.model(image, verbose=False)
            detections = []

            for r in results:
                for box in r.boxes:
                    detections.append({
                        "class":      r.names[int(box.cls[0])],
                        "confidence": round(float(box.conf[0]), 3),
                        "bbox":       [round(float(c), 1) for c in box.xyxy[0].tolist()]
                    })

            # Clean up temp file if we used one
            if not PIL_AVAILABLE and isinstance(image, str):
                os.unlink(image)

            logger.info(f"YOLO detected {len(detections)} objects")
            return {"detections": detections, "count": len(detections)}

        except Exception as e:
            logger.error(f"YOLO detection failed: {e}")
            return {"error": str(e), "detections": []}

    # ── Tier 2: Claude Vision Identification ─────────────

    def identify(self, image_bytes: bytes = None, prompt: str = None) -> dict:
        """
        Run YOLO first for fast object detection, then send to
        Claude Vision for comprehensive identification.

        Claude recognizes anything YOLO can't: keys, wallet, cables,
        brands, text on objects, etc.

        Falls back to YOLO-only if Claude not available.
        """
        # Always run YOLO first
        yolo_result = self.detect(image_bytes)

        if not self.claude_available:
            yolo_result["claude"] = None
            yolo_result["note"] = "Claude Vision not available — YOLO-only results"
            return yolo_result

        img_data = self._get_image_bytes(image_bytes)
        if not img_data:
            return {"error": "No image available", "detections": yolo_result.get("detections", [])}

        # Build the prompt for Claude
        yolo_summary = ""
        if yolo_result.get("detections"):
            items = [f"{d['class']} ({d['confidence']:.0%})" for d in yolo_result["detections"]]
            yolo_summary = f"\n\nYOLO already detected: {', '.join(items)}"

        if prompt:
            system_prompt = f"You are a vision assistant in a smart backpack. Answer the user's question about what you see.{yolo_summary}"
            user_prompt = prompt
        else:
            system_prompt = "You are a vision assistant in a smart backpack. Identify everything you can see in this image — objects, brands, text, colors, context."
            user_prompt = f"What do you see in this image? Be specific and comprehensive. List every identifiable object, any readable text, brand logos, and notable details.{yolo_summary}"

        try:
            img_b64 = self._image_to_base64(img_data)

            response = self.claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": img_b64
                            }
                        },
                        {
                            "type": "text",
                            "text": user_prompt
                        }
                    ]
                }],
                system=system_prompt
            )

            claude_text = response.content[0].text
            logger.info(f"Claude Vision response: {claude_text[:100]}...")

            return {
                "detections": yolo_result.get("detections", []),
                "yolo_count": yolo_result.get("count", 0),
                "claude":     claude_text,
                "prompt":     prompt
            }

        except Exception as e:
            logger.error(f"Claude Vision failed: {e}")
            yolo_result["claude"] = None
            yolo_result["error"] = f"Claude Vision failed: {e}"
            return yolo_result
