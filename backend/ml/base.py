"""Kontrak dasar pipeline machine learning untuk Sonance."""
from abc import ABC, abstractmethod
from typing import Callable, Optional


class TrainingPipeline(ABC):
    """
    Interface abstrak untuk semua pipeline training model suara.
    Menerapkan dependency inversion agar implementasi nyata (RVC/SVC/XTTS)
    dapat diganti tanpa memodifikasi layer worker atau service.
    """

    @abstractmethod
    def train(
        self,
        sample_audio_path: str,
        checkpoint_dir: str,
        progress_cb: Optional[Callable[[int], None]] = None,
    ) -> str:
        """
        Menjalankan proses training model suara dari sample audio.

        Args:
            sample_audio_path: Path ke file sample audio sumber (Opus).
            checkpoint_dir: Direktori tempat menyimpan file checkpoint model.
            progress_cb: Callback opsional untuk menerima update progress persentase (0-100).

        Returns:
            str: Path ke file model checkpoint (.pth) yang dihasilkan.

        Raises:
            Exception: Jika proses training gagal.
        """
        pass
