import type {
  ApiErrorDetail,
  ApiErrorResponse,
  TrainingJobDispatchResponse,
  TTSGenerateRequest,
  TTSJob,
  TTSJobListResponse,
  VoiceProfile,
  VoiceProfileCreatePayload,
  VoiceProfileListResponse,
  VoiceProfileStatusResponse,
} from "./types"

export const SONANCE_TOKEN_KEY = "sonance_api_token"

export class ApiError extends Error {
  public readonly statusCode: number
  public readonly detail: unknown
  public readonly isNetworkError: boolean

  constructor(
    message: string,
    statusCode: number,
    detail?: unknown,
    isNetworkError = false
  ) {
    super(message)
    this.name = "ApiError"
    this.statusCode = statusCode
    this.detail = detail
    this.isNetworkError = isNetworkError
  }
}

type UnauthorizedListener = () => void
const unauthorizedListeners = new Set<UnauthorizedListener>()

export function registerUnauthorizedListener(listener: UnauthorizedListener): () => void {
  unauthorizedListeners.add(listener)
  return () => {
    unauthorizedListeners.delete(listener)
  }
}

function notifyUnauthorized(): void {
  unauthorizedListeners.forEach((listener) => {
    try {
      listener()
    } catch {
      // Ignore listener error to prevent unhandled rejection
    }
  })
}

export function getStoredToken(): string | null {
  if (typeof window === "undefined") {
    return null
  }
  const fromStorage = localStorage.getItem(SONANCE_TOKEN_KEY)
  if (fromStorage && fromStorage.trim()) {
    return fromStorage.trim()
  }
  const fromEnv = process.env.NEXT_PUBLIC_API_TOKEN
  if (fromEnv && fromEnv.trim()) {
    return fromEnv.trim()
  }
  return null
}

export function setStoredToken(token: string): void {
  if (typeof window !== "undefined") {
    localStorage.setItem(SONANCE_TOKEN_KEY, token.trim())
  }
}

export function clearStoredToken(): void {
  if (typeof window !== "undefined") {
    localStorage.removeItem(SONANCE_TOKEN_KEY)
  }
}

export function getApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/+$/, "") || "http://localhost:8000"
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE"
  token?: string | null
  headers?: Record<string, string>
  body?: unknown
  isFormData?: boolean
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const baseUrl = getApiBaseUrl()
  const url = `${baseUrl}${path.startsWith("/") ? path : `/${path}`}`

  const headers: Record<string, string> = {
    ...options.headers,
  }

  if (!options.isFormData && options.body !== undefined) {
    headers["Content-Type"] = "application/json"
  }

  const token = options.token !== undefined ? options.token : getStoredToken()
  if (token) {
    headers["Authorization"] = `Bearer ${token}`
  }

  let fetchBody: BodyInit | undefined
  if (options.isFormData && options.body instanceof FormData) {
    fetchBody = options.body
  } else if (options.body !== undefined) {
    fetchBody = JSON.stringify(options.body)
  }

  let response: Response
  try {
    response = await fetch(url, {
      method: options.method || "GET",
      headers,
      body: fetchBody,
    })
  } catch (error) {
    const message = `Tidak dapat terhubung ke server backend di ${baseUrl}. Pastikan server FastAPI berjalan.`
    throw new ApiError(message, 0, error, true)
  }

  if (!response.ok) {
    if (response.status === 401) {
      notifyUnauthorized()
    }

    let parsedDetail: unknown = null
    let errorMessage = `Request gagal dengan status ${response.status}`

    try {
      const errorJson = (await response.json()) as ApiErrorResponse
      parsedDetail = errorJson.detail

      if (typeof errorJson.detail === "string") {
        errorMessage = errorJson.detail
      } else if (Array.isArray(errorJson.detail)) {
        const details = errorJson.detail as ApiErrorDetail[]
        errorMessage = details
          .map((d) => d.msg || "Validasi gagal")
          .filter(Boolean)
          .join(", ")
      }
    } catch {
      // Body bukan JSON
    }

    if (response.status === 401 && !parsedDetail) {
      errorMessage = "Token autentikasi tidak valid atau tidak ada."
    }

    throw new ApiError(errorMessage, response.status, parsedDetail, false)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}

export const apiClient = {
  getHealth: () => request<{ status: string }>("/health"),

  validateToken: async (token: string): Promise<boolean> => {
    await request<VoiceProfileListResponse>("/api/v1/voice-profiles", {
      method: "GET",
      token,
    })
    return true
  },

  getVoiceProfiles: async (): Promise<VoiceProfile[]> => {
    const data = await request<VoiceProfileListResponse>("/api/v1/voice-profiles")
    return data.items
  },

  getVoiceProfile: (id: string): Promise<VoiceProfile> =>
    request<VoiceProfile>(`/api/v1/voice-profiles/${id}`),

  createVoiceProfile: (payload: VoiceProfileCreatePayload): Promise<VoiceProfile> => {
    const formData = new FormData()
    formData.append("name", payload.name)
    formData.append("source_type", payload.source_type)
    formData.append("sample_audio", payload.sample_audio)

    return request<VoiceProfile>("/api/v1/voice-profiles", {
      method: "POST",
      body: formData,
      isFormData: true,
    })
  },

  renameVoiceProfile: (id: string, name: string): Promise<VoiceProfile> =>
    request<VoiceProfile>(`/api/v1/voice-profiles/${id}`, {
      method: "PATCH",
      body: { name },
    }),

  deleteVoiceProfile: (id: string): Promise<void> =>
    request<void>(`/api/v1/voice-profiles/${id}`, {
      method: "DELETE",
    }),

  trainVoiceProfile: (id: string): Promise<TrainingJobDispatchResponse> =>
    request<TrainingJobDispatchResponse>(`/api/v1/voice-profiles/${id}/train`, {
      method: "POST",
    }),

  getVoiceProfileStatus: (id: string): Promise<VoiceProfileStatusResponse> =>
    request<VoiceProfileStatusResponse>(`/api/v1/voice-profiles/${id}/status`),

  generateTTS: (payload: TTSGenerateRequest): Promise<TTSJob> =>
    request<TTSJob>("/api/v1/tts/generate", {
      method: "POST",
      body: payload,
    }),

  getTTSJobs: async (): Promise<TTSJob[]> => {
    const data = await request<TTSJobListResponse | TTSJob[]>("/api/v1/tts/jobs")
    if (Array.isArray(data)) {
      return data
    }
    return data.items || []
  },

  getTTSJob: (id: string): Promise<TTSJob> =>
    request<TTSJob>(`/api/v1/tts/jobs/${id}`),

  getTTSAudioUrl: (id: string): string => {
    const baseUrl = getApiBaseUrl()
    return `${baseUrl}/api/v1/tts/jobs/${id}/audio`
  },
}
