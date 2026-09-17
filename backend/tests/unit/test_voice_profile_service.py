"""Tests untuk VoiceProfileService.
Wave 4: Service Layer.
"""
import io
import os
import uuid
from unittest.mock import patch

import pytest
from fastapi import HTTPException, UploadFile
from hypothesis import HealthCheck, given, settings, strategies as st

from backend.app.models.training_job_model import TrainingJob
from backend.app.models.user_model import User
from backend.app.models.voice_profile_model import VoiceProfile
from backend.app.schemas.voice_profile_schema import SourceType, VoiceProfileStatus
from backend.app.services.training_job_service import TrainingJobService
from backend.app.services.voice_profile_service import VoiceProfileService


def _create_upload_file(content: bytes, filename: str = "sample.opus") -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=filename)


class TestVoiceProfileServiceCreate:

    def test_create_success(self, db_session, make_user, mock_storage, sample_opus_factory):
        user = make_user()
        opus_data = sample_opus_factory(duration_seconds=15.0)
        upload_file = _create_upload_file(opus_data)

        service = VoiceProfileService()
        result = service.create(
            user_id=user.id,
            name="Suara Baru",
            source_type=SourceType.own_voice,
            sample_audio=upload_file,
            db=db_session,
        )

        assert result.id is not None
        assert result.name == "Suara Baru"
        assert result.source_type == SourceType.own_voice
        assert result.status == VoiceProfileStatus.pending
        assert abs(result.duration_seconds - 15.0) < 0.1
        assert result.error_message is None

        db_record = db_session.get(VoiceProfile, result.id)
        assert db_record is not None
        assert db_record.user_id == user.id
        assert db_record.sample_audio_path is not None
        assert os.path.exists(db_record.sample_audio_path)
        with open(db_record.sample_audio_path, "rb") as f:
            assert f.read() == opus_data

    def test_create_accepts_bytes_directly(self, db_session, make_user, mock_storage, sample_opus_factory):
        user = make_user()
        opus_data = sample_opus_factory(duration_seconds=20.0)

        service = VoiceProfileService()
        result = service.create(
            user_id=user.id,
            name="Suara Langsung Bytes",
            source_type="character",
            sample_audio=opus_data,
            db=db_session,
        )

        assert result.status == VoiceProfileStatus.pending
        assert abs(result.duration_seconds - 20.0) < 0.1

    def test_create_invalid_file_format_raises_400(self, db_session, make_user, mock_storage):
        user = make_user()
        fake_data = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00"

        service = VoiceProfileService()
        with pytest.raises(HTTPException) as exc_info:
            service.create(
                user_id=user.id,
                name="Format Salah",
                source_type=SourceType.own_voice,
                sample_audio=fake_data,
                db=db_session,
            )

        assert exc_info.value.status_code == 400
        assert "Opus" in exc_info.value.detail
        assert db_session.query(VoiceProfile).filter_by(name="Format Salah").first() is None

    def test_create_duration_under_10s_raises_400(self, db_session, make_user, mock_storage, sample_opus_factory):
        user = make_user()
        short_audio = sample_opus_factory(duration_seconds=9.0)

        service = VoiceProfileService()
        with pytest.raises(HTTPException) as exc_info:
            service.create(
                user_id=user.id,
                name="Terlalu Pendek",
                source_type=SourceType.own_voice,
                sample_audio=short_audio,
                db=db_session,
            )

        assert exc_info.value.status_code == 400
        assert "10" in exc_info.value.detail
        assert db_session.query(VoiceProfile).filter_by(name="Terlalu Pendek").first() is None

    def test_create_duration_over_30s_raises_400(self, db_session, make_user, mock_storage, sample_opus_factory):
        user = make_user()
        long_audio = sample_opus_factory(duration_seconds=31.0)

        service = VoiceProfileService()
        with pytest.raises(HTTPException) as exc_info:
            service.create(
                user_id=user.id,
                name="Terlalu Panjang",
                source_type=SourceType.own_voice,
                sample_audio=long_audio,
                db=db_session,
            )

        assert exc_info.value.status_code == 400
        assert "30" in exc_info.value.detail
        assert db_session.query(VoiceProfile).filter_by(name="Terlalu Panjang").first() is None

    def test_create_corrupt_file_raises_400(self, db_session, make_user, mock_storage):
        user = make_user()
        corrupt_audio = b"OggS\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00"

        service = VoiceProfileService()
        with pytest.raises(HTTPException) as exc_info:
            service.create(
                user_id=user.id,
                name="Corrupt File",
                source_type=SourceType.own_voice,
                sample_audio=corrupt_audio,
                db=db_session,
            )

        assert exc_info.value.status_code == 400
        assert db_session.query(VoiceProfile).filter_by(name="Corrupt File").first() is None

    def test_create_storage_io_error_raises_500_and_no_db_record(
        self, db_session, make_user, mock_storage, sample_opus_factory
    ):
        user = make_user()
        opus_data = sample_opus_factory(duration_seconds=15.0)

        service = VoiceProfileService()
        with patch("builtins.open", side_effect=OSError("Disk write error")):
            with pytest.raises(HTTPException) as exc_info:
                service.create(
                    user_id=user.id,
                    name="IO Error Test",
                    source_type=SourceType.own_voice,
                    sample_audio=opus_data,
                    db=db_session,
                )

        assert exc_info.value.status_code == 500
        assert db_session.query(VoiceProfile).filter_by(name="IO Error Test").first() is None

    def test_create_db_failure_cleans_up_file(
        self, db_session, make_user, mock_storage, sample_opus_factory
    ):
        user = make_user()
        opus_data = sample_opus_factory(duration_seconds=15.0)

        service = VoiceProfileService()
        with patch.object(db_session, "commit", side_effect=RuntimeError("DB Commit Failed")):
            with pytest.raises(HTTPException) as exc_info:
                service.create(
                    user_id=user.id,
                    name="DB Failure Test",
                    source_type=SourceType.own_voice,
                    sample_audio=opus_data,
                    db=db_session,
                )

        assert exc_info.value.status_code == 500
        # Pastikan tidak ada file tertinggal di direktori penyimpanan user
        user_dir = os.path.join(mock_storage["sample_dir"], str(user.id))
        if os.path.exists(user_dir):
            assert len(os.listdir(user_dir)) == 0


