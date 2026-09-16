"""Worker dan task executor untuk pemrosesan TTS job secara asynchronous.
Menangani GPU lock wait, timeout 30 menit, dan orkestrasi sintesis suara.
"""
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Union

from sqlalchemy.orm import Session

from backend.app.core.database import get_session_factory
from backend.app.core.gpu_manager import GPUResourceManager, get_gpu_manager
from backend.app.models.tts_job_model import TTSJob
from backend.app.models.voice_profile_model import VoiceProfile
from backend.app.schemas.tts_job_schema import TTSJobStatus
from backend.app.services.tts_job_service import TTSJobService
from backend.ml.base import TTSPipeline
from backend.ml.xtts import XTTSPipeline

logger = logging.getLogger(__name__)

DEFAULT_TTS_QUEUE = "tts"
DEFAULT_GPU_TIMEOUT_SECONDS = 1800.0


def execute_tts_job(
    tts_job_id: Union[uuid.UUID, str],
    db: Optional[Session] = None,
    pipeline: Optional[TTSPipeline] = None,
    gpu_manager: Optional[GPUResourceManager] = None,
    tts_service: Optional[TTSJobService] = None,
    output_dir: Optional[str] = None,
    poll_interval: float = 0.5,
    timeout_seconds: float = DEFAULT_GPU_TIMEOUT_SECONDS,
    time_provider: Optional[Callable[[], datetime]] = None,
    max_poll_iterations: Optional[int] = None,
    progress_cb: Optional[Callable[[int], None]] = None,
) -> Dict[str, Any]:
    """
    Consumer task untuk mengeksekusi TTS job.
    Memeriksa ketersediaan GPU dari sesi real-time:
    - Jika GPU terkunci, menunda proses dan memantau timeout 30 menit (1800 detik).
    - Jika timeout terlewati, membatalkan job menjadi failed (tanpa auto-retry).
    - Jika GPU bebas, memanggil update_start, mengeksekusi pipeline sintesis,
      dan memanggil complete atau fail.
    """
    j_uuid = tts_job_id if isinstance(tts_job_id, uuid.UUID) else uuid.UUID(str(tts_job_id))
    service = tts_service or TTSJobService()
    gpu_mgr = gpu_manager or get_gpu_manager()
    now_fn = time_provider or (lambda: datetime.now(timezone.utc))

    owns_session = False
    session = db
    if session is None:
        factory = get_session_factory()
        session = factory()
        owns_session = True

    try:
        job = session.get(TTSJob, j_uuid)
        if not job:
            raise ValueError(f"TTSJob dengan ID {j_uuid} tidak ditemukan.")

        if job.status in (TTSJobStatus.completed.value, TTSJobStatus.failed.value):
            logger.warning("TTSJob %s sudah berstatus terminal: %s.", job.id, job.status)
            return {
                "status": job.status,
                "tts_job_id": str(job.id),
                "error": f"Job already in terminal status: {job.status}",
            }

        # 1. Pengecekan GPU Lock loop
        iteration_count = 0
        while gpu_mgr.is_locked():
            if job.gpu_wait_started_at is None:
                service.record_gpu_wait_start(job_id=job.id, db=session)
                session.refresh(job)

            current_now = now_fn()
            wait_start = job.gpu_wait_started_at
            if wait_start.tzinfo is None:
                wait_start = wait_start.replace(tzinfo=timezone.utc)
            elapsed = (current_now - wait_start).total_seconds()

            if elapsed >= timeout_seconds:
                logger.warning(
                    "Job %s dibatalkan karena timeout menunggu GPU selama %.1f detik (limit: %.1f).",
                    job.id,
                    elapsed,
                    timeout_seconds,
                )
                service.fail_due_to_gpu_timeout(job_id=job.id, db=session)
                return {
                    "status": "failed",
                    "tts_job_id": str(job.id),
                    "error": "GPU wait timeout",
                }

            if max_poll_iterations is not None:
                iteration_count += 1
                if iteration_count >= max_poll_iterations:
                    return {
                        "status": "waiting_for_gpu",
                        "tts_job_id": str(job.id),
                        "gpu_wait_started_at": (
                            job.gpu_wait_started_at.isoformat()
                            if job.gpu_wait_started_at
                            else None
                        ),
                    }

            if poll_interval > 0:
                time.sleep(poll_interval)

        # 2. Transisi state awal pemrosesan: processing
        service.update_start(job_id=job.id, db=session)

        # 3. Ambil voice profile terkait
        vp = session.get(VoiceProfile, job.voice_profile_id)
        if not vp:
            raise ValueError(f"VoiceProfile dengan ID {job.voice_profile_id} tidak ditemukan.")

        checkpoint_path = vp.model_checkpoint_path or vp.sample_audio_path or ""
        active_pipeline = pipeline or XTTSPipeline()

        dest_dir = output_dir or os.environ.get(
            "SONANCE_TTS_OUTPUT_DIR", "/tmp/sonance/tts_output"
        )
        os.makedirs(dest_dir, exist_ok=True)

        # 4. Eksekusi pipeline sintesis
        try:
            output_path = active_pipeline.synthesize(
                text=job.input_text,
                voice_profile_checkpoint_path=checkpoint_path,
                settings=job.settings or {},
                output_dir=dest_dir,
                progress_cb=progress_cb,
            )
            service.complete(
                job_id=job.id,
                output_audio_path=output_path,
                db=session,
            )
            return {
                "status": "completed",
                "tts_job_id": str(job.id),
                "output_audio_path": output_path,
            }
        except Exception as err:
            logger.exception("Error saat eksekusi pipeline TTS: %s", err)
            error_summary = str(err) or "Kegagalan pada pipeline sintesis TTS."
            service.fail(
                job_id=job.id,
                error_message=error_summary,
                db=session,
            )
            return {
                "status": "failed",
                "tts_job_id": str(job.id),
                "error": error_summary,
            }

    finally:
        if owns_session:
            session.close()


