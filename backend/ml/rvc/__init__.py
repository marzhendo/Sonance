"""Stub pipeline training RVC (Retrieval-based Voice Conversion) untuk Sonance."""
import os
import time
import uuid
from typing import Any, Callable, Optional, Union

from backend.ml.base import TrainingPipeline, VoiceConversionPipeline


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


class RVCRealtimePipeline(VoiceConversionPipeline):
    """
    Pipeline stub untuk real-time voice conversion RVC.
    Mensimulasikan pemuatan model on-demand dan konversi audio frame-by-frame.
    """

    def __init__(
        self,
        simulate_failure: bool = False,
        cold_start_delay: float = 0.0,
        inference_delay: float = 0.0,
    ):
        self.simulate_failure = simulate_failure
        self.cold_start_delay = cold_start_delay
        self.inference_delay = inference_delay
        self._is_loaded: bool = False
        self._checkpoint_path: Optional[str] = None

    def load_model(self, checkpoint_path: str) -> None:
        """
        Memuat model ke memori GPU on-demand saat sesi dimulai.
        """
        should_fail = (
            self.simulate_failure
            or os.environ.get("SONANCE_SIMULATE_VC_FAILURE", "").lower() in ("true", "1")
        )
        if should_fail:
            raise RuntimeError("Simulated RVC model load failure: GPU memory allocation error.")

        if self.cold_start_delay > 0:
            time.sleep(self.cold_start_delay)

        self._is_loaded = True
        self._checkpoint_path = checkpoint_path

    def unload_model(self) -> None:
        """
        Membongkar model dari memori GPU setelah sesi berakhir.
        """
        self._is_loaded = False
        self._checkpoint_path = None

    def is_loaded(self) -> bool:
        """
        Mengecek apakah model saat ini sedang termuat.
        """
        return self._is_loaded

    def convert_chunk(
        self,
        pcm_bytes: bytes,
        settings: Optional[Union[dict, Any]] = None,
    ) -> bytes:
        """
        Mengonversi satu frame audio raw PCM.
        """
        if not self._is_loaded:
            raise RuntimeError("Model RVC belum dimuat ke memori. Panggil load_model() terlebih dahulu.")

        should_fail = (
            self.simulate_failure
            or os.environ.get("SONANCE_SIMULATE_VC_FAILURE", "").lower() in ("true", "1")
        )
        if should_fail:
            raise RuntimeError("Simulated RVC inference failure: computation error during voice conversion.")

        if self.inference_delay > 0:
            time.sleep(self.inference_delay)

        # Untuk stub, return bytes dengan panjang yang sama persis
        return bytes(pcm_bytes)

