"""
Tests untuk Pydantic schemas: VoiceProfile dan TrainingJob.
Wave 2: Task 2.1.

Tests ini gagal dulu (Red), lalu schemas diimplementasikan (Green).
"""
import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ===========================================================================
# SourceType & VoiceProfileStatus enums
# ===========================================================================

class TestSourceTypeEnum:

    def test_valid_values(self):
        from backend.app.schemas.voice_profile_schema import SourceType
        assert SourceType.own_voice == "own_voice"
        assert SourceType.other_person == "other_person"
        assert SourceType.character == "character"

    def test_all_three_values_exist(self):
        from backend.app.schemas.voice_profile_schema import SourceType
        assert len(SourceType) == 3


class TestVoiceProfileStatusEnum:

    def test_valid_values(self):
        from backend.app.schemas.voice_profile_schema import VoiceProfileStatus
        assert VoiceProfileStatus.pending == "pending"
        assert VoiceProfileStatus.processing == "processing"
        assert VoiceProfileStatus.ready == "ready"
        assert VoiceProfileStatus.failed == "failed"

    def test_all_four_values_exist(self):
        from backend.app.schemas.voice_profile_schema import VoiceProfileStatus
        assert len(VoiceProfileStatus) == 4


# ===========================================================================
# VoiceProfileCreateRequest
# ===========================================================================

class TestVoiceProfileCreateRequest:

    def _make(self, **kwargs):
        from backend.app.schemas.voice_profile_schema import VoiceProfileCreateRequest
        defaults = {"name": "Suara Gue", "source_type": "own_voice"}
        defaults.update(kwargs)
        return VoiceProfileCreateRequest(**defaults)

    def test_valid_minimal(self):
        req = self._make()
        assert req.name == "Suara Gue"
        assert req.source_type.value == "own_voice"

    def test_name_trimmed_on_input(self):
        """Leading/trailing whitespace di-trim."""
        req = self._make(name="  My Voice  ")
        assert req.name == "My Voice"

    def test_name_min_length_one(self):
        req = self._make(name="A")
        assert req.name == "A"

    def test_name_max_length_255(self):
        req = self._make(name="x" * 255)
        assert len(req.name) == 255

    def test_name_empty_string_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            self._make(name="")
        errors = exc_info.value.errors()
        assert any("name" in str(e["loc"]) for e in errors)

    def test_name_whitespace_only_rejected(self):
        with pytest.raises(ValidationError):
            self._make(name="   ")

    def test_name_exceeds_255_rejected(self):
        with pytest.raises(ValidationError):
            self._make(name="x" * 256)

    def test_name_missing_rejected(self):
        from backend.app.schemas.voice_profile_schema import VoiceProfileCreateRequest
        with pytest.raises(ValidationError):
            VoiceProfileCreateRequest(source_type="own_voice")

    def test_source_type_all_valid_values(self):
        for st in ("own_voice", "other_person", "character"):
            req = self._make(source_type=st)
            assert req.source_type == st

    def test_source_type_invalid_rejected(self):
        with pytest.raises(ValidationError):
            self._make(source_type="robot")

    def test_source_type_missing_rejected(self):
        from backend.app.schemas.voice_profile_schema import VoiceProfileCreateRequest
        with pytest.raises(ValidationError):
            VoiceProfileCreateRequest(name="Test")


# ===========================================================================
# VoiceProfileRenameRequest
# ===========================================================================

