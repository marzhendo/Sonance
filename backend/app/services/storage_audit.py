"""Utilitas audit dan verifikasi konsistensi file storage dan database untuk Sonance.
Memastikan integritas dua arah: tidak ada file fisik yatim (orphan) di disk,
dan tidak ada pointer file hilang (missing) di database.
"""
import os
from pathlib import Path
from typing import Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.tts_job_model import TTSJob
from backend.app.models.voice_profile_model import VoiceProfile


def audit_storage_consistency(
    db: Session,
    sample_dir: Optional[str] = None,
    checkpoint_dir: Optional[str] = None,
    tts_output_dir: Optional[str] = None,
) -> Dict[str, List[str]]:
    """
    Memeriksa konsistensi dua arah antara database dan media penyimpanan (storage disk):
    1. missing_files: Path file yang tercatat di DB tetapi file fisiknya tidak ditemukan di disk.
    2. orphan_files: File fisik di storage disk yang tidak memiliki record pemilik di DB.
    3. synced_files: File yang sinkron dan valid di kedua sisi (DB dan disk).
    """
    s_dir = Path(sample_dir or os.environ.get("SONANCE_SAMPLE_AUDIO_DIR", "/tmp/sonance/samples")).resolve()
    c_dir = Path(checkpoint_dir or os.environ.get("SONANCE_CHECKPOINT_DIR", "/tmp/sonance/checkpoints")).resolve()
    t_dir = Path(tts_output_dir or os.environ.get("SONANCE_TTS_OUTPUT_DIR", "/tmp/sonance/tts_output")).resolve()

    missing_files: List[str] = []
    synced_files: List[str] = []

    # 1. Kumpulkan semua path file yang tercatat di database
    tracked_db_paths = set()

    # VoiceProfile: sample_audio_path dan model_checkpoint_path
    vp_records = db.scalars(select(VoiceProfile)).all()
    for vp in vp_records:
        if vp.sample_audio_path:
            norm_path = Path(vp.sample_audio_path).resolve()
            tracked_db_paths.add(str(norm_path))
            if norm_path.is_file():
                synced_files.append(str(norm_path))
            else:
                missing_files.append(str(norm_path))

        if vp.model_checkpoint_path:
            norm_path = Path(vp.model_checkpoint_path).resolve()
            tracked_db_paths.add(str(norm_path))
            if norm_path.is_file():
                synced_files.append(str(norm_path))
            else:
                missing_files.append(str(norm_path))

    # TTSJob: output_audio_path (untuk job yang berstatus completed)
    tts_records = db.scalars(
        select(TTSJob).where(TTSJob.status == "completed")
    ).all()
    for job in tts_records:
        if job.output_audio_path:
            norm_path = Path(job.output_audio_path).resolve()
            tracked_db_paths.add(str(norm_path))
            if norm_path.is_file():
                synced_files.append(str(norm_path))
            else:
                missing_files.append(str(norm_path))

    # 2. Pindai file fisik di direktori storage untuk mendeteksi orphan files
    orphan_files: List[str] = []

    monitored_dirs = [s_dir, c_dir, t_dir]
    for d in monitored_dirs:
        if d.is_dir():
            for entry in d.rglob("*"):
                if entry.is_file():
                    resolved_file = str(entry.resolve())
                    if resolved_file not in tracked_db_paths:
                        orphan_files.append(resolved_file)

    return {
        "missing_files": sorted(list(set(missing_files))),
        "orphan_files": sorted(list(set(orphan_files))),
        "synced_files": sorted(list(set(synced_files))),
    }


def is_storage_consistent(
    db: Session,
    sample_dir: Optional[str] = None,
    checkpoint_dir: Optional[str] = None,
    tts_output_dir: Optional[str] = None,
) -> bool:
    """Mengembalikan True jika tidak ada missing files maupun orphan files."""
    audit = audit_storage_consistency(
        db=db,
        sample_dir=sample_dir,
        checkpoint_dir=checkpoint_dir,
        tts_output_dir=tts_output_dir,
    )
    return len(audit["missing_files"]) == 0 and len(audit["orphan_files"]) == 0
