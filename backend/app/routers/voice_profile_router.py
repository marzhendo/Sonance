import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from backend.app.core.auth import verify_token
from backend.app.core.database import get_db
from backend.app.schemas.training_job_schema import TrainingJobDispatchResponse
from backend.app.schemas.voice_profile_schema import (
    SourceType,
    VoiceProfileListResponse,
    VoiceProfileRenameRequest,
    VoiceProfileResponse,
    VoiceProfileStatusResponse,
)
from backend.app.services.training_job_service import TrainingJobService
from backend.app.services.voice_profile_service import VoiceProfileService

router = APIRouter(prefix="/voice-profiles", tags=["voice-profiles"])

MAX_SAMPLE_AUDIO_SIZE = 10 * 1024 * 1024
voice_profile_service = VoiceProfileService()
training_job_service = TrainingJobService()


@router.post(
    "",
    response_model=VoiceProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Buat Voice Profile baru",
)
async def create_voice_profile(
    name: str = Form(...),
    source_type: str = Form(...),
    sample_audio: UploadFile = File(...),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    trimmed_name = name.strip() if isinstance(name, str) else ""
    if not trimmed_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Nama tidak boleh kosong atau hanya berisi whitespace.",
        )
    if len(trimmed_name) > 255:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Nama tidak boleh melebihi 255 karakter setelah di-trim.",
        )

    try:
        valid_source = SourceType(source_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Field source_type tidak valid.",
        )

    if not sample_audio or not sample_audio.filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="File sample audio wajib diunggah.",
        )

    audio_bytes = await sample_audio.read()
    if not audio_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="File sample audio tidak boleh kosong.",
        )

    if len(audio_bytes) > MAX_SAMPLE_AUDIO_SIZE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Ukuran file audio melebihi batas maksimum 10 MB.",
        )

    return voice_profile_service.create(
        user_id=user_id,
        name=trimmed_name,
        source_type=valid_source,
        sample_audio=audio_bytes,
        db=db,
    )


@router.get(
    "",
    response_model=VoiceProfileListResponse,
    status_code=status.HTTP_200_OK,
    summary="Daftar Voice Profile milik user",
)
def list_voice_profiles(
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    items = voice_profile_service.list(user_id=user_id, db=db)
    return VoiceProfileListResponse(items=items)


@router.get(
    "/{id}",
    response_model=VoiceProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Detail Voice Profile",
)
def get_voice_profile(
    id: uuid.UUID,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    return voice_profile_service.get(
        voice_profile_id=id,
        user_id=user_id,
        db=db,
    )


@router.patch(
    "/{id}",
    response_model=VoiceProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Ubah nama Voice Profile",
)
def rename_voice_profile(
    id: uuid.UUID,
    payload: VoiceProfileRenameRequest,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    return voice_profile_service.rename(
        voice_profile_id=id,
        user_id=user_id,
        new_name=payload.name,
        db=db,
    )


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Hapus Voice Profile",
)
def delete_voice_profile(
    id: uuid.UUID,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    voice_profile_service.delete(
        voice_profile_id=id,
        user_id=user_id,
        db=db,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{id}/train",
    response_model=TrainingJobDispatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Mulai proses training untuk Voice Profile",
)
def train_voice_profile(
    id: uuid.UUID,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    return training_job_service.dispatch(
        voice_profile_id=id,
        user_id=user_id,
        db=db,
    )


@router.get(
    "/{id}/status",
    response_model=VoiceProfileStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Ambil status training Voice Profile",
)
def get_voice_profile_status(
    id: uuid.UUID,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    return voice_profile_service.get_status(
        voice_profile_id=id,
        user_id=user_id,
        db=db,
    )
