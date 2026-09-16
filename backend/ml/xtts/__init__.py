"""Stub pipeline sintesis suara XTTS-v2 untuk Sonance."""
import os
import struct
import time
import uuid
from typing import Callable, Optional

from backend.ml.base import TTSPipeline


def generate_valid_opus_bytes(duration_seconds: float = 2.0) -> bytes:
    """
    Menghasilkan bytes container Ogg Opus valid minimal untuk stub atau testing.
    Memiliki struktur OggS standar: header OpusHead, OpusTags, dan audio packet dengan granule pos.
    """
    opus_head = b"OpusHead" + struct.pack("<BBHIhB", 1, 1, 0, 48000, 0, 0)
    page1 = bytearray(
        b"OggS" + struct.pack("<BBqIIIB", 0, 2, 0, 12345, 0, 0, 1) + bytes([len(opus_head)]) + opus_head
    )
    opus_tags = b"OpusTags" + struct.pack("<I", 7) + b"Sonance" + struct.pack("<I", 0)
    page2 = bytearray(
        b"OggS" + struct.pack("<BBqIIIB", 0, 0, 0, 12345, 1, 0, 1) + bytes([len(opus_tags)]) + opus_tags
    )
    granule = int(duration_seconds * 48000)
    payload = b"\xf8\xff\xfe"
    page3 = bytearray(
        b"OggS" + struct.pack("<BBqIIIB", 0, 4, granule, 12345, 2, 0, 1) + bytes([len(payload)]) + payload
    )
    return bytes(page1 + page2 + page3)


class XTTSPipeline(TTSPipeline):
    """
    Pipeline stub untuk model XTTS-v2.
    Mensimulasikan sintesis teks menjadi audio berformat Opus.
    """

    def __init__(
        self,
        simulate_failure: bool = False,
        sleep_interval: float = 0.0,
    ):
        self.simulate_failure = simulate_failure
        self.sleep_interval = sleep_interval

    def synthesize(
        self,
        text: str,
        voice_profile_checkpoint_path: str,
        settings: Optional[dict] = None,
        output_dir: str = "/tmp",
        progress_cb: Optional[Callable[[int], None]] = None,
    ) -> str:
        should_fail = (
            self.simulate_failure
            or os.environ.get("SONANCE_SIMULATE_TTS_FAILURE", "").lower() in ("true", "1")
        )

        steps = [25, 50, 75]
        for step in steps:
            if self.sleep_interval > 0:
                time.sleep(self.sleep_interval)
            if progress_cb:
                progress_cb(step)
            if should_fail and step >= 50:
                raise RuntimeError("Simulated XTTS synthesis failure: CUDA out of memory during inference.")

        if should_fail:
            raise RuntimeError("Simulated XTTS synthesis failure: pipeline error.")

        if self.sleep_interval > 0:
            time.sleep(self.sleep_interval)
        if progress_cb:
            progress_cb(100)

        os.makedirs(output_dir, exist_ok=True)
        filename = f"xtts_{uuid.uuid4().hex[:12]}.opus"
        output_path = os.path.join(output_dir, filename)

        opus_bytes = generate_valid_opus_bytes(duration_seconds=2.0)
        with open(output_path, "wb") as f:
            f.write(opus_bytes)

        return output_path
