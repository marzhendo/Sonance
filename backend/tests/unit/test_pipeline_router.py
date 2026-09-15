"""Tests untuk Pipeline Router dan ML Pipeline Stubs.
Wave 7 - Task 13.1, 13.2, 13.4 (Property 4).
"""
import os
import tempfile
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from backend.app.schemas.voice_profile_schema import SourceType
from backend.ml.rvc import RVCPipeline
from backend.ml.svc import SVCPipeline
from backend.workers.training_worker import select_pipeline


class TestPipelineRouter:

    def test_select_pipeline_own_voice_returns_rvc(self):
        pipeline = select_pipeline(SourceType.own_voice)
        assert isinstance(pipeline, RVCPipeline)

        pipeline_str = select_pipeline("own_voice")
        assert isinstance(pipeline_str, RVCPipeline)

    def test_select_pipeline_other_person_returns_rvc(self):
        pipeline = select_pipeline(SourceType.other_person)
        assert isinstance(pipeline, RVCPipeline)

        pipeline_str = select_pipeline("other_person")
        assert isinstance(pipeline_str, RVCPipeline)

    def test_select_pipeline_character_returns_svc(self):
        pipeline = select_pipeline(SourceType.character)
        assert isinstance(pipeline, SVCPipeline)

        pipeline_str = select_pipeline("character")
        assert isinstance(pipeline_str, SVCPipeline)

    @pytest.mark.parametrize("invalid_source", ["unknown", "alien", "", "robot"])
    def test_select_pipeline_unknown_raises_value_error(self, invalid_source):
        with pytest.raises(ValueError) as exc_info:
            select_pipeline(invalid_source)
        assert "Unknown source_type" in str(exc_info.value)

    @settings(max_examples=50, deadline=None)
    @given(
        source_val=st.sampled_from([
            SourceType.own_voice,
            SourceType.other_person,
            SourceType.character,
            "own_voice",
            "other_person",
            "character",
        ])
    )
    def test_property_4_pipeline_routing_consistency(self, source_val):
        # Feature: voice-profile-management, Property 4: Pipeline Routing Berdasarkan source_type
        # Validates: Requirements 2.10
        pipeline = select_pipeline(source_val)
        raw_val = source_val.value if isinstance(source_val, SourceType) else source_val
        if raw_val in ("own_voice", "other_person"):
            assert isinstance(pipeline, RVCPipeline)
        elif raw_val == "character":
            assert isinstance(pipeline, SVCPipeline)

    @settings(max_examples=50, deadline=None)
    @given(
        invalid_str=st.text().filter(
            lambda s: s not in ("own_voice", "other_person", "character")
        )
    )
    def test_property_4_invalid_source_type_always_rejected(self, invalid_str):
        # Feature: voice-profile-management, Property 4: Rejection of Invalid source_type
        # Validates: Requirements 2.10
        with pytest.raises(ValueError) as exc_info:
            select_pipeline(invalid_str)
        assert "Unknown source_type" in str(exc_info.value)


class TestRVCPipelineStub:

    def test_rvc_pipeline_train_success(self, tmp_path):
        pipeline = RVCPipeline()
        progress_records = []

        def on_progress(pct: int):
            progress_records.append(pct)

        sample_path = str(tmp_path / "sample.opus")
        with open(sample_path, "wb") as f:
            f.write(b"dummy opus audio")

        checkpoint_dir = str(tmp_path / "checkpoints")
        checkpoint_path = pipeline.train(
            sample_audio_path=sample_path,
            checkpoint_dir=checkpoint_dir,
            progress_cb=on_progress,
        )

        assert os.path.exists(checkpoint_path)
        assert checkpoint_path.endswith(".pth")
        assert progress_records == [25, 50, 75, 100]

        with open(checkpoint_path, "rb") as f:
            content = f.read()
            assert b"RVC" in content

    def test_rvc_pipeline_simulate_failure_via_constructor(self, tmp_path):
        pipeline = RVCPipeline(simulate_failure=True)
        sample_path = str(tmp_path / "sample.opus")
        with open(sample_path, "wb") as f:
            f.write(b"dummy")

        with pytest.raises(RuntimeError) as exc_info:
            pipeline.train(sample_audio_path=sample_path, checkpoint_dir=str(tmp_path))

        assert "CUDA out of memory" in str(exc_info.value) or "failure" in str(exc_info.value)

    def test_rvc_pipeline_simulate_failure_via_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SONANCE_SIMULATE_TRAINING_FAILURE", "true")
        pipeline = RVCPipeline()
        sample_path = str(tmp_path / "sample.opus")
        with open(sample_path, "wb") as f:
            f.write(b"dummy")

        with pytest.raises(RuntimeError) as exc_info:
            pipeline.train(sample_audio_path=sample_path, checkpoint_dir=str(tmp_path))

        assert "Simulated RVC training failure" in str(exc_info.value)


class TestSVCPipelineStub:

    def test_svc_pipeline_train_success(self, tmp_path):
        pipeline = SVCPipeline()
        progress_records = []

        def on_progress(pct: int):
            progress_records.append(pct)

        sample_path = str(tmp_path / "sample.opus")
        with open(sample_path, "wb") as f:
            f.write(b"dummy opus audio")

        checkpoint_dir = str(tmp_path / "checkpoints")
        checkpoint_path = pipeline.train(
            sample_audio_path=sample_path,
            checkpoint_dir=checkpoint_dir,
            progress_cb=on_progress,
        )

        assert os.path.exists(checkpoint_path)
        assert checkpoint_path.endswith(".pth")
        assert progress_records == [25, 50, 75, 100]

        with open(checkpoint_path, "rb") as f:
            content = f.read()
            assert b"SVC" in content

    def test_svc_pipeline_simulate_failure_via_constructor(self, tmp_path):
        pipeline = SVCPipeline(simulate_failure=True)
        sample_path = str(tmp_path / "sample.opus")
        with open(sample_path, "wb") as f:
            f.write(b"dummy")

        with pytest.raises(RuntimeError) as exc_info:
            pipeline.train(sample_audio_path=sample_path, checkpoint_dir=str(tmp_path))

        assert "Model divergence" in str(exc_info.value) or "failure" in str(exc_info.value)

    def test_svc_pipeline_simulate_failure_via_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SONANCE_SIMULATE_TRAINING_FAILURE", "1")
        pipeline = SVCPipeline()
        sample_path = str(tmp_path / "sample.opus")
        with open(sample_path, "wb") as f:
            f.write(b"dummy")

        with pytest.raises(RuntimeError) as exc_info:
            pipeline.train(sample_audio_path=sample_path, checkpoint_dir=str(tmp_path))

        assert "Simulated SVC training failure" in str(exc_info.value)
