"use client"

import * as React from "react"
import {
  clearStoredToken,
  getStoredToken,
  registerUnauthorizedListener,
  setStoredToken,
} from "@/lib/api-client"

interface AuthContextValue {
  token: string | null
  isAuthenticated: boolean
  isLoading: boolean
  isTokenModalOpen: boolean
  setToken: (token: string) => void
  clearToken: () => void
  openTokenModal: () => void
  closeTokenModal: () => void
}

const AuthContext = React.createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setTokenState] = React.useState<string | null>(null)
  const [isLoading, setIsLoading] = React.useState(true)
  const [isTokenModalOpen, setIsTokenModalOpen] = React.useState(false)

  React.useEffect(() => {
    const existingToken = getStoredToken()
    if (existingToken) {
      setTokenState(existingToken)
    } else {
      setIsTokenModalOpen(true)
    }
    setIsLoading(false)

    // Listen to 401 unauthorized responses across the entire application
    const unregister = registerUnauthorizedListener(() => {
      setIsTokenModalOpen(true)
    })

    return () => {
      unregister()
    }
  }, [])

  const setToken = React.useCallback((newToken: string) => {
    const sanitized = newToken.trim()
    setStoredToken(sanitized)
    setTokenState(sanitized)
    setIsTokenModalOpen(false)
  }, [])

  const clearToken = React.useCallback(() => {
    clearStoredToken()
    setTokenState(null)
    setIsTokenModalOpen(true)
  }, [])

  const openTokenModal = React.useCallback(() => {
    setIsTokenModalOpen(true)
  }, [])

  const closeTokenModal = React.useCallback(() => {
    setIsTokenModalOpen(false)
  }, [])

  const value = React.useMemo<AuthContextValue>(
    () => ({
      token,
      isAuthenticated: Boolean(token),
      isLoading,
      isTokenModalOpen,
      setToken,
      clearToken,
      openTokenModal,
      closeTokenModal,
    }),
    [
      token,
      isLoading,
      isTokenModalOpen,
      setToken,
      clearToken,
      openTokenModal,
      closeTokenModal,
    ]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = React.useContext(AuthContext)
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider")
  }
  return context
}