class TestVoiceProfileRenameRequest:

    def _make(self, **kwargs):
        from backend.app.schemas.voice_profile_schema import VoiceProfileRenameRequest
        defaults = {"name": "Nama Baru"}
        defaults.update(kwargs)
        return VoiceProfileRenameRequest(**defaults)

    def test_valid_name(self):
        req = self._make(name="Nama Baru")
        assert req.name == "Nama Baru"

    def test_name_trimmed(self):
        req = self._make(name="  Nama Baru  ")
        assert req.name == "Nama Baru"

    def test_name_max_100_chars(self):
        req = self._make(name="x" * 100)
        assert len(req.name) == 100

    def test_name_101_chars_rejected(self):
        with pytest.raises(ValidationError):
            self._make(name="x" * 101)

    def test_name_after_trim_101_rejected(self):
        """101 karakter non-whitespace setelah trim harus ditolak."""
        with pytest.raises(ValidationError):
            self._make(name="  " + "x" * 101 + "  ")

    def test_name_empty_rejected(self):
        with pytest.raises(ValidationError):
            self._make(name="")

    def test_name_whitespace_only_rejected(self):
        with pytest.raises(ValidationError):
            self._make(name="   ")

    def test_name_missing_rejected(self):
        from backend.app.schemas.voice_profile_schema import VoiceProfileRenameRequest
        with pytest.raises(ValidationError):
            VoiceProfileRenameRequest()

    def test_name_single_char_valid(self):
        req = self._make(name="X")
        assert req.name == "X"

    def test_name_after_trim_empty_rejected(self):
        """String yang setelah di-trim jadi kosong harus ditolak."""
        with pytest.raises(ValidationError):
            self._make(name="\t\n  ")


# ===========================================================================
# VoiceProfileResponse
# ===========================================================================

class TestVoiceProfileResponse:

    def _make_data(self, **kwargs):
        now = utcnow()
        defaults = {
            "id": uuid.uuid4(),
            "name": "Suara Gue",
            "source_type": "own_voice",
            "status": "pending",
            "duration_seconds": 15.0,
            "error_message": None,
            "created_at": now,
            "updated_at": now,
        }
        defaults.update(kwargs)
        return defaults

    def test_valid_response(self):
        from backend.app.schemas.voice_profile_schema import VoiceProfileResponse
        data = self._make_data()
        resp = VoiceProfileResponse(**data)
        assert isinstance(resp.id, uuid.UUID)
        assert resp.name == "Suara Gue"
        assert resp.error_message is None

    def test_error_message_null_when_no_error(self):
        from backend.app.schemas.voice_profile_schema import VoiceProfileResponse
        resp = VoiceProfileResponse(**self._make_data(error_message=None))
        assert resp.error_message is None

    def test_error_message_present_when_failed(self):
        from backend.app.schemas.voice_profile_schema import VoiceProfileResponse
        resp = VoiceProfileResponse(**self._make_data(
            status="failed",
            error_message="Training gagal karena GPU OOM"
        ))
        assert resp.error_message == "Training gagal karena GPU OOM"

    def test_all_required_fields_present(self):
        from backend.app.schemas.voice_profile_schema import VoiceProfileResponse
        resp = VoiceProfileResponse(**self._make_data())
        # Semua field wajib dari spec harus ada
        for field in ("id", "name", "source_type", "status",
                      "duration_seconds", "error_message",
                      "created_at", "updated_at"):
            assert hasattr(resp, field)

    def test_model_checkpoint_path_not_exposed(self):
        """model_checkpoint_path adalah internal, tidak boleh ada di response schema."""
        from backend.app.schemas.voice_profile_schema import VoiceProfileResponse
        fields = VoiceProfileResponse.model_fields
        assert "model_checkpoint_path" not in fields, (
            "model_checkpoint_path adalah path internal server, "
            "tidak boleh di-expose ke client"
        )

    def test_sample_audio_path_not_exposed(self):
        """sample_audio_path adalah path internal, tidak boleh ada di response schema."""
        from backend.app.schemas.voice_profile_schema import VoiceProfileResponse
        fields = VoiceProfileResponse.model_fields
        assert "sample_audio_path" not in fields

    def test_from_orm_attributes(self):
        """Schema harus bisa dibuat dari ORM model attributes (from_attributes=True)."""
        from backend.app.schemas.voice_profile_schema import VoiceProfileResponse
        # Simulasi ORM object dengan __dict__-style access
        class FakeVP:
            id = uuid.uuid4()
            name = "ORM VP"
            source_type = "character"
            status = "ready"
            duration_seconds = 20.0
            error_message = None
            created_at = utcnow()
            updated_at = utcnow()

        resp = VoiceProfileResponse.model_validate(FakeVP())
        assert resp.name == "ORM VP"

    def test_serializes_to_dict(self):
        from backend.app.schemas.voice_profile_schema import VoiceProfileResponse
        resp = VoiceProfileResponse(**self._make_data())
        d = resp.model_dump()
        assert "id" in d
        assert "name" in d


