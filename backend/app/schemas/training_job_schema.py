"""
Pydantic schemas untuk Training Job.
Wave 2: Task 2.1 (training job responses).
"""
import uuid

from pydantic import BaseModel


class TrainingJobDispatchResponse(BaseModel):
    """
    Response untuk POST /api/v1/voice-profiles/{id}/train (HTTP 202).
    Dikembalikan saat job berhasil di-dispatch ke Job_Queue.
    """
    training_job_id: uuid.UUID
    status: str  # selalu "queued" saat dispatch berhasil

    model_config = {"from_attributes": True}
