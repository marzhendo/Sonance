"""Unit tests untuk TTSPipeline, XTTSPipeline stub, dan GPUResourceManager.
Wave 5: ML Pipeline Stub & GPU Resource Manager.
"""
import concurrent.futures
import os
import threading
import time
import pytest

from backend.app.core.gpu_manager import GPUResourceManager, get_gpu_manager
from backend.app.services.audio_utils import extract_opus_duration, validate_opus_format
from backend.ml.base import TTSPipeline
from backend.ml.xtts import XTTSPipeline, generate_valid_opus_bytes


class DummyConcreteTTSPipeline(TTSPipeline):
    def synthesize(
        self,
        text: str,
        voice_profile_checkpoint_path: str,
        settings: dict,
        output_dir: str,
        progress_cb=None,
    ) -> str:
        return os.path.join(output_dir, "dummy.opus")


class TestTTSPipelineInterface:
    def test_cannot_instantiate_abstract_ttspipeline(self):
        """TTSPipeline adalah interface abstrak dan tidak dapat diinstansiasi langsung."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            TTSPipeline()

    def test_cannot_instantiate_subclass_without_synthesize(self):
        """Subclass yang tidak mengimplementasikan synthesize melempar TypeError."""
        class IncompletePipeline(TTSPipeline):
            pass

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompletePipeline()

    def test_concrete_subclass_can_be_instantiated(self, tmp_path):
        """Subclass yang mengimplementasikan synthesize dapat diinstansiasi dan dipanggil."""
        pipeline = DummyConcreteTTSPipeline()
        result = pipeline.synthesize(
            text="Halo",
            voice_profile_checkpoint_path="/models/chk.pth",
            settings={},
            output_dir=str(tmp_path),
        )
        assert result.endswith("dummy.opus")


class TestXTTSPipelineStub:
    def test_generate_valid_opus_bytes_utility(self):
        """generate_valid_opus_bytes menghasilkan audio Opus valid dengan header OggS dan OpusHead."""
        opus_data = generate_valid_opus_bytes(duration_seconds=2.5)
        validate_opus_format(opus_data)
        duration = extract_opus_duration(opus_data)
        assert abs(duration - 2.5) < 0.1

    def test_synthesize_success(self, tmp_path):
        """synthesize menghasilkan file Opus yang valid dan memanggil callback progress hingga 100%."""
        pipeline = XTTSPipeline(simulate_failure=False, sleep_interval=0.0)
        progress_records = []

        def on_progress(p: int):
            progress_records.append(p)

        output_file = pipeline.synthesize(
            text="Halo dunia, ini pengujian sintesis suara.",
            voice_profile_checkpoint_path="/checkpoints/model.pth",
            settings={"speed": 1.0},
            output_dir=str(tmp_path),
            progress_cb=on_progress,
        )

        assert os.path.isfile(output_file)
        assert output_file.endswith(".opus")
        assert progress_records == [25, 50, 75, 100]

        with open(output_file, "rb") as f:
            data = f.read()
        validate_opus_format(data)

    def test_synthesize_with_sleep_interval(self, tmp_path):
        """synthesize menghormati sleep_interval yang diberikan."""
        pipeline = XTTSPipeline(simulate_failure=False, sleep_interval=0.02)
        start = time.perf_counter()
        pipeline.synthesize(
            text="Pengujian waktu jeda.",
            voice_profile_checkpoint_path="/checkpoints/model.pth",
            settings={},
            output_dir=str(tmp_path),
        )
        elapsed = time.perf_counter() - start
        assert elapsed >= 0.05

    def test_synthesize_failure_via_constructor(self, tmp_path):
        """synthesize melempar RuntimeError ketika simulate_failure=True."""
        pipeline = XTTSPipeline(simulate_failure=True)
        progress_records = []

        with pytest.raises(RuntimeError, match="Simulated XTTS synthesis failure"):
            pipeline.synthesize(
                text="Teks sintesis gagal",
                voice_profile_checkpoint_path="/checkpoints/model.pth",
                settings={},
                output_dir=str(tmp_path),
                progress_cb=lambda p: progress_records.append(p),
            )

        assert 25 in progress_records
        assert 100 not in progress_records

    def test_synthesize_failure_via_env_var(self, tmp_path, monkeypatch):
        """synthesize melempar RuntimeError ketika SONANCE_SIMULATE_TTS_FAILURE bernilai 1 atau true."""
        monkeypatch.setenv("SONANCE_SIMULATE_TTS_FAILURE", "1")
        pipeline = XTTSPipeline()

        with pytest.raises(RuntimeError, match="Simulated XTTS synthesis failure"):
            pipeline.synthesize(
                text="Teks sintesis gagal via env",
                voice_profile_checkpoint_path="/checkpoints/model.pth",
                settings={},
                output_dir=str(tmp_path),
            )

    def test_synthesize_text_containing_fail_keyword_does_not_fail(self, tmp_path):
        """Teks yang memuat kata 'fail' tidak memicu kegagalan kecuali flag atau env var aktif."""
        pipeline = XTTSPipeline(simulate_failure=False)
        output_file = pipeline.synthesize(
            text="Kalimat ini sengaja memuat kata fail dan failure tanpa memicu kegagalan.",
            voice_profile_checkpoint_path="/checkpoints/model.pth",
            settings={},
            output_dir=str(tmp_path),
        )
        assert os.path.isfile(output_file)
        assert output_file.endswith(".opus")


class TestGPUResourceManager:
    @pytest.fixture(autouse=True)
    def clean_gpu_state(self):
        """Memastikan state GPU selalu bersih sebelum dan sesudah tiap test."""
        manager = get_gpu_manager()
        manager.reset()
        yield
        manager.reset()

    def test_singleton_identity(self):
        """GPUResourceManager menerapkan singleton pattern."""
        m1 = GPUResourceManager()
        m2 = GPUResourceManager()
        m3 = get_gpu_manager()
        assert m1 is m2
        assert m2 is m3

    def test_initial_unlocked_state(self):
        """Status awal GPU manager adalah tidak terkunci."""
        manager = get_gpu_manager()
        assert manager.is_locked() is False
        assert manager.get_holder() is None
        assert manager.get_locked_at() is None

    def test_acquire_lock_invalid_session_raises_value_error(self):
        """acquire_lock melempar ValueError jika session_id kosong atau whitespace."""
        manager = get_gpu_manager()
        with pytest.raises(ValueError, match="session_id harus berupa string"):
            manager.acquire_lock("")

        with pytest.raises(ValueError, match="session_id harus berupa string"):
            manager.acquire_lock("   ")

        with pytest.raises(ValueError, match="session_id harus berupa string"):
            manager.acquire_lock(None)

    def test_acquire_and_release_lock_success(self):
        """acquire_lock sukses mengunci GPU dan release_lock melepaskannya."""
        manager = get_gpu_manager()

        acquired = manager.acquire_lock("session-101")
        assert acquired is True
        assert manager.is_locked() is True
        assert manager.get_holder() == "session-101"
        assert manager.get_locked_at() is not None

        released = manager.release_lock("session-101")
        assert released is True
        assert manager.is_locked() is False
        assert manager.get_holder() is None
        assert manager.get_locked_at() is None

    def test_acquire_lock_idempotent_for_same_holder(self):
        """Pemegang lock yang sama memanggil acquire_lock kembali mendapatkan True."""
        manager = get_gpu_manager()
        assert manager.acquire_lock("session-101") is True
        assert manager.acquire_lock("session-101") is True
        assert manager.get_holder() == "session-101"

    def test_acquire_lock_conflict_returns_false(self):
        """Sesi lain yang mencoba acquire saat GPU sudah terkunci mendapatkan False."""
        manager = get_gpu_manager()
        assert manager.acquire_lock("session-primary") is True

        conflict_result = manager.acquire_lock("session-secondary")
        assert conflict_result is False
        assert manager.is_locked() is True
        assert manager.get_holder() == "session-primary"

    def test_release_lock_unauthorized_fails(self):
        """Sesi yang bukan pemegang lock tidak dapat melepaskan lock."""
        manager = get_gpu_manager()
        manager.acquire_lock("session-owner")

        released = manager.release_lock("session-intruder")
        assert released is False
        assert manager.is_locked() is True
        assert manager.get_holder() == "session-owner"

    def test_release_lock_force_override(self):
        """release_lock dengan force=True dapat melepaskan lock tanpa memandang holder."""
        manager = get_gpu_manager()
        manager.acquire_lock("session-owner")

        released = manager.release_lock(force=True)
        assert released is True
        assert manager.is_locked() is False
        assert manager.get_holder() is None

    def test_release_lock_when_already_unlocked(self):
        """release_lock saat tidak terkunci mengembalikan True."""
        manager = get_gpu_manager()
        assert manager.release_lock("any-session") is True

    def test_concurrent_acquire_lock(self):
        """
        Simulasi 20 thread mencoba acquire_lock secara simultan.
        Tepat satu thread yang berhasil (True), sisanya gagal (False).
        """
        manager = get_gpu_manager()
        num_threads = 20
        start_event = threading.Event()
        results = {}

        def worker(thread_idx: int):
            session_id = f"session-thread-{thread_idx}"
            start_event.wait()
            success = manager.acquire_lock(session_id)
            results[session_id] = success

        threads = []
        for i in range(num_threads):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        start_event.set()

        for t in threads:
            t.join()

        success_count = sum(1 for v in results.values() if v is True)
        fail_count = sum(1 for v in results.values() if v is False)

        assert success_count == 1
        assert fail_count == num_threads - 1
        assert manager.is_locked() is True

        winning_session = [k for k, v in results.items() if v is True][0]
        assert manager.get_holder() == winning_session

        assert manager.release_lock(winning_session) is True
        assert manager.is_locked() is False
