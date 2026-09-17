"""
Unit tests untuk interface VoiceConversionPipeline dan stub RVCRealtimePipeline.
Wave 3: ML Abstraction & Stub RVCRealtimePipeline.
"""
import pytest
from backend.app.schemas.vc_session_schema import VCSettings


class TestVoiceConversionPipelineInterface:
    """Pengujian kontrak interface abstrak VoiceConversionPipeline."""

    def test_cannot_instantiate_abstract_pipeline_directly(self):
        from backend.ml.base import VoiceConversionPipeline

        with pytest.raises(TypeError):
            VoiceConversionPipeline()


class TestRVCRealtimePipelineStub:
    """Pengujian untuk implementasi stub RVCRealtimePipeline."""

    def test_initial_state_not_loaded(self):
        from backend.ml.rvc import RVCRealtimePipeline

        pipeline = RVCRealtimePipeline()
        assert pipeline.is_loaded() is False

    def test_load_and_unload_lifecycle(self):
        from backend.ml.rvc import RVCRealtimePipeline

        pipeline = RVCRealtimePipeline()
        assert pipeline.is_loaded() is False

        pipeline.load_model("/fake/path/to/model.pth")
        assert pipeline.is_loaded() is True

        pipeline.unload_model()
        assert pipeline.is_loaded() is False

    def test_convert_chunk_success_preserves_length(self):
        from backend.ml.rvc import RVCRealtimePipeline

        pipeline = RVCRealtimePipeline()
        pipeline.load_model("/fake/path/to/model.pth")

        # 960 bytes dummy PCM
        input_pcm = b"\x01\x02" * 480
        output_pcm = pipeline.convert_chunk(input_pcm, {"pitch_shift": 2, "sample_rate": 16000})

        assert isinstance(output_pcm, bytes)
        assert len(output_pcm) == len(input_pcm)

    def test_convert_chunk_accepts_vc_settings_schema(self):
        from backend.ml.rvc import RVCRealtimePipeline

        pipeline = RVCRealtimePipeline()
        pipeline.load_model("/fake/path/to/model.pth")

        settings = VCSettings(pitch_shift=4, sample_rate=24000, chunk_duration_ms=20)
        input_pcm = b"\x00" * 960
        output_pcm = pipeline.convert_chunk(input_pcm, settings)

        assert len(output_pcm) == len(input_pcm)

    def test_convert_chunk_raises_if_not_loaded(self):
        from backend.ml.rvc import RVCRealtimePipeline

        pipeline = RVCRealtimePipeline()
        with pytest.raises(RuntimeError, match="belum dimuat"):
            pipeline.convert_chunk(b"\x00" * 960, {})

    def test_simulate_failure_via_constructor(self):
        from backend.ml.rvc import RVCRealtimePipeline

        pipeline = RVCRealtimePipeline(simulate_failure=True)
        with pytest.raises(RuntimeError, match="Simulated RVC"):
            pipeline.load_model("/fake/path/to/model.pth")

    def test_simulate_failure_via_env_var_load_model(self, monkeypatch):
        from backend.ml.rvc import RVCRealtimePipeline

        monkeypatch.setenv("SONANCE_SIMULATE_VC_FAILURE", "1")
        pipeline = RVCRealtimePipeline()
        with pytest.raises(RuntimeError, match="Simulated RVC"):
            pipeline.load_model("/fake/path/to/model.pth")

    def test_simulate_failure_via_env_var_convert_chunk(self, monkeypatch):
        from backend.ml.rvc import RVCRealtimePipeline

        pipeline = RVCRealtimePipeline()
        pipeline.load_model("/fake/path/to/model.pth")

        monkeypatch.setenv("SONANCE_SIMULATE_VC_FAILURE", "1")
        with pytest.raises(RuntimeError, match="Simulated RVC"):
            pipeline.convert_chunk(b"\x00" * 960, {})
