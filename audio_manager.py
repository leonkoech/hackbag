import pyaudio
import wave
import tempfile
import os
import logging
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

load_dotenv()

logger = logging.getLogger(__name__)

EPOS_KEYWORDS = ["epos", "sennheiser", "headset", "usb audio"]  # match your device name

class AudioManager:
    def __init__(self):
        self.pa           = pyaudio.PyAudio()
        self.eleven       = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))
        self.input_device  = self._find_device(input=True)
        self.output_device = self._find_device(input=False)

        if self.input_device:
            logger.info(f"Mic  → {self.input_device['name']}")
        else:
            logger.warning("No EPOS mic found — using system default")

        if self.output_device:
            logger.info(f"Speaker → {self.output_device['name']}")
        else:
            logger.warning("No EPOS speaker found — using system default")

    # ── Device discovery ──────────────────────────────────

    def _find_device(self, input: bool) -> dict | None:
        """Find EPOS device by name, fall back to None (system default)."""
        for i in range(self.pa.get_device_count()):
            info = self.pa.get_device_info_by_index(i)
            name = info["name"].lower()
            is_input  = info["maxInputChannels"] > 0
            is_output = info["maxOutputChannels"] > 0
            if input and not is_input:   continue
            if not input and not is_output: continue
            if any(k in name for k in EPOS_KEYWORDS):
                return {"index": i, "name": info["name"]}
        return None

    def list_devices(self) -> dict:
        inputs, outputs = [], []
        for i in range(self.pa.get_device_count()):
            info = self.pa.get_device_info_by_index(i)
            entry = {"index": i, "name": info["name"]}
            if info["maxInputChannels"] > 0:
                inputs.append(entry)
            if info["maxOutputChannels"] > 0:
                outputs.append(entry)
        return {
            "inputs":  inputs,
            "outputs": outputs,
            "active_mic":     self.input_device,
            "active_speaker": self.output_device
        }

    # ── Listen + transcribe ───────────────────────────────

    def listen(self, duration_seconds: int = 5) -> dict:
        RATE     = 16000
        CHUNK    = 1024
        CHANNELS = 1
        FORMAT   = pyaudio.paInt16

        device_index = self.input_device["index"] if self.input_device else None

        logger.info(f"Recording {duration_seconds}s from {self.input_device or 'default'}")

        stream = self.pa.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=CHUNK
        )

        frames = []
        for _ in range(int(RATE / CHUNK * duration_seconds)):
            frames.append(stream.read(CHUNK))

        stream.stop_stream()
        stream.close()

        # Save to temp wav file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        wf = wave.open(tmp_path, "wb")
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(self.pa.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b"".join(frames))
        wf.close()

        # Transcribe with ElevenLabs Scribe
        try:
            with open(tmp_path, "rb") as f:
                result = self.eleven.speech_to_text.convert(
                    file=f, model_id="scribe_v1"
                )
            transcript = result.text.strip()
            language   = getattr(result, "language_code", "unknown")
        except Exception as e:
            logger.error(f"ElevenLabs STT failed: {e}")
            transcript = ""
            language   = "unknown"
        finally:
            os.unlink(tmp_path)

        return {"transcript": transcript, "language": language, "duration_seconds": duration_seconds}

    # ── Text to speech (ElevenLabs) ───────────────────────

    def say(self, text: str, voice: str = "Rachel"):
        logger.info(f"Speaking: {text}")
        try:
            audio_gen = self.eleven.text_to_speech.convert(
                text=text,
                voice_id=voice,
                model_id="eleven_multilingual_v2",
                output_format="mp3_44100_128",
            )
            audio_bytes = b"".join(audio_gen)

            # Save to temp file and play via pyaudio/system
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            # Play the audio file
            os.system(f'start /min "" "{tmp_path}"')
        except Exception as e:
            logger.error(f"ElevenLabs TTS failed: {e}")

    # ── Continuous listening ────────────────────────────────

    def listen_continuous(self, chunk_seconds: int = 5, callback=None):
        """
        Continuously listen and transcribe in a loop.
        Calls callback(transcript_dict) for each chunk.
        Runs forever — meant to be called from a background thread.
        """
        logger.info("Starting continuous listening...")
        while True:
            result = self.listen(duration_seconds=chunk_seconds)
            if result["transcript"]:
                logger.info(f"Heard: {result['transcript']}")
                if callback:
                    callback(result)
