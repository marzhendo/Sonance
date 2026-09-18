import { describe, it, beforeEach, afterEach } from "node:test"
import assert from "node:assert/strict"
import {
  apiClient,
  ApiError,
  clearStoredToken,
  getStoredToken,
  registerUnauthorizedListener,
  setStoredToken,
  SONANCE_TOKEN_KEY,
} from "../lib/api-client.ts"

// Simple in-memory localStorage polyfill for Node environment
class MockLocalStorage {
  private store: Map<string, string> = new Map()

  getItem(key: string): string | null {
    return this.store.get(key) ?? null
  }

  setItem(key: string, value: string): void {
    this.store.set(key, value)
  }

  removeItem(key: string): void {
    this.store.delete(key)
  }

  clear(): void {
    this.store.clear()
  }
}

describe("ApiClient & Auth Storage Tests", () => {
  const originalFetch = globalThis.fetch
  const originalWindow = (globalThis as any).window
  const originalLocalStorage = (globalThis as any).localStorage

  beforeEach(() => {
    const mockStorage = new MockLocalStorage()
    ;(globalThis as any).window = globalThis
    ;(globalThis as any).localStorage = mockStorage
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    ;(globalThis as any).window = originalWindow
    ;(globalThis as any).localStorage = originalLocalStorage
  })

  it("stores and retrieves token from localStorage", () => {
    clearStoredToken()
    assert.equal(getStoredToken(), null)

    setStoredToken("test-secret-token-123")
    assert.equal(getStoredToken(), "test-secret-token-123")

    clearStoredToken()
    assert.equal(getStoredToken(), null)
  })

  it("sends Authorization Bearer header when token is present", async () => {
    setStoredToken("my-auth-token")
    let capturedHeaders: HeadersInit | undefined

    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      capturedHeaders = init?.headers
      return new Response(JSON.stringify({ items: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    }

    const profiles = await apiClient.getVoiceProfiles()
    assert.deepEqual(profiles, [])

    const headersRecord = capturedHeaders as Record<string, string>
    assert.equal(headersRecord["Authorization"], "Bearer my-auth-token")
  })

  it("triggers unauthorized listener and throws ApiError on 401", async () => {
    let unauthorizedTriggered = false
    const unsubscribe = registerUnauthorizedListener(() => {
      unauthorizedTriggered = true
    })

    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({ detail: "Token autentikasi tidak valid atau tidak ada." }),
        {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }
      )
    }

    await assert.rejects(
      async () => {
        await apiClient.getVoiceProfiles()
      },
      (err: unknown) => {
        assert(err instanceof ApiError)
        assert.equal(err.statusCode, 401)
        assert.equal(err.isNetworkError, false)
        assert.equal(err.message, "Token autentikasi tidak valid atau tidak ada.")
        return true
      }
    )

    assert.equal(unauthorizedTriggered, true)
    unsubscribe()
  })

  it("handles network failure with isNetworkError true and clear message", async () => {
    globalThis.fetch = async () => {
      throw new TypeError("Failed to fetch")
    }

    await assert.rejects(
      async () => {
        await apiClient.getHealth()
      },
      (err: unknown) => {
        assert(err instanceof ApiError)
        assert.equal(err.statusCode, 0)
        assert.equal(err.isNetworkError, true)
        assert(err.message.includes("Tidak dapat terhubung ke server backend"))
        return true
      }
    )
  })

  it("parses structured FastAPI 422 validation error details", async () => {
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({
          detail: [
            { loc: ["body", "name"], msg: "Nama tidak boleh kosong", type: "value_error" },
            { loc: ["body", "source_type"], msg: "Field source_type tidak valid", type: "value_error" },
          ],
        }),
        {
          status: 422,
          headers: { "Content-Type": "application/json" },
        }
      )
    }

    await assert.rejects(
      async () => {
        await apiClient.renameVoiceProfile("dummy-id", "")
      },
      (err: unknown) => {
        assert(err instanceof ApiError)
        assert.equal(err.statusCode, 422)
        assert.equal(err.isNetworkError, false)
        assert(err.message.includes("Nama tidak boleh kosong"))
        assert(err.message.includes("Field source_type tidak valid"))
        return true
      }
    )
  })

  it("validates token successfully when endpoint returns 200", async () => {
    globalThis.fetch = async () => {
      return new Response(JSON.stringify({ items: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    }

    const isValid = await apiClient.validateToken("valid-token")
    assert.equal(isValid, true)
  })
})