class TestVoiceProfileServiceList:

    def test_list_returns_empty_when_no_profiles(self, db_session, make_user):
        user = make_user()
        service = VoiceProfileService()
        result = service.list(user_id=user.id, db=db_session)
        assert result == []

    def test_list_returns_only_user_profiles_sorted_desc(
        self, db_session, make_user, make_voice_profile
    ):
        user_a = make_user()
        user_b = make_user()

        # Buat profiles untuk user A dengan urutan waktu berbeda
        vp_a1 = make_voice_profile(user=user_a, name="Profile A1")
        vp_a2 = make_voice_profile(user=user_a, name="Profile A2")
        vp_a3 = make_voice_profile(user=user_a, name="Profile A3")

        # Buat profiles untuk user B
        make_voice_profile(user=user_b, name="Profile B1")
        make_voice_profile(user=user_b, name="Profile B2")

        db_session.commit()

        service = VoiceProfileService()
        results = service.list(user_id=user_a.id, db=db_session)

        assert len(results) == 3
        # Pastikan hanya milik user_a
        assert {r.id for r in results} == {vp_a1.id, vp_a2.id, vp_a3.id}
        # Pastikan terurut created_at descending
        assert results[0].created_at >= results[1].created_at >= results[2].created_at

    def test_list_defense_in_depth_raises_403_if_mismatch(self, db_session, make_user):
        user_a = make_user()
        user_b = make_user()

        service = VoiceProfileService()
        # Mock query return untuk mensimulasikan kegagalan isolasi data
        from backend.app.models.voice_profile_model import VoiceProfile
        fake_leak_record = VoiceProfile(
            id=uuid.uuid4(),
            user_id=user_b.id,
            name="Leaked",
            source_type="own_voice",
            status="pending",
            duration_seconds=12.0,
        )
        with patch.object(db_session, "scalars") as mock_scalars:
            mock_scalars.return_value.all.return_value = [fake_leak_record]
            with pytest.raises(HTTPException) as exc_info:
                service.list(user_id=user_a.id, db=db_session)

        assert exc_info.value.status_code == 403


class TestVoiceProfileServiceGet:

    def test_get_success(self, db_session, make_user, make_voice_profile):
        user = make_user()
        vp = make_voice_profile(user=user, name="Profile Spesifik", duration_seconds=18.0)
        db_session.commit()

        service = VoiceProfileService()
        result = service.get(voice_profile_id=vp.id, user_id=user.id, db=db_session)

        assert result.id == vp.id
        assert result.name == "Profile Spesifik"
        assert result.duration_seconds == 18.0
        assert result.status == VoiceProfileStatus.pending

    def test_get_non_existent_id_raises_404(self, db_session, make_user):
        user = make_user()
        random_id = uuid.uuid4()

        service = VoiceProfileService()
        with pytest.raises(HTTPException) as exc_info:
            service.get(voice_profile_id=random_id, user_id=user.id, db=db_session)

        assert exc_info.value.status_code == 404
        assert "tidak ditemukan" in exc_info.value.detail

    def test_get_other_user_profile_raises_404(self, db_session, make_user, make_voice_profile):
        user_a = make_user()
        user_b = make_user()
        vp_b = make_voice_profile(user=user_b, name="Milik User B")
        db_session.commit()

        service = VoiceProfileService()
        # User A mencoba akses milik User B -> harus 404 (bukan 403)
        with pytest.raises(HTTPException) as exc_info:
            service.get(voice_profile_id=vp_b.id, user_id=user_a.id, db=db_session)

        assert exc_info.value.status_code == 404
        assert "tidak ditemukan" in exc_info.value.detail


