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


class TTSPipeline(ABC):
    """
    Interface abstrak untuk semua pipeline text-to-speech (TTS).
    Menerapkan dependency inversion agar implementasi nyata (XTTS-v2)
    dapat diganti tanpa memodifikasi layer worker atau service.
    """

    @abstractmethod
    def synthesize(
        self,
        text: str,
        voice_profile_checkpoint_path: str,
        settings: dict,
        output_dir: str,
        progress_cb: Optional[Callable[[int], None]] = None,
    ) -> str:
        """
        Menjalankan proses sintesis teks menjadi audio berbasis model profil suara.

        Args:
            text: Teks yang akan disintesis.
            voice_profile_checkpoint_path: Path ke file model checkpoint suara.
            settings: Dictionary konfigurasi sintesis (language, speed, pitch_shift, dsb).
            output_dir: Direktori tempat menyimpan file audio hasil sintesis (.opus).
            progress_cb: Callback opsional untuk menerima update progress persentase (0-100).

        Returns:
            str: Path ke file audio (.opus) yang dihasilkan.

        Raises:
            Exception: Jika proses sintesis gagal.
        """
        pass