# ===========================================================================
# VoiceProfileListResponse
# ===========================================================================

class TestVoiceProfileListResponse:

    def test_list_response_wraps_items(self):
        from backend.app.schemas.voice_profile_schema import (
            VoiceProfileResponse,
            VoiceProfileListResponse,
        )
        now = utcnow()
        item = VoiceProfileResponse(
            id=uuid.uuid4(),
            name="VP 1",
            source_type="own_voice",
            status="pending",
            duration_seconds=10.0,
            error_message=None,
            created_at=now,
            updated_at=now,
        )
        resp = VoiceProfileListResponse(items=[item])
        assert len(resp.items) == 1

    def test_empty_list_valid(self):
        from backend.app.schemas.voice_profile_schema import VoiceProfileListResponse
        resp = VoiceProfileListResponse(items=[])
        assert resp.items == []


# ===========================================================================
# VoiceProfileStatusResponse
# ===========================================================================

class TestVoiceProfileStatusResponse:

    def _make_job_data(self, **kwargs):
        defaults = {
            "status": "queued",
            "progress_pct": 0,
            "started_at": None,
            "completed_at": None,
        }
        defaults.update(kwargs)
        return defaults

    def test_status_pending_no_job(self):
        from backend.app.schemas.voice_profile_schema import VoiceProfileStatusResponse
        resp = VoiceProfileStatusResponse(
            id=uuid.uuid4(),
            status="pending",
            error_message=None,
            training_job=None,
        )
        assert resp.status == "pending"
        assert resp.training_job is None

    def test_status_processing_has_progress(self):
        from backend.app.schemas.voice_profile_schema import (
            VoiceProfileStatusResponse,
            TrainingJobStatusResponse,
        )
        job = TrainingJobStatusResponse(**self._make_job_data(
            status="processing", progress_pct=45, started_at=utcnow()
        ))
        resp = VoiceProfileStatusResponse(
            id=uuid.uuid4(),
            status="processing",
            error_message=None,
            training_job=job,
        )
        assert resp.training_job.progress_pct == 45

    def test_status_failed_has_error_message(self):
        from backend.app.schemas.voice_profile_schema import (
            VoiceProfileStatusResponse,
            TrainingJobStatusResponse,
        )
        job = TrainingJobStatusResponse(**self._make_job_data(
            status="failed", progress_pct=0, completed_at=None
        ))
        resp = VoiceProfileStatusResponse(
            id=uuid.uuid4(),
            status="failed",
            error_message="CUDA out of memory",
            training_job=job,
        )
        assert resp.error_message == "CUDA out of memory"
        assert resp.training_job.completed_at is None

    def test_status_ready_has_completed_at(self):
        from backend.app.schemas.voice_profile_schema import (
            VoiceProfileStatusResponse,
            TrainingJobStatusResponse,
        )
        completed = utcnow()
        job = TrainingJobStatusResponse(**self._make_job_data(
            status="completed", progress_pct=100,
            started_at=utcnow(), completed_at=completed
        ))
        resp = VoiceProfileStatusResponse(
            id=uuid.uuid4(),
            status="ready",
            error_message=None,
            training_job=job,
        )
        assert resp.training_job.completed_at == completed


# ===========================================================================
# TrainingJobDispatchResponse
# ===========================================================================

class TestTrainingJobDispatchResponse:

    def test_valid_response(self):
        from backend.app.schemas.training_job_schema import TrainingJobDispatchResponse
        resp = TrainingJobDispatchResponse(
            training_job_id=uuid.uuid4(),
            status="queued",
        )
        assert resp.status == "queued"
        assert isinstance(resp.training_job_id, uuid.UUID)

    def test_status_is_always_queued_on_dispatch(self):
        from backend.app.schemas.training_job_schema import TrainingJobDispatchResponse
        resp = TrainingJobDispatchResponse(
            training_job_id=uuid.uuid4(),
            status="queued",
        )
        assert resp.status == "queued"
