from fastapi import FastAPI

from backend.app.routers.tts_router import router as tts_router
from backend.app.routers.vc_router import router as vc_router
from backend.app.routers.voice_profile_router import router as voice_profile_router


def create_app() -> FastAPI:
    """Factory function untuk membuat instans aplikasi FastAPI Sonance."""
    app = FastAPI(
        title="Sonance API",
        version="0.1.0",
        description="Sonance Voice Cloning and Real-time Voice Changer API",
    )

    app.include_router(voice_profile_router, prefix="/api/v1")
    app.include_router(tts_router, prefix="/api/v1/tts")
    app.include_router(vc_router)

    @app.get("/health", tags=["system"], summary="Health check")
    def health_check():
        return {"status": "ok"}

    return app


app = create_app()
