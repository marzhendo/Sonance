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


class VoiceConversionPipeline(ABC):
    """
    Interface abstrak untuk semua pipeline real-time voice conversion.
    Menerapkan pemrosesan audio berbasis chunk secara real-time.
    """

    @abstractmethod
    def load_model(self, checkpoint_path: str) -> None:
        """
        Memuat bobot model checkpoint ke dalam memori GPU on-demand.

        Args:
            checkpoint_path: Path absolut ke file model checkpoint (.pth).

        Raises:
            Exception: Jika pemuatan model gagal.
        """
        pass

    @abstractmethod
    def unload_model(self) -> None:
        """Membongkar model dari memori GPU untuk menghemat VRAM."""
        pass

    @abstractmethod
    def convert_chunk(
        self,
        pcm_bytes: bytes,
        settings: dict,
    ) -> bytes:
        """
        Mengonversi satu frame audio raw PCM menjadi suara target.

        Args:
            pcm_bytes: Potongan data audio PCM input (16-bit mono).
            settings: Konfigurasi konversi suara (pitch_shift, sample_rate, dsb).

        Returns:
            bytes: Potongan data audio PCM hasil konversi.

        Raises:
            Exception: Jika inferensi gagal atau model belum dimuat.
        """
        pass

    @abstractmethod
    def is_loaded(self) -> bool:
        """
        Mengecek apakah model saat ini sedang termuat di memori.

        Returns:
            bool: True jika model sedang aktif dimuat, False jika tidak.
        """
        pass