class TestVoiceProfileServiceRename:

    def test_rename_success_and_preserves_fields(
        self, db_session, make_user, make_voice_profile
    ):
        user = make_user()
        vp = make_voice_profile(
            user=user,
            name="Nama Lama",
            source_type="character",
            status="ready",
            duration_seconds=22.5,
            sample_audio_path="/path/sample.opus",
            model_checkpoint_path="/path/model.pth",
            error_message=None,
        )
        db_session.commit()
        original_created_at = vp.created_at

        service = VoiceProfileService()
        result = service.rename(
            voice_profile_id=vp.id,
            user_id=user.id,
            new_name="   Nama Baru Keren   ",
            db=db_session,
        )

        assert result.id == vp.id
        assert result.name == "Nama Baru Keren"
        assert result.source_type == SourceType.character
        assert result.status == VoiceProfileStatus.ready
        assert result.duration_seconds == 22.5
        assert result.created_at.replace(tzinfo=None) == original_created_at.replace(tzinfo=None)

        # Verifikasi di DB
        db_session.expire_all()
        reloaded = db_session.get(VoiceProfile, vp.id)
        assert reloaded.name == "Nama Baru Keren"
        assert reloaded.source_type == "character"
        assert reloaded.status == "ready"
        assert reloaded.duration_seconds == 22.5
        assert reloaded.sample_audio_path == "/path/sample.opus"
        assert reloaded.model_checkpoint_path == "/path/model.pth"

    def test_rename_non_existent_raises_404(self, db_session, make_user):
        user = make_user()
        service = VoiceProfileService()
        with pytest.raises(HTTPException) as exc_info:
            service.rename(
                voice_profile_id=uuid.uuid4(),
                user_id=user.id,
                new_name="Nama Apapun",
                db=db_session,
            )

        assert exc_info.value.status_code == 404

    def test_rename_other_user_profile_raises_404(
        self, db_session, make_user, make_voice_profile
    ):
        user_a = make_user()
        user_b = make_user()
        vp_b = make_voice_profile(user=user_b, name="VP User B")
        db_session.commit()

        service = VoiceProfileService()
        with pytest.raises(HTTPException) as exc_info:
            service.rename(
                voice_profile_id=vp_b.id,
                user_id=user_a.id,
                new_name="Hacked Name",
                db=db_session,
            )

        assert exc_info.value.status_code == 404

    def test_rename_empty_or_whitespace_raises_422(
        self, db_session, make_user, make_voice_profile
    ):
        user = make_user()
        vp = make_voice_profile(user=user)
        db_session.commit()

        service = VoiceProfileService()
        with pytest.raises(HTTPException) as exc_info:
            service.rename(
                voice_profile_id=vp.id,
                user_id=user.id,
                new_name="    ",
                db=db_session,
            )

        assert exc_info.value.status_code == 422

    def test_rename_too_long_raises_422(
        self, db_session, make_user, make_voice_profile
    ):
        user = make_user()
        vp = make_voice_profile(user=user)
        db_session.commit()

        service = VoiceProfileService()
        with pytest.raises(HTTPException) as exc_info:
            service.rename(
                voice_profile_id=vp.id,
                user_id=user.id,
                new_name="x" * 101,
                db=db_session,
            )

        assert exc_info.value.status_code == 422