def process_queue_jobs(
    queue: Any,
    db: Optional[Session] = None,
    max_jobs: Optional[int] = None,
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """
    Helper consumer in-memory untuk memproses job dalam antrian testing/staged.
    Mendukung queue dengan atribut enqueued_jobs.
    """
    results = []
    if not hasattr(queue, "enqueued_jobs"):
        return results

    jobs_to_process = list(queue.enqueued_jobs)
    if max_jobs is not None:
        jobs_to_process = jobs_to_process[:max_jobs]

    for job_item in jobs_to_process:
        job_kwargs = job_item.get("kwargs", {})
        tts_id = job_kwargs.get("tts_job_id")
        if tts_id:
            res = execute_tts_job(
                tts_job_id=tts_id,
                db=db,
                **kwargs,
            )
            results.append(res)

    for item in jobs_to_process:
        if item in queue.enqueued_jobs:
            queue.enqueued_jobs.remove(item)

    return results


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Sonance TTS Job Worker Daemon")
    parser.add_argument(
        "--burst",
        action="store_true",
        help="Jalankan worker dalam mode burst (keluar setelah antrian kosong)",
    )
    parser.add_argument(
        "--queue",
        default=DEFAULT_TTS_QUEUE,
        help=f"Nama antrian RQ yang didengarkan (default: {DEFAULT_TTS_QUEUE})",
    )
    args = parser.parse_args()

    redis_url = os.environ.get("SONANCE_REDIS_URL", "").strip()
    if not redis_url:
        print(
            "ERROR: SONANCE_REDIS_URL tidak diset. Worker memerlukan koneksi Redis untuk berjalan.",
            file=sys.stderr,
        )
        print(
            "Silakan set environment variable: export SONANCE_REDIS_URL=redis://localhost:6379/0",
            file=sys.stderr,
        )
        sys.exit(1)

    import redis
    from rq import Connection, Queue, Worker

    print(f"[*] Menghubungkan ke Redis: {redis_url}")
    conn = redis.from_url(redis_url)
    with Connection(conn):
        worker = Worker([Queue(args.queue)])
        print(f"[*] Worker aktif mendengarkan antrian '{args.queue}' (burst={args.burst})")
        worker.work(burst=args.burst)
