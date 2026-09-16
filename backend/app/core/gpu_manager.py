"""Pengelola alokasi resource GPU untuk koordinasi sesi real-time dan TTS offline."""
import threading
from datetime import datetime, timezone
from typing import Optional


class GPUResourceManager:
    """
    Singleton thread-safe coordinator untuk alokasi GPU.
    Ketika sesi real-time voice changer aktif, GPU di-lock sehingga job offline TTS
    harus menunggu sampai GPU dilepaskan kembali.
    """

    _instance: Optional["GPUResourceManager"] = None
    _class_lock = threading.Lock()

    def __new__(cls, *args, **kwargs) -> "GPUResourceManager":
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._lock = threading.Lock()
        self._is_locked: bool = False
        self._holder: Optional[str] = None
        self._locked_at: Optional[datetime] = None
        self._initialized = True

    def is_locked(self) -> bool:
        """Mengecek apakah GPU sedang terkunci oleh sesi real-time."""
        with self._lock:
            return self._is_locked

    def acquire_lock(self, session_id: str) -> bool:
        """
        Mencoba mendapatkan lock eksklusif GPU untuk session_id yang diberikan.

        Returns:
            bool: True jika berhasil memperoleh lock, False jika GPU sudah dipegang sesi lain.

        Raises:
            ValueError: Jika session_id kosong atau bukan string valid.
        """
        if not session_id or not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id harus berupa string yang tidak kosong.")

        clean_id = session_id.strip()
        with self._lock:
            if self._is_locked:
                if self._holder == clean_id:
                    return True
                return False
            self._is_locked = True
            self._holder = clean_id
            self._locked_at = datetime.now(timezone.utc)
            return True

    def release_lock(self, session_id: Optional[str] = None, force: bool = False) -> bool:
        """
        Melepaskan lock GPU. Hanya pemegang lock yang sah atau pemanggilan dengan force=True
        yang diizinkan melepaskan lock.

        Returns:
            bool: True jika lock berhasil dilepas (atau memang sedang tidak terkunci),
                  False jika session_id bukan pemegang lock yang sah.
        """
        with self._lock:
            if not self._is_locked:
                return True
            if force or (session_id and self._holder == session_id.strip()):
                self._is_locked = False
                self._holder = None
                self._locked_at = None
                return True
            return False

    def get_holder(self) -> Optional[str]:
        """Mengembalikan identifier sesi pemegang lock saat ini, jika ada."""
        with self._lock:
            return self._holder

    def get_locked_at(self) -> Optional[datetime]:
        """Mengembalikan timestamp kapan lock GPU di-acquire, jika ada."""
        with self._lock:
            return self._locked_at

    def reset(self) -> None:
        """Mereset status lock ke kondisi awal tidak terkunci (untuk keperluan testing)."""
        with self._lock:
            self._is_locked = False
            self._holder = None
            self._locked_at = None


gpu_resource_manager = GPUResourceManager()


def get_gpu_manager() -> GPUResourceManager:
    """Mengembalikan instans singleton GPUResourceManager."""
    return gpu_resource_manager