class TestVoiceProfileServiceDelete:

    def test_delete_success_deletes_db_and_files(
        self, db_session, make_user, make_voice_profile, make_training_job, mock_storage
    ):
        user = make_user()
        # Buat file audio dan checkpoint dummy di disk
        sample_path = os.path.join(mock_storage["sample_dir"], "test_sample.opus")
        ckpt_path = os.path.join(mock_storage["checkpoint_dir"], "test_ckpt.pth")
        with open(sample_path, "wb") as f:
            f.write(b"sample_content")
        with open(ckpt_path, "wb") as f:
            f.write(b"ckpt_content")

        vp = make_voice_profile(
            user=user,
            status="ready",
            sample_audio_path=sample_path,
            model_checkpoint_path=ckpt_path,
        )
        tj = make_training_job(voice_profile=vp, status="completed")
        db_session.commit()

        service = VoiceProfileService()
        result = service.delete(voice_profile_id=vp.id, user_id=user.id, db=db_session)
        assert result is None

        # Verifikasi file di disk terhapus
        assert not os.path.exists(sample_path)
        assert not os.path.exists(ckpt_path)

        # Verifikasi record DB terhapus
        from backend.app.models.training_job_model import TrainingJob
        assert db_session.get(VoiceProfile, vp.id) is None
        assert db_session.get(TrainingJob, tj.id) is None

    def test_delete_non_existent_raises_404(self, db_session, make_user):
        user = make_user()
        service = VoiceProfileService()
        with pytest.raises(HTTPException) as exc_info:
            service.delete(voice_profile_id=uuid.uuid4(), user_id=user.id, db=db_session)

        assert exc_info.value.status_code == 404

    def test_delete_other_user_profile_raises_404(
        self, db_session, make_user, make_voice_profile
    ):
        user_a = make_user()
        user_b = make_user()
        vp_b = make_voice_profile(user=user_b, name="VP User B")
        db_session.commit()

        service = VoiceProfileService()
        with pytest.raises(HTTPException) as exc_info:
            service.delete(voice_profile_id=vp_b.id, user_id=user_a.id, db=db_session)

        assert exc_info.value.status_code == 404
        assert db_session.get(VoiceProfile, vp_b.id) is not None

    def test_delete_status_processing_raises_409(
        self, db_session, make_user, make_voice_profile
    ):
        user = make_user()
        vp = make_voice_profile(user=user, status="processing")
        db_session.commit()

        service = VoiceProfileService()
        with pytest.raises(HTTPException) as exc_info:
            service.delete(voice_profile_id=vp.id, user_id=user.id, db=db_session)

        assert exc_info.value.status_code == 409
        assert "sedang diproses" in exc_info.value.detail
        assert db_session.get(VoiceProfile, vp.id) is not None

    def test_delete_file_not_found_tolerated(
        self, db_session, make_user, make_voice_profile
    ):
        user = make_user()
        vp = make_voice_profile(
            user=user,
            status="ready",
            sample_audio_path="/non/existent/sample.opus",
            model_checkpoint_path="/non/existent/ckpt.pth",
        )
        db_session.commit()

        service = VoiceProfileService()
        result = service.delete(voice_profile_id=vp.id, user_id=user.id, db=db_session)
        assert result is None
        assert db_session.get(VoiceProfile, vp.id) is None

    def test_delete_permission_error_raises_500_and_retains_db(
        self, db_session, make_user, make_voice_profile, mock_storage
    ):
        user = make_user()
        sample_path = os.path.join(mock_storage["sample_dir"], "locked_sample.opus")
        with open(sample_path, "wb") as f:
            f.write(b"locked")

        vp = make_voice_profile(
            user=user,
            status="ready",
            sample_audio_path=sample_path,
        )
        db_session.commit()

        service = VoiceProfileService()
        with patch("os.remove", side_effect=PermissionError("Access denied")):
            with pytest.raises(HTTPException) as exc_info:
                service.delete(voice_profile_id=vp.id, user_id=user.id, db=db_session)

        assert exc_info.value.status_code == 500
        # Pastikan DB record tidak dihapus
        assert db_session.get(VoiceProfile, vp.id) is not None


class TestVoiceProfileServiceGetStatus:

    def test_get_status_pending_no_job(
        self, db_session, make_user, make_voice_profile
    ):
        user = make_user()
        vp = make_voice_profile(user=user, status="pending")
        db_session.commit()

        service = VoiceProfileService()
        result = service.get_status(voice_profile_id=vp.id, user_id=user.id, db=db_session)

        assert result.id == vp.id
        assert result.status == VoiceProfileStatus.pending
        assert result.error_message is None
        assert result.training_job is None

    def test_get_status_processing_with_progress(
        self, db_session, make_user, make_voice_profile, make_training_job
    ):
        from datetime import datetime, timezone
        user = make_user()
        vp = make_voice_profile(user=user, status="processing")
        now = datetime.now(timezone.utc)
        make_training_job(
            voice_profile=vp,
            status="processing",
            progress_pct=55,
            started_at=now,
        )
        db_session.commit()

        service = VoiceProfileService()
        result = service.get_status(voice_profile_id=vp.id, user_id=user.id, db=db_session)

        assert result.id == vp.id
        assert result.status == VoiceProfileStatus.processing
        assert result.training_job is not None
        assert result.training_job.status == "processing"
        assert result.training_job.progress_pct == 55
        assert result.training_job.started_at is not None

    def test_get_status_failed_invariants(
        self, db_session, make_user, make_voice_profile, make_training_job
    ):
        user = make_user()
        vp = make_voice_profile(
            user=user,
            status="failed",
            error_message="Proses training kehabisan memori GPU.",
        )
        make_training_job(voice_profile=vp, status="failed")
        db_session.commit()

        service = VoiceProfileService()
        result = service.get_status(voice_profile_id=vp.id, user_id=user.id, db=db_session)

        assert result.status == VoiceProfileStatus.failed
        assert result.error_message == "Proses training kehabisan memori GPU."
        assert result.training_job is not None
        assert result.training_job.completed_at is None

    def test_get_status_ready_invariants(
        self, db_session, make_user, make_voice_profile, make_training_job
    ):
        from datetime import datetime, timezone
        user = make_user()
        vp = make_voice_profile(user=user, status="ready")
        now = datetime.now(timezone.utc)
        make_training_job(voice_profile=vp, status="completed", completed_at=now)
        db_session.commit()

        service = VoiceProfileService()
        result = service.get_status(voice_profile_id=vp.id, user_id=user.id, db=db_session)

        assert result.status == VoiceProfileStatus.ready
        assert result.training_job is not None
        assert result.training_job.completed_at is not None

    def test_get_status_non_existent_raises_404(self, db_session, make_user):
        user = make_user()
        service = VoiceProfileService()
        with pytest.raises(HTTPException) as exc_info:
            service.get_status(
                voice_profile_id=uuid.uuid4(),
                user_id=user.id,
                db=db_session,
            )

        assert exc_info.value.status_code == 404

    def test_get_status_other_user_raises_404(
        self, db_session, make_user, make_voice_profile
    ):
        user_a = make_user()
        user_b = make_user()
        vp_b = make_voice_profile(user=user_b)
        db_session.commit()

        service = VoiceProfileService()
        with pytest.raises(HTTPException) as exc_info:
            service.get_status(
                voice_profile_id=vp_b.id,
                user_id=user_a.id,
                db=db_session,
            )

        assert exc_info.value.status_code == 404

    def test_get_status_ready_with_null_completed_at_uses_fallback_and_does_not_modify_db(
        self, db_session, make_user, make_voice_profile, make_training_job, caplog
    ):
        import logging
        user = make_user()
        vp = make_voice_profile(user=user, status="ready")
        tj = make_training_job(voice_profile=vp, status="completed", completed_at=None)
        db_session.commit()

        service = VoiceProfileService()
        with caplog.at_level(logging.WARNING):
            result = service.get_status(voice_profile_id=vp.id, user_id=user.id, db=db_session)

        # Invariant API response terpenuhi via fallback
        assert result.status == VoiceProfileStatus.ready
        assert result.training_job is not None
        assert result.training_job.completed_at is not None
        assert result.training_job.completed_at == vp.updated_at

        # Verifikasi bahwa DB sama sekali TIDAK diubah (tidak ada silent write)
        db_session.expire_all()
        from backend.app.models.training_job_model import TrainingJob
        tj_db = db_session.get(TrainingJob, tj.id)
        assert tj_db.completed_at is None

        # Verifikasi adanya warning log untuk visibilitas tim operasional
        assert any("berstatus 'ready' tetapi training_job.completed_at bernilai None" in record.message for record in caplog.records)


