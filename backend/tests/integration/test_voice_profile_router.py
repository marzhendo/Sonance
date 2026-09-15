"""Integration tests untuk Voice Profile Router (7 endpoint) dan Auth Guard.
Wave 6 - Task 12.1 dan 12.2.
"""
import io
import os
import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.app.models.training_job_model import TrainingJob
from backend.app.models.user_model import User
from backend.app.models.voice_profile_model import VoiceProfile
from backend.tests.conftest import OTHER_USER_ID, TEST_TOKEN, TEST_USER_ID


class TestVoiceProfileCreateEndpoint:

    def test_create_voice_profile_success(self, client, sample_opus_factory, mock_storage):
        sample_data = sample_opus_factory(duration_seconds=15.0)
        files = {"sample_audio": ("sample.opus", io.BytesIO(sample_data), "audio/ogg")}
        data = {"name": "Profil Suara Test", "source_type": "own_voice"}

        resp = client.post("/api/v1/voice-profiles", data=data, files=files)
        assert resp.status_code == 201

        payload = resp.json()
        assert payload["name"] == "Profil Suara Test"
        assert payload["source_type"] == "own_voice"
        assert payload["status"] == "pending"
        assert abs(payload["duration_seconds"] - 15.0) < 0.1
        assert "id" in payload

        # Pastikan path internal tidak bocor ke level HTTP response
        assert "sample_audio_path" not in payload
        assert "model_checkpoint_path" not in payload

    def test_create_voice_profile_empty_name_returns_422(self, client, sample_opus_factory):
        sample_data = sample_opus_factory(duration_seconds=15.0)
        files = {"sample_audio": ("sample.opus", io.BytesIO(sample_data), "audio/ogg")}
        data = {"name": "   ", "source_type": "own_voice"}

        resp = client.post("/api/v1/voice-profiles", data=data, files=files)
        assert resp.status_code == 422
        assert "detail" in resp.json()

    def test_create_voice_profile_name_too_long_returns_422(self, client, sample_opus_factory):
        sample_data = sample_opus_factory(duration_seconds=15.0)
        files = {"sample_audio": ("sample.opus", io.BytesIO(sample_data), "audio/ogg")}
        data = {"name": "A" * 256, "source_type": "own_voice"}

        resp = client.post("/api/v1/voice-profiles", data=data, files=files)
        assert resp.status_code == 422

    def test_create_voice_profile_invalid_source_type_returns_422(self, client, sample_opus_factory):
        sample_data = sample_opus_factory(duration_seconds=15.0)
        files = {"sample_audio": ("sample.opus", io.BytesIO(sample_data), "audio/ogg")}
        data = {"name": "Suara Test", "source_type": "invalid_type"}

        resp = client.post("/api/v1/voice-profiles", data=data, files=files)
        assert resp.status_code == 422

    def test_create_voice_profile_missing_file_returns_422(self, client):
        data = {"name": "Suara Test", "source_type": "own_voice"}
        resp = client.post("/api/v1/voice-profiles", data=data)
        assert resp.status_code == 422

    def test_create_voice_profile_empty_file_returns_422(self, client):
        files = {"sample_audio": ("empty.opus", io.BytesIO(b""), "audio/ogg")}
        data = {"name": "Suara Test", "source_type": "own_voice"}

        resp = client.post("/api/v1/voice-profiles", data=data, files=files)
        assert resp.status_code == 422

    def test_create_voice_profile_file_exceeds_10mb_returns_422(self, client):
        large_bytes = b"0" * (10 * 1024 * 1024 + 1)
        files = {"sample_audio": ("large.opus", io.BytesIO(large_bytes), "audio/ogg")}
        data = {"name": "Suara Test", "source_type": "own_voice"}

        resp = client.post("/api/v1/voice-profiles", data=data, files=files)
        assert resp.status_code == 422
        assert "10 MB" in resp.json()["detail"]

    def test_create_voice_profile_invalid_duration_returns_400(self, client, sample_opus_factory):
        short_sample = sample_opus_factory(duration_seconds=5.0)
        files = {"sample_audio": ("short.opus", io.BytesIO(short_sample), "audio/ogg")}
        data = {"name": "Suara Terlalu Pendek", "source_type": "own_voice"}

        resp = client.post("/api/v1/voice-profiles", data=data, files=files)
        assert resp.status_code == 400


