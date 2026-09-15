"""Worker dan pipeline router untuk pemrosesan training job async.
Wave 7 - Task 13.1.
"""
import logging
import os
import traceback
import uuid
from typing import Any, Dict, List, Optional, Union

from sqlalchemy.orm import Session

from backend.app.core.database import get_session_factory
from backend.app.models.training_job_model import TrainingJob
from backend.app.models.voice_profile_model import VoiceProfile
from backend.app.schemas.voice_profile_schema import SourceType
from backend.app.services.training_job_service import TrainingJobService
from backend.ml.base import TrainingPipeline
from backend.ml.rvc import RVCPipeline
from backend.ml.svc import SVCPipeline

logger = logging.getLogger(__name__)


def select_pipeline(source_type: Union[SourceType, str]) -> TrainingPipeline:
    """
    Routing pipeline training berdasarkan source_type (ADR-007):
    - own_voice / other_person -> RVCPipeline
    - character -> SVCPipeline
    - tipe lainnya -> raise ValueError
    """
    raw_value = source_type.value if hasattr(source_type, "value") else str(source_type)

    if raw_value in (SourceType.own_voice.value, SourceType.other_person.value):
        return RVCPipeline()
    elif raw_value == SourceType.character.value:
        return SVCPipeline()
    else:
        raise ValueError(f"Unknown source_type: {source_type}")


def execute_training_job(
    voice_profile_id: Union[uuid.UUID, str],
    source_type: Union[SourceType, str],
    db: Optional[Session] = None,
    pipeline: Optional[TrainingPipeline] = None,
    training_service: Optional[TrainingJobService] = None,
) -> Dict[str, Any]:
    """
    Consumer task untuk mengeksekusi training job.
    Dapat dijalankan langsung oleh worker queue (RQ/Celery) atau secara in-memory.
    Menjalankan alur: update_start -> update_progress -> complete / fail.
    """
    vp_uuid = (
        voice_profile_id
        if isinstance(voice_profile_id, uuid.UUID)
        else uuid.UUID(str(voice_profile_id))
    )
    service = training_service or TrainingJobService()

    owns_session = False
    session = db
    if session is None:
        factory = get_session_factory()
        session = factory()
        owns_session = True

    try:
        vp = session.get(VoiceProfile, vp_uuid)
        if not vp:
            raise ValueError(f"VoiceProfile dengan ID {vp_uuid} tidak ditemukan.")

        job = session.query(TrainingJob).filter_by(voice_profile_id=vp.id).first()
        if not job:
            raise ValueError(f"TrainingJob untuk VoiceProfile {vp_uuid} tidak ditemukan.")

        # 1. Update status awal: processing
        service.update_start(
            training_job_id=job.id,
            voice_profile_id_or_db=vp.id,
            db=session,
        )

        # 2. Tentukan pipeline yang sesuai
        active_pipeline = pipeline or select_pipeline(source_type)

        # 3. Setup progress callback
        def on_progress(pct: int) -> None:
            service.update_progress(
                training_job_id=job.id,
                progress_pct=pct,
                db=session,
            )

        checkpoint_dir = os.environ.get("SONANCE_CHECKPOINT_DIR", "/tmp/sonance/checkpoints")

        # 4. Eksekusi pipeline
        try:
            checkpoint_path = active_pipeline.train(
                sample_audio_path=vp.sample_audio_path or "",
                checkpoint_dir=checkpoint_dir,
                progress_cb=on_progress,
            )
            service.complete(
                training_job_id=job.id,
                voice_profile_id_or_checkpoint=vp.id,
                checkpoint_path_or_db=checkpoint_path,
                db=session,
            )
            return {
                "status": "completed",
                "training_job_id": str(job.id),
                "voice_profile_id": str(vp.id),
                "checkpoint_path": checkpoint_path,
            }
        except Exception as err:
            logger.exception("Error saat eksekusi pipeline training: %s", err)
            error_summary = str(err) or "Kegagalan pada pipeline training."
            error_log = traceback.format_exc()
            service.fail(
                training_job_id=job.id,
                voice_profile_id_or_error_summary=vp.id,
                error_summary_or_log=error_summary,
                error_log_or_db=error_log,
                db=session,
            )
            return {
                "status": "failed",
                "training_job_id": str(job.id),
                "voice_profile_id": str(vp.id),
                "error": error_summary,
            }

    finally:
        if owns_session:
            session.close()


def process_queue_jobs(
    queue: Any,
    db: Optional[Session] = None,
    max_jobs: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Helper consumer in-memory untuk memproses job dalam queue testing/staged.
    Mendukung queue dengan atribut enqueued_jobs.
    """
    results = []
    if not hasattr(queue, "enqueued_jobs"):
        return results

    jobs_to_process = list(queue.enqueued_jobs)
    if max_jobs is not None:
        jobs_to_process = jobs_to_process[:max_jobs]

    for job_item in jobs_to_process:
        kwargs = job_item.get("kwargs", {})
        vp_id = kwargs.get("voice_profile_id")
        src_type = kwargs.get("source_type")
        if vp_id and src_type:
            res = execute_training_job(
                voice_profile_id=vp_id,
                source_type=src_type,
                db=db,
            )
            results.append(res)

    # Kosongkan job yang telah selesai diproses dari mock queue
    for item in jobs_to_process:
        if item in queue.enqueued_jobs:
            queue.enqueued_jobs.remove(item)

    return results


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Sonance Training Job Worker Daemon")
    parser.add_argument(
        "--burst",
        action="store_true",
        help="Jalankan worker dalam mode burst (keluar setelah antrian kosong)",
    )
    parser.add_argument(
        "--queue",
        default="training",
        help="Nama antrian RQ yang didengarkan (default: training)",
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