class TestRealOpusFixtures:
    """Pengujian terhadap file audio Opus nyata hasil generate encoder libopus asli."""

    @pytest.fixture
    def fixtures_dir(self):
        from pathlib import Path
        path = Path(__file__).parent.parent / "fixtures" / "audio"
        assert path.exists(), f"Fixtures dir tidak ditemukan di {path}"
        return path

    def test_real_opus_fixture_valid_15s(
        self, db_session, make_user, mock_storage, fixtures_dir
    ):
        user = make_user()
        audio_path = fixtures_dir / "valid_15s.opus"
        with open(audio_path, "rb") as f:
            content = f.read()

        upload_file = _create_upload_file(content, filename="real_15s.opus")
        service = VoiceProfileService()
        result = service.create(
            user_id=user.id,
            name="Profil 15s Asli",
            source_type=SourceType.own_voice,
            sample_audio=upload_file,
            db=db_session,
        )

        assert result.id is not None
        assert result.name == "Profil 15s Asli"
        assert result.status == VoiceProfileStatus.pending
        assert 14.5 <= result.duration_seconds <= 15.5
        assert os.path.exists(mock_storage["sample_dir"])

    def test_real_opus_fixture_valid_25s(
        self, db_session, make_user, mock_storage, fixtures_dir
    ):
        user = make_user()
        audio_path = fixtures_dir / "valid_25s.opus"
        with open(audio_path, "rb") as f:
            content = f.read()

        upload_file = _create_upload_file(content, filename="real_25s.opus")
        service = VoiceProfileService()
        result = service.create(
            user_id=user.id,
            name="Profil 25s Asli",
            source_type=SourceType.character,
            sample_audio=upload_file,
            db=db_session,
        )

        assert result.id is not None
        assert 24.5 <= result.duration_seconds <= 25.5

    def test_real_opus_fixture_too_short_5s_raises_400(
        self, db_session, make_user, mock_storage, fixtures_dir
    ):
        user = make_user()
        audio_path = fixtures_dir / "too_short_5s.opus"
        with open(audio_path, "rb") as f:
            content = f.read()

        upload_file = _create_upload_file(content, filename="short.opus")
        service = VoiceProfileService()
        with pytest.raises(HTTPException) as exc_info:
            service.create(
                user_id=user.id,
                name="Profil Terlalu Pendek",
                source_type=SourceType.own_voice,
                sample_audio=upload_file,
                db=db_session,
            )

        assert exc_info.value.status_code == 400
        assert "10 hingga 30" in exc_info.value.detail
        assert db_session.query(VoiceProfile).filter_by(name="Profil Terlalu Pendek").first() is None

    def test_real_opus_fixture_too_long_35s_raises_400(
        self, db_session, make_user, mock_storage, fixtures_dir
    ):
        user = make_user()
        audio_path = fixtures_dir / "too_long_35s.opus"
        with open(audio_path, "rb") as f:
            content = f.read()

        upload_file = _create_upload_file(content, filename="long.opus")
        service = VoiceProfileService()
        with pytest.raises(HTTPException) as exc_info:
            service.create(
                user_id=user.id,
                name="Profil Terlalu Panjang",
                source_type=SourceType.own_voice,
                sample_audio=upload_file,
                db=db_session,
            )

        assert exc_info.value.status_code == 400
        assert "10 hingga 30" in exc_info.value.detail
        assert db_session.query(VoiceProfile).filter_by(name="Profil Terlalu Panjang").first() is None

    def test_real_opus_fixture_corrupt_truncated_raises_400(
        self, db_session, make_user, mock_storage, fixtures_dir
    ):
        user = make_user()
        audio_path = fixtures_dir / "corrupt_truncated.opus"
        with open(audio_path, "rb") as f:
            content = f.read()

        upload_file = _create_upload_file(content, filename="corrupt.opus")
        service = VoiceProfileService()
        with pytest.raises(HTTPException) as exc_info:
            service.create(
                user_id=user.id,
                name="Profil Corrupt Truncated",
                source_type=SourceType.own_voice,
                sample_audio=upload_file,
                db=db_session,
            )

        assert exc_info.value.status_code == 400
        assert "corrupt atau tidak dapat diproses" in exc_info.value.detail
        assert db_session.query(VoiceProfile).filter_by(name="Profil Corrupt Truncated").first() is None

    def test_real_opus_fixture_corrupt_header_raises_400(
        self, db_session, make_user, mock_storage, fixtures_dir
    ):
        user = make_user()
        audio_path = fixtures_dir / "corrupt_header.opus"
        with open(audio_path, "rb") as f:
            content = f.read()

        upload_file = _create_upload_file(content, filename="bad_header.opus")
        service = VoiceProfileService()
        with pytest.raises(HTTPException) as exc_info:
            service.create(
                user_id=user.id,
                name="Profil Corrupt Header",
                source_type=SourceType.own_voice,
                sample_audio=upload_file,
                db=db_session,
            )

        assert exc_info.value.status_code == 400
        assert "Format file tidak valid" in exc_info.value.detail
        assert db_session.query(VoiceProfile).filter_by(name="Profil Corrupt Header").first() is None