class TestVoiceProfileListEndpoint:

    def test_list_voice_profiles_empty(self, client):
        resp = client.get("/api/v1/voice-profiles")
        assert resp.status_code == 200
        assert resp.json() == {"items": []}

    def test_list_voice_profiles_returns_user_profiles_ordered(
        self, client, make_voice_profile, test_user, db_session
    ):
        vp1 = make_voice_profile(user=test_user, name="Profil Pertama")
        vp2 = make_voice_profile(user=test_user, name="Profil Kedua")
        db_session.commit()

        resp = client.get("/api/v1/voice-profiles")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 2
        item_ids = [item["id"] for item in items]
        assert str(vp2.id) in item_ids
        assert str(vp1.id) in item_ids

    def test_list_voice_profiles_isolation(
        self, client, make_voice_profile, test_user, other_user, db_session
    ):
        make_voice_profile(user=test_user, name="Profil Test User")
        make_voice_profile(user=other_user, name="Profil Other User")
        db_session.commit()

        resp = client.get("/api/v1/voice-profiles")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Profil Test User"


class TestVoiceProfileGetEndpoint:

    def test_get_voice_profile_success(self, client, pending_voice_profile):
        resp = client.get(f"/api/v1/voice-profiles/{pending_voice_profile.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(pending_voice_profile.id)
        assert data["name"] == pending_voice_profile.name
        assert "sample_audio_path" not in data

    def test_get_voice_profile_not_found(self, client):
        random_id = uuid.uuid4()
        resp = client.get(f"/api/v1/voice-profiles/{random_id}")
        assert resp.status_code == 404

    def test_get_voice_profile_other_user_returns_404(
        self, other_user_client, pending_voice_profile
    ):
        resp = other_user_client.get(f"/api/v1/voice-profiles/{pending_voice_profile.id}")
        assert resp.status_code == 404


class TestVoiceProfileRenameEndpoint:

    def test_rename_voice_profile_success(self, client, pending_voice_profile):
        resp = client.patch(
            f"/api/v1/voice-profiles/{pending_voice_profile.id}",
            json={"name": "Nama Baru Disetujui"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Nama Baru Disetujui"
        assert data["id"] == str(pending_voice_profile.id)

    def test_rename_voice_profile_empty_name_returns_422(self, client, pending_voice_profile):
        resp = client.patch(
            f"/api/v1/voice-profiles/{pending_voice_profile.id}",
            json={"name": "   "},
        )
        assert resp.status_code == 422

    def test_rename_voice_profile_too_long_name_returns_422(self, client, pending_voice_profile):
        resp = client.patch(
            f"/api/v1/voice-profiles/{pending_voice_profile.id}",
            json={"name": "A" * 101},
        )
        assert resp.status_code == 422

    def test_rename_voice_profile_not_found(self, client):
        resp = client.patch(
            f"/api/v1/voice-profiles/{uuid.uuid4()}",
            json={"name": "Nama Baru"},
        )
        assert resp.status_code == 404

    def test_rename_voice_profile_other_user_returns_404(
        self, other_user_client, pending_voice_profile
    ):
        resp = other_user_client.patch(
            f"/api/v1/voice-profiles/{pending_voice_profile.id}",
            json={"name": "Nama Pembobol"},
        )
        assert resp.status_code == 404


class TestVoiceProfileDeleteEndpoint:

    def test_delete_voice_profile_success(self, client, pending_voice_profile, db_session):
        resp = client.delete(f"/api/v1/voice-profiles/{pending_voice_profile.id}")
        assert resp.status_code == 204

        # Verifikasi bahwa subsequent GET menghasilkan 404
        get_resp = client.get(f"/api/v1/voice-profiles/{pending_voice_profile.id}")
        assert get_resp.status_code == 404

    def test_delete_voice_profile_processing_conflict_returns_409(
        self, client, make_voice_profile, test_user, db_session
    ):
        vp = make_voice_profile(user=test_user, status="processing")
        db_session.commit()

        resp = client.delete(f"/api/v1/voice-profiles/{vp.id}")
        assert resp.status_code == 409
        assert "diproses" in resp.json()["detail"].lower() or "processing" in resp.json()["detail"].lower()

    def test_delete_voice_profile_not_found(self, client):
        resp = client.delete(f"/api/v1/voice-profiles/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_delete_voice_profile_other_user_returns_404(
        self, other_user_client, pending_voice_profile
    ):
        resp = other_user_client.delete(f"/api/v1/voice-profiles/{pending_voice_profile.id}")
        assert resp.status_code == 404


class TestVoiceProfileTrainEndpoint:

    def test_train_voice_profile_success(self, client, pending_voice_profile):
        resp = client.post(f"/api/v1/voice-profiles/{pending_voice_profile.id}/train")
        assert resp.status_code == 202
        payload = resp.json()
        assert "training_job_id" in payload
        assert payload["status"] == "queued"

    def test_train_voice_profile_non_pending_returns_409(self, client, ready_voice_profile):
        resp = client.post(f"/api/v1/voice-profiles/{ready_voice_profile.id}/train")
        assert resp.status_code == 409
        assert "pending" in resp.json()["detail"].lower()

    def test_train_voice_profile_not_found(self, client):
        resp = client.post(f"/api/v1/voice-profiles/{uuid.uuid4()}/train")
        assert resp.status_code == 404

    def test_train_voice_profile_other_user_returns_404(
        self, other_user_client, pending_voice_profile
    ):
        resp = other_user_client.post(f"/api/v1/voice-profiles/{pending_voice_profile.id}/train")
        assert resp.status_code == 404


class TestVoiceProfileStatusEndpoint:

    def test_get_status_pending_without_job(self, client, pending_voice_profile):
        resp = client.get(f"/api/v1/voice-profiles/{pending_voice_profile.id}/status")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["id"] == str(pending_voice_profile.id)
        assert payload["status"] == "pending"
        assert payload["training_job"] is None

    def test_get_status_processing_with_progress(
        self, client, make_voice_profile, make_training_job, test_user, db_session
    ):
        vp = make_voice_profile(user=test_user, status="processing")
        make_training_job(voice_profile=vp, status="processing", progress_pct=65)
        db_session.commit()

        resp = client.get(f"/api/v1/voice-profiles/{vp.id}/status")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["status"] == "processing"
        assert payload["training_job"] is not None
        assert payload["training_job"]["progress_pct"] == 65

    def test_get_status_ready_invariants(
        self, client, make_voice_profile, make_training_job, test_user, db_session
    ):
        vp = make_voice_profile(user=test_user, status="ready")
        from datetime import datetime, timezone
        make_training_job(
            voice_profile=vp,
            status="completed",
            progress_pct=100,
            completed_at=datetime.now(timezone.utc),
        )
        db_session.commit()

        resp = client.get(f"/api/v1/voice-profiles/{vp.id}/status")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["status"] == "ready"
        assert payload["training_job"]["completed_at"] is not None

    def test_get_status_failed_invariants(
        self, client, make_voice_profile, make_training_job, test_user, db_session
    ):
        vp = make_voice_profile(
            user=test_user,
            status="failed",
            error_message="Dataset audio tidak mencukupi",
        )
        make_training_job(voice_profile=vp, status="failed", progress_pct=20)
        db_session.commit()

        resp = client.get(f"/api/v1/voice-profiles/{vp.id}/status")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["status"] == "failed"
        assert payload["error_message"] == "Dataset audio tidak mencukupi"

    def test_get_status_not_found(self, client):
        resp = client.get(f"/api/v1/voice-profiles/{uuid.uuid4()}/status")
        assert resp.status_code == 404

    def test_get_status_other_user_returns_404(
        self, other_user_client, pending_voice_profile
    ):
        resp = other_user_client.get(f"/api/v1/voice-profiles/{pending_voice_profile.id}/status")
        assert resp.status_code == 404


class TestVoiceProfileStatusProperty:
    """Property 6: Status Polling - Invariant Field Berdasarkan Status (Task 14.1)."""

    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        status_name=st.sampled_from(["processing", "failed", "ready"]),
        progress_pct=st.integers(min_value=0, max_value=100),
    )
    def test_property_6_status_polling_invariants(
        self, status_name, progress_pct, client, test_user, make_voice_profile, make_training_job, db_session
    ):
        # Feature: voice-profile-management, Property 6: Status Polling Invariants
        # Validates: Requirements 3.1, 3.4, 3.5, 3.6
        from datetime import datetime, timezone

        if status_name == "processing":
            vp = make_voice_profile(user=test_user, status="processing")
            tj = make_training_job(voice_profile=vp, status="processing", progress_pct=progress_pct)
        elif status_name == "failed":
            vp = make_voice_profile(user=test_user, status="failed", error_message="Gagal proses training")
            tj = make_training_job(voice_profile=vp, status="failed", progress_pct=progress_pct)
        elif status_name == "ready":
            vp = make_voice_profile(user=test_user, status="ready")
            tj = make_training_job(
                voice_profile=vp,
                status="completed",
                progress_pct=100,
                completed_at=datetime.now(timezone.utc),
            )

        db_session.commit()

        # 1. Verifikasi lewat endpoint GET /status
        resp = client.get(f"/api/v1/voice-profiles/{vp.id}/status")
        assert resp.status_code == 200
        data = resp.json()

        assert data["id"] == str(vp.id)
        assert data["status"] == status_name
        assert data["training_job"] is not None
        job_data = data["training_job"]

        # Invariant 1: progress_pct selalu dalam rentang [0, 100]
        assert 0 <= job_data["progress_pct"] <= 100

        if status_name == "processing":
            # Invariant 2: error_message harus None saat processing
            assert data["error_message"] is None
            # Invariant 3: completed_at harus None saat processing
            assert job_data["completed_at"] is None
            assert job_data["progress_pct"] == progress_pct

        elif status_name == "failed":
            # Invariant 4: error_message tidak boleh None saat failed
            assert data["error_message"] is not None
            assert len(data["error_message"]) > 0
            # Invariant 5: completed_at harus None saat failed
            assert job_data["completed_at"] is None

        elif status_name == "ready":
            # Invariant 6: completed_at tidak boleh None saat ready
            assert job_data["completed_at"] is not None
            # Invariant 7: error_message harus None saat ready
            assert data["error_message"] is None
            assert job_data["progress_pct"] == 100

        # Cleanup untuk iterasi berikutnya
        db_session.query(TrainingJob).filter_by(voice_profile_id=vp.id).delete()
        db_session.query(VoiceProfile).filter_by(id=vp.id).delete()
        db_session.commit()


class TestVoiceProfileAuthGuardProperty:
    """Property 9: Auth Guard - HTTP 401 untuk Semua Endpoint (Task 12.2)."""

    def test_all_endpoints_return_401_when_token_absent(self, unauth_client):
        # Feature: voice-profile-management, Property 9: Auth Guard HTTP 401
        # Validates: Requirements 8.1, 8.2
        dummy_id = uuid.uuid4()

        r_create = unauth_client.post("/api/v1/voice-profiles", data={})
        assert r_create.status_code == 401

        r_list = unauth_client.get("/api/v1/voice-profiles")
        assert r_list.status_code == 401

        r_get = unauth_client.get(f"/api/v1/voice-profiles/{dummy_id}")
        assert r_get.status_code == 401

        r_patch = unauth_client.patch(f"/api/v1/voice-profiles/{dummy_id}", json={})
        assert r_patch.status_code == 401

        r_del = unauth_client.delete(f"/api/v1/voice-profiles/{dummy_id}")
        assert r_del.status_code == 401

        r_train = unauth_client.post(f"/api/v1/voice-profiles/{dummy_id}/train")
        assert r_train.status_code == 401

        r_status = unauth_client.get(f"/api/v1/voice-profiles/{dummy_id}/status")
        assert r_status.status_code == 401

    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        raw_token=st.text(
            alphabet=st.characters(min_codepoint=32, max_codepoint=126),
            min_size=0,
            max_size=60,
        ).filter(lambda s: s.strip() != TEST_TOKEN),
        use_bearer=st.booleans(),
    )
    def test_property_9_all_7_endpoints_reject_invalid_token_with_401(
        self, raw_token, use_bearer, unauth_client, monkeypatch
    ):
        # Feature: voice-profile-management, Property 9: Auth Guard HTTP 401 untuk Semua 7 Endpoint
        # Validates: Requirements 8.1, 8.2
        monkeypatch.setenv("SONANCE_API_TOKEN", TEST_TOKEN)
        header_val = f"Bearer {raw_token}" if use_bearer else raw_token
        headers = {"Authorization": header_val} if raw_token else {}
        dummy_id = uuid.uuid4()

        responses = [
            unauth_client.post("/api/v1/voice-profiles", data={}, headers=headers),
            unauth_client.get("/api/v1/voice-profiles", headers=headers),
            unauth_client.get(f"/api/v1/voice-profiles/{dummy_id}", headers=headers),
            unauth_client.patch(f"/api/v1/voice-profiles/{dummy_id}", json={}, headers=headers),
            unauth_client.delete(f"/api/v1/voice-profiles/{dummy_id}", headers=headers),
            unauth_client.post(f"/api/v1/voice-profiles/{dummy_id}/train", headers=headers),
            unauth_client.get(f"/api/v1/voice-profiles/{dummy_id}/status", headers=headers),
        ]

        for r in responses:
            assert r.status_code == 401
            data = r.json()
            assert "detail" in data

