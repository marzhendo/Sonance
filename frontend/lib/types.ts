/**
 * TypeScript type definitions matching backend Pydantic schemas.
 */

// ---------------------------------------------------------------------------
// Common & Voice Profile Types
// ---------------------------------------------------------------------------

export type SourceType = "own_voice" | "other_person" | "character"

export type VoiceProfileStatus = "pending" | "processing" | "ready" | "failed"

export interface VoiceProfile {
  id: string
  name: string
  source_type: SourceType
  status: VoiceProfileStatus
  duration_seconds: number
  error_message?: string | null
  created_at: string
  updated_at: string
}

export interface VoiceProfileListResponse {
  items: VoiceProfile[]
}

export interface TrainingJobStatusResponse {
  status: string
  progress_pct: number
  started_at?: string | null
  completed_at?: string | null
}

export interface VoiceProfileStatusResponse {
  id: string
  status: VoiceProfileStatus
  error_message?: string | null
  training_job?: TrainingJobStatusResponse | null
}

export interface TrainingJobDispatchResponse {
  training_job_id: string
  status: string
}

export interface VoiceProfileCreatePayload {
  name: string
  source_type: SourceType
  sample_audio: File
}

export interface VoiceProfileRenamePayload {
  name: string
}

// ---------------------------------------------------------------------------
// TTS Types
// ---------------------------------------------------------------------------

export type TTSJobStatus = "queued" | "processing" | "completed" | "failed"

export interface TTSSettings {
  language: "id" | "en"
  speed: number
  pitch_shift: number
  temperature: number
  output_format: "opus"
}

export interface TTSGenerateRequest {
  voice_profile_id: string
  text: string
  settings?: Partial<TTSSettings>
}

export interface TTSJob {
  id: string
  status: TTSJobStatus
  input_text: string
  voice_profile_id: string
  settings: TTSSettings
  error_message?: string | null
  created_at: string
  started_at?: string | null
  completed_at?: string | null
}

export interface TTSJobListResponse {
  items: TTSJob[]
}

// ---------------------------------------------------------------------------
// Real-time Voice Changer Types
// ---------------------------------------------------------------------------

export type VCErrorCode =
  | "AUTH_FAILED"
  | "PROFILE_NOT_FOUND"
  | "PROFILE_NOT_READY"
  | "GPU_BUSY"
  | "INVALID_STATE"
  | "INVALID_PAYLOAD"
  | "MODEL_LOAD_FAILED"
  | "INFERENCE_FAILED"
  | "SESSION_EXPIRED"

export interface VCSettings {
  pitch_shift: number
  sample_rate: 16000 | 24000 | 44100 | 48000
  chunk_duration_ms: number
}

export interface VCSettingsUpdate {
  pitch_shift?: number
}

export interface InitSessionMessage {
  type: "init_session"
  voice_profile_id?: string
  session_id?: string
  settings?: VCSettings
}

export interface UpdateSettingsMessage {
  type: "update_settings"
  settings: VCSettingsUpdate
}

export interface CloseSessionMessage {
  type: "close_session"
}

export type ClientMessage =
  | InitSessionMessage
  | UpdateSettingsMessage
  | CloseSessionMessage

export interface SessionReadyMessage {
  type: "session_ready"
  session_id: string
  reconnected: boolean
}

export interface MetricsMessage {
  type: "metrics"
  latency_ms: number
  processing_ms: number
}

export interface ErrorMessage {
  type: "error"
  code: VCErrorCode
  message: string
}

export type ServerMessage =
  | SessionReadyMessage
  | MetricsMessage
  | ErrorMessage

// ---------------------------------------------------------------------------
// Client State & Error Types
// ---------------------------------------------------------------------------

export interface ApiErrorDetail {
  loc?: (string | number)[]
  msg?: string
  type?: string
}

export interface ApiErrorResponse {
  detail?: string | ApiErrorDetail[]
}