class TestVoiceProfilePropertyTests:
    """Property-based tests menggunakan Hypothesis untuk Voice Profile Management."""

    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        name=st.text(
            alphabet=st.characters(blacklist_categories=("Cs",)),
            min_size=1,
            max_size=255,
        ).filter(lambda s: bool(s.strip()) and len(s.strip()) <= 255),
        source_type=st.sampled_from(list(SourceType)),
    )
    def test_property_1_create_initial_status_and_completeness(
        self, name, source_type, db_session, make_user, mock_storage, sample_opus_factory
    ):
        # Feature: voice-profile-management, Property 1: Create Voice Profile - Status Awal dan Kelengkapan Response
        # Validates: Requirements 1.1, 1.2
        user = make_user()
        opus_data = sample_opus_factory(duration_seconds=15.0)
        upload_file = _create_upload_file(opus_data)
        service = VoiceProfileService()

        try:
            result = service.create(
                user_id=user.id,
                name=name,
                source_type=source_type,
                sample_audio=upload_file,
                db=db_session,
            )

            assert isinstance(result.id, uuid.UUID)
            assert result.name == name.strip()
            assert result.source_type == source_type
            assert result.status == VoiceProfileStatus.pending
            assert 10.0 <= result.duration_seconds <= 30.0
            assert result.created_at is not None
            assert result.updated_at is not None
            assert result.error_message is None

            db_session.expire_all()
            record = db_session.get(VoiceProfile, result.id)
            assert record is not None
            assert record.user_id == user.id
            assert record.status == "pending"
            assert record.name == name.strip()
            assert os.path.exists(record.sample_audio_path)
        finally:
            db_session.query(TrainingJob).delete()
            db_session.query(VoiceProfile).delete()
            db_session.query(User).delete()
            db_session.commit()
            for p in mock_storage["sample_dir"].glob("**/*"):
                if p.is_file():
                    try:
                        p.unlink()
                    except OSError:
                        pass

    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        name=st.one_of(
            st.text(alphabet=" \t\r\n\u00a0\u2000", min_size=0, max_size=30),
            st.text(
                alphabet=st.characters(blacklist_categories=("Cs",)),
                min_size=256,
                max_size=350,
            ).filter(lambda s: len(s.strip()) > 255),
        )
    )
    def test_property_2_create_invalid_name_rejected(
        self, name, db_session, make_user, mock_storage, sample_opus_factory
    ):
        # Feature: voice-profile-management, Property 2: Validasi Name - Rejection Semua Input Invalid
        # Validates: Requirements 1.3, 6.3
        user = make_user()
        opus_data = sample_opus_factory(duration_seconds=15.0)
        upload_file = _create_upload_file(opus_data)
        service = VoiceProfileService()

        try:
            with pytest.raises(HTTPException) as exc_info:
                service.create(
                    user_id=user.id,
                    name=name,
                    source_type=SourceType.own_voice,
                    sample_audio=upload_file,
                    db=db_session,
                )
            assert exc_info.value.status_code == 422
            assert db_session.query(VoiceProfile).filter_by(user_id=user.id).count() == 0
        finally:
            db_session.query(TrainingJob).delete()
            db_session.query(VoiceProfile).delete()
            db_session.query(User).delete()
            db_session.commit()
            for p in mock_storage["sample_dir"].glob("**/*"):
                if p.is_file():
                    try:
                        p.unlink()
                    except OSError:
                        pass

    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        duration=st.one_of(
            st.floats(min_value=0.5, max_value=9.9),
            st.floats(min_value=10.0, max_value=30.0),
            st.floats(min_value=30.1, max_value=60.0),
        )
    )
    def test_property_3_audio_duration_validation(
        self, duration, db_session, make_user, mock_storage, sample_opus_factory
    ):
        # Feature: voice-profile-management, Property 3: Validasi Durasi Sample Audio
        # Validates: Requirements 1.8, 1.9
        user = make_user()
        opus_data = sample_opus_factory(duration_seconds=float(duration))
        upload_file = _create_upload_file(opus_data)
        service = VoiceProfileService()

        try:
            if duration < 10.0 or duration > 30.0:
                with pytest.raises(HTTPException) as exc_info:
                    service.create(
                        user_id=user.id,
                        name="Test Durasi",
                        source_type=SourceType.own_voice,
                        sample_audio=upload_file,
                        db=db_session,
                    )
                assert exc_info.value.status_code == 400
                assert "10" in exc_info.value.detail and "30" in exc_info.value.detail
                assert db_session.query(VoiceProfile).filter_by(user_id=user.id).count() == 0
            else:
                result = service.create(
                    user_id=user.id,
                    name="Test Durasi",
                    source_type=SourceType.own_voice,
                    sample_audio=upload_file,
                    db=db_session,
                )
                assert abs(result.duration_seconds - float(duration)) < 0.1
                db_session.expire_all()
                record = db_session.get(VoiceProfile, result.id)
                assert record is not None
                assert abs(record.duration_seconds - float(duration)) < 0.1
        finally:
            db_session.query(TrainingJob).delete()
            db_session.query(VoiceProfile).delete()
            db_session.query(User).delete()
            db_session.commit()
            for p in mock_storage["sample_dir"].glob("**/*"):
                if p.is_file():
                    try:
                        p.unlink()
                    except OSError:
                        pass

    @settings(max_examples=40, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        count_a=st.integers(min_value=0, max_value=5),
        count_b=st.integers(min_value=0, max_value=4),
    )
    def test_property_7_list_isolation_and_ordering(
        self, count_a, count_b, db_session, make_user, make_voice_profile
    ):
        # Feature: voice-profile-management, Property 7: List Voice Profile - Isolasi Kepemilikan dan Urutan
        # Validates: Requirements 4.1, 4.2, 4.4
        from datetime import datetime, timezone, timedelta
        user_a = make_user()
        user_b = make_user()
        service = VoiceProfileService()

        try:
            base_time = datetime.now(timezone.utc).replace(tzinfo=None)
            ids_a = []
            for i in range(count_a):
                created = base_time - timedelta(minutes=i)
                vp = make_voice_profile(
                    user=user_a,
                    name=f"VP A {i}",
                    created_at=created,
                    updated_at=created,
                )
                ids_a.append(vp.id)

            for j in range(count_b):
                make_voice_profile(user=user_b, name=f"VP B {j}")

            db_session.commit()

            list_a = service.list(user_id=user_a.id, db=db_session)
            assert len(list_a) == count_a
            assert [item.id for item in list_a] == ids_a

            for k in range(len(list_a) - 1):
                t1 = list_a[k].created_at.replace(tzinfo=None) if list_a[k].created_at.tzinfo else list_a[k].created_at
                t2 = list_a[k + 1].created_at.replace(tzinfo=None) if list_a[k + 1].created_at.tzinfo else list_a[k + 1].created_at
                assert t1 >= t2

            for item in list_a:
                assert item.id is not None
                assert item.name is not None
                assert item.source_type is not None
                assert item.status is not None
                assert item.duration_seconds is not None
                assert item.created_at is not None
                assert item.updated_at is not None
        finally:
            db_session.query(TrainingJob).delete()
            db_session.query(VoiceProfile).delete()
            db_session.query(User).delete()
            db_session.commit()

    @settings(max_examples=40, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        vp_status=st.sampled_from(["pending", "processing", "ready", "failed"]),
    )
    def test_property_8_ownership_isolation_404_for_all_ops(
        self, vp_status, db_session, make_user, make_voice_profile, make_training_job, mock_queue
    ):
        # Feature: voice-profile-management, Property 8: Ownership Isolation - HTTP 404 untuk Resource Milik User Lain
        # Validates: Requirements 2.4, 3.3, 5.3, 6.5, 7.2, 9.2
        user_a = make_user()
        user_b = make_user()
        service = VoiceProfileService()
        training_service = TrainingJobService(queue=mock_queue)

        try:
            vp_a = make_voice_profile(
                user=user_a,
                name="Profil Milik A",
                status=vp_status,
                duration_seconds=15.0,
            )
            if vp_status != "pending":
                make_training_job(
                    voice_profile=vp_a,
                    status="completed" if vp_status == "ready" else vp_status,
                )
            db_session.commit()

            # 1. GET detail milik user A oleh user B -> 404
            with pytest.raises(HTTPException) as exc_get:
                service.get(voice_profile_id=vp_a.id, user_id=user_b.id, db=db_session)
            assert exc_get.value.status_code == 404

            # 2. PATCH rename milik user A oleh user B -> 404
            with pytest.raises(HTTPException) as exc_rename:
                service.rename(
                    voice_profile_id=vp_a.id,
                    user_id=user_b.id,
                    new_name="Hacked Name",
                    db=db_session,
                )
            assert exc_rename.value.status_code == 404

            # 3. DELETE milik user A oleh user B -> 404
            with pytest.raises(HTTPException) as exc_del:
                service.delete(voice_profile_id=vp_a.id, user_id=user_b.id, db=db_session)
            assert exc_del.value.status_code == 404

            # 4. GET status milik user A oleh user B -> 404
            with pytest.raises(HTTPException) as exc_stat:
                service.get_status(voice_profile_id=vp_a.id, user_id=user_b.id, db=db_session)
            assert exc_stat.value.status_code == 404

            # 5. POST train milik user A oleh user B -> 404
            with pytest.raises(HTTPException) as exc_train:
                training_service.dispatch(voice_profile_id=vp_a.id, user_id=user_b.id, db=db_session)
            assert exc_train.value.status_code == 404

            # Verifikasi bahwa record user A tidak termutasi atau terhapus
            db_session.expire_all()
            reloaded = db_session.get(VoiceProfile, vp_a.id)
            assert reloaded is not None
            assert reloaded.name == "Profil Milik A"
            assert reloaded.status == vp_status
            assert reloaded.user_id == user_a.id
        finally:
            db_session.query(TrainingJob).delete()
            db_session.query(VoiceProfile).delete()
            db_session.query(User).delete()
            db_session.commit()

    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        original_status=st.sampled_from(["ready", "failed", "pending"]),
        new_name=st.text(
            alphabet=st.characters(blacklist_categories=("Cs",)),
            min_size=0,
            max_size=150,
        ),
    )
    def test_property_10_rename_field_preservation(
        self, original_status, new_name, db_session, make_user, make_voice_profile
    ):
        # Feature: voice-profile-management, Property 10: Rename - Field Preservation
        # Validates: Requirements 6.1, 6.6
        user = make_user()
        service = VoiceProfileService()

        try:
            vp = make_voice_profile(
                user=user,
                name="Nama Awal",
                source_type="character",
                status=original_status,
                duration_seconds=22.5,
                sample_audio_path="/mock/storage/sample.opus",
                model_checkpoint_path="/mock/storage/chk.pth",
                error_message="Pesan error lampau" if original_status == "failed" else None,
            )
            db_session.commit()
            db_session.refresh(vp)
            original_id = vp.id
            original_user_id = vp.user_id
            original_created_at = vp.created_at
            original_error_message = vp.error_message

            trimmed = new_name.strip()
            if not trimmed or len(trimmed) > 100:
                with pytest.raises(HTTPException) as exc_info:
                    service.rename(
                        voice_profile_id=vp.id,
                        user_id=user.id,
                        new_name=new_name,
                        db=db_session,
                    )
                assert exc_info.value.status_code == 422
                db_session.expire_all()
                unchanged = db_session.get(VoiceProfile, original_id)
                assert unchanged.name == "Nama Awal"
            else:
                result = service.rename(
                    voice_profile_id=vp.id,
                    user_id=user.id,
                    new_name=new_name,
                    db=db_session,
                )
                assert result.name == trimmed

                db_session.expire_all()
                reloaded = db_session.get(VoiceProfile, original_id)
                assert reloaded.name == trimmed
                assert reloaded.id == original_id
                assert reloaded.user_id == original_user_id
                assert reloaded.source_type == "character"
                assert reloaded.status == original_status
                assert reloaded.duration_seconds == 22.5
                assert reloaded.sample_audio_path == "/mock/storage/sample.opus"
                assert reloaded.model_checkpoint_path == "/mock/storage/chk.pth"
                assert reloaded.error_message == original_error_message
                assert reloaded.created_at.replace(tzinfo=None) == original_created_at.replace(tzinfo=None)
                assert reloaded.updated_at >= original_created_at
        finally:
            db_session.query(TrainingJob).delete()
            db_session.query(VoiceProfile).delete()
            db_session.query(User).delete()
            db_session.commit()
