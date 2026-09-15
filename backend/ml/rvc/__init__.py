"""Stub pipeline training RVC (Retrieval-based Voice Conversion) untuk Sonance."""
import os
import time
import uuid
from typing import Callable, Optional

from backend.ml.base import TrainingPipeline


class RVCPipeline(TrainingPipeline):
    """
    Pipeline stub untuk model RVC.
    Digunakan untuk tipe suara own_voice dan other_person (ADR-007).
    """

    def __init__(
        self,
        simulate_failure: bool = False,
        sleep_interval: float = 0.0,
    ):
        self.simulate_failure = simulate_failure
        self.sleep_interval = sleep_interval

    def train(
        self,
        sample_audio_path: str,
        checkpoint_dir: str,
        progress_cb: Optional[Callable[[int], None]] = None,
    ) -> str:
        should_fail = (
            self.simulate_failure
            or os.environ.get("SONANCE_SIMULATE_TRAINING_FAILURE", "").lower() in ("true", "1")
            or "fail" in os.path.basename(sample_audio_path).lower()
        )

        steps = [25, 50, 75]
        for step in steps:
            if self.sleep_interval > 0:
                time.sleep(self.sleep_interval)
            if progress_cb:
                progress_cb(step)
            if should_fail and step >= 50:
                raise RuntimeError("Simulated RVC training failure: CUDA out of memory during epoch 20.")

        if should_fail:
            raise RuntimeError("Simulated RVC training failure: pipeline error.")

        if self.sleep_interval > 0:
            time.sleep(self.sleep_interval)
        if progress_cb:
            progress_cb(100)

        os.makedirs(checkpoint_dir, exist_ok=True)
        checkpoint_filename = f"rvc_{uuid.uuid4().hex[:12]}.pth"
        checkpoint_path = os.path.join(checkpoint_dir, checkpoint_filename)

        with open(checkpoint_path, "wb") as f:
            f.write(b"SONANCE_MOCK_RVC_CHECKPOINT_PAYLOAD")

        return checkpoint_path
