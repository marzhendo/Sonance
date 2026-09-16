"""Integration tests untuk audit konsistensi file storage dan database (Task 9: Checkpoint Final).
Memverifikasi:
1. Tidak ada orphan file di storage disk yang tidak memiliki record di DB.
2. Tidak ada record DB yang menunjuk ke file yang sudah hilang dari disk.
3. Sinkronisasi konsisten pada seluruh siklus hidup VoiceProfile dan TTSJob.
"""
from pathlib import Path

from backend.app.services.storage_audit import audit_storage_consistency, is_storage_consistent
from backend.app.services.voice_profile_service import VoiceProfileService
from backend.ml.xtts import generate_valid_opus_bytes


class TestStorageConsistencyAudit:

    def test_clean_storage_is_consistent(self, db_session, tmp_path):
        """Storage kosong tanpa record DB terverifikasi konsisten (0 missing, 0 orphan)."""
        s_dir = tmp_path / "samples"
        c_dir = tmp_path / "checkpoints"
        t_dir = tmp_path / "tts_output"
        s_dir.mkdir()
        c_dir.mkdir()
        t_dir.mkdir()

        res = audit_storage_consistency(
            db=db_session,
            sample_dir=str(s_dir),
            checkpoint_dir=str(c_dir),
            tts_output_dir=str(t_dir),
        )

        assert res["missing_files"] == []
        assert res["orphan_files"] == []
        assert is_storage_consistent(
            db=db_session,
            sample_dir=str(s_dir),
            checkpoint_dir=str(c_dir),
            tts_output_dir=str(t_dir),
        ) is True

    def test_valid_voice_profile_and_tts_files_are_synced(
        self, db_session, test_user, make_voice_profile, make_tts_job, tmp_path
    ):
        """File sample, checkpoint, dan output audio yang terdaftar di DB diakui sebagai synced."""
        s_dir = tmp_path / "samples"
        c_dir = tmp_path / "checkpoints"
        t_dir = tmp_path / "tts_output"
        s_dir.mkdir()
        c_dir.mkdir()
        t_dir.mkdir()

        sample_file = s_dir / "sample.opus"
        sample_file.write_bytes(generate_valid_opus_bytes(2.0))

        chk_file = c_dir / "model.pth"
        chk_file.write_bytes(b"MODEL_CHECKPOINT_DATA")

        vp = make_voice_profile(
            user=test_user,
            status="ready",
            sample_audio_path=str(sample_file),
            model_checkpoint_path=str(chk_file),
        )

        tts_file = t_dir / "output.opus"
        tts_file.write_bytes(generate_valid_opus_bytes(2.0))

        make_tts_job(
            user=test_user,
            voice_profile=vp,
            status="completed",
            output_audio_path=str(tts_file),
        )

        res = audit_storage_consistency(
            db=db_session,
            sample_dir=str(s_dir),
            checkpoint_dir=str(c_dir),
            tts_output_dir=str(t_dir),
        )

        assert len(res["missing_files"]) == 0
        assert len(res["orphan_files"]) == 0
        assert len(res["synced_files"]) == 3
        assert is_storage_consistent(
            db=db_session,
            sample_dir=str(s_dir),
            checkpoint_dir=str(c_dir),
            tts_output_dir=str(t_dir),
        ) is True

    def test_orphan_file_detected_in_storage(
        self, db_session, test_user, make_voice_profile, tmp_path
    ):
        """File di storage yang tidak memiliki record pemilik di DB terdeteksi sebagai orphan."""
        s_dir = tmp_path / "samples"
        c_dir = tmp_path / "checkpoints"
        t_dir = tmp_path / "tts_output"
        s_dir.mkdir()
        c_dir.mkdir()
        t_dir.mkdir()

        # File valid yang terdaftar di DB
        sample_file = s_dir / "sample_registered.opus"
        sample_file.write_bytes(generate_valid_opus_bytes(2.0))
        make_voice_profile(
            user=test_user,
            status="ready",
            sample_audio_path=str(sample_file),
        )

        # File yatim (orphan) tanpa referensi di DB
        orphan_1 = s_dir / "untracked_sample.opus"
        orphan_1.write_bytes(b"ORPHAN_SAMPLE")

        orphan_2 = t_dir / "untracked_tts.opus"
        orphan_2.write_bytes(b"ORPHAN_TTS")

        res = audit_storage_consistency(
            db=db_session,
            sample_dir=str(s_dir),
            checkpoint_dir=str(c_dir),
            tts_output_dir=str(t_dir),
        )

        assert len(res["orphan_files"]) == 2
        assert str(orphan_1.resolve()) in res["orphan_files"]
        assert str(orphan_2.resolve()) in res["orphan_files"]
        assert is_storage_consistent(
            db=db_session,
            sample_dir=str(s_dir),
            checkpoint_dir=str(c_dir),
            tts_output_dir=str(t_dir),
        ) is False

    def test_missing_file_detected_when_db_pointer_dangles(
        self, db_session, test_user, make_voice_profile, tmp_path
    ):
        """Record di DB yang menunjuk ke file yang sudah hilang terdeteksi sebagai missing_files."""
        s_dir = tmp_path / "samples"
        c_dir = tmp_path / "checkpoints"
        t_dir = tmp_path / "tts_output"
        s_dir.mkdir()
        c_dir.mkdir()
        t_dir.mkdir()

        # Path file yang sengaja tidak pernah dibuat di disk
        ghost_path = s_dir / "ghost_audio.opus"
        make_voice_profile(
            user=test_user,
            status="ready",
            sample_audio_path=str(ghost_path),
        )

        res = audit_storage_consistency(
            db=db_session,
            sample_dir=str(s_dir),
            checkpoint_dir=str(c_dir),
            tts_output_dir=str(t_dir),
        )

        assert len(res["missing_files"]) == 1
        assert str(ghost_path.resolve()) in res["missing_files"]
        assert is_storage_consistent(
            db=db_session,
            sample_dir=str(s_dir),
            checkpoint_dir=str(c_dir),
            tts_output_dir=str(t_dir),
        ) is False

    def test_delete_lifecycle_leaves_no_orphans(
        self, db_session, test_user, make_voice_profile, tmp_path
    ):
        """Penghapusan voice profile membersihkan file fisik dan record DB tanpa meninggalkan orphan."""
        s_dir = tmp_path / "samples"
        c_dir = tmp_path / "checkpoints"
        t_dir = tmp_path / "tts_output"
        s_dir.mkdir()
        c_dir.mkdir()
        t_dir.mkdir()

        sample_file = s_dir / "vp_sample.opus"
        sample_file.write_bytes(generate_valid_opus_bytes(2.0))

        chk_file = c_dir / "vp_model.pth"
        chk_file.write_bytes(b"CHECKPOINT_DATA")

        vp = make_voice_profile(
            user=test_user,
            status="ready",
            sample_audio_path=str(sample_file),
            model_checkpoint_path=str(chk_file),
        )

        service = VoiceProfileService()
        service.delete(voice_profile_id=vp.id, user_id=test_user.id, db=db_session)

        res = audit_storage_consistency(
            db=db_session,
            sample_dir=str(s_dir),
            checkpoint_dir=str(c_dir),
            tts_output_dir=str(t_dir),
        )

        assert len(res["missing_files"]) == 0
        assert len(res["orphan_files"]) == 0
        assert is_storage_consistent(
            db=db_session,
            sample_dir=str(s_dir),
            checkpoint_dir=str(c_dir),
            tts_output_dir=str(t_dir),
        ) is True
