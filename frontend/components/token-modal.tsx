"use client"

import * as React from "react"
import { AlertCircle, CheckCircle2, KeyRound, Loader2, LogOut } from "lucide-react"
import { toast } from "sonner"
import { apiClient, ApiError } from "@/lib/api-client"
import { useAuth } from "@/hooks/use-auth"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

export function TokenModal() {
  const {
    token,
    setToken,
    clearToken,
    isTokenModalOpen,
    closeTokenModal,
    isAuthenticated,
  } = useAuth()

  const [inputToken, setInputToken] = React.useState("")
  const [isValidating, setIsValidating] = React.useState(false)
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null)
  const [isNetworkError, setIsNetworkError] = React.useState(false)

  React.useEffect(() => {
    if (isTokenModalOpen) {
      setInputToken(token || "")
      setErrorMessage(null)
      setIsNetworkError(false)
    }
  }, [isTokenModalOpen, token])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const candidate = inputToken.trim()

    if (!candidate) {
      setErrorMessage("Token API tidak boleh kosong.")
      setIsNetworkError(false)
      return
    }

    setIsValidating(true)
    setErrorMessage(null)
    setIsNetworkError(false)

    try {
      await apiClient.validateToken(candidate)
      setToken(candidate)
      toast.success("Token API berhasil diverifikasi.")
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.isNetworkError) {
          setIsNetworkError(true)
          setErrorMessage(
            "Tidak dapat terhubung ke server backend. Pastikan server FastAPI sedang berjalan."
          )
          toast.error("Gagal terhubung ke backend")
        } else if (err.statusCode === 401) {
          setIsNetworkError(false)
          setErrorMessage(
            "Token tidak valid. Pastikan token sesuai dengan SONANCE_API_TOKEN di backend."
          )
          toast.error("Token API ditolak (401)")
        } else {
          setIsNetworkError(false)
          setErrorMessage(err.message || "Gagal memverifikasi token.")
          toast.error("Verifikasi token gagal")
        }
      } else {
        setIsNetworkError(false)
        setErrorMessage("Terjadi kesalahan tak terduga saat memvalidasi token.")
        toast.error("Terjadi kesalahan sistem")
      }
    } finally {
      setIsValidating(false)
    }
  }

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      if (!isAuthenticated) {
        // Jangan izinkan tutup modal jika belum terautentikasi
        return
      }
      closeTokenModal()
    }
  }

  return (
    <Dialog open={isTokenModalOpen} onOpenChange={handleOpenChange}>
      <DialogContent showCloseButton={isAuthenticated} className="sm:max-w-md">
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <DialogHeader>
            <div className="flex items-center gap-2">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <KeyRound className="h-5 w-5" />
              </div>
              <div>
                <DialogTitle>Autentikasi API Sonance</DialogTitle>
                <DialogDescription>
                  Masukkan token bearer untuk mengakses endpoint backend.
                </DialogDescription>
              </div>
            </div>
          </DialogHeader>

          {errorMessage && (
            <div
              className={`flex items-start gap-2.5 rounded-lg border p-3 text-xs leading-relaxed ${
                isNetworkError
                  ? "border-amber-500/30 bg-amber-500/10 text-amber-950 dark:text-amber-200"
                  : "border-destructive/30 bg-destructive/10 text-destructive dark:text-destructive"
              }`}
              role="alert"
            >
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <div className="flex-1">
                <p className="font-medium">
                  {isNetworkError ? "Koneksi Bermasalah" : "Validasi Gagal"}
                </p>
                <p className="mt-0.5">{errorMessage}</p>
              </div>
            </div>
          )}

          <div className="flex flex-col gap-2">
            <Label htmlFor="api-token">SONANCE_API_TOKEN</Label>
            <Input
              id="api-token"
              type="password"
              autoComplete="off"
              placeholder="Masukkan bearer token..."
              value={inputToken}
              onChange={(e) => {
                setInputToken(e.target.value)
                if (errorMessage) setErrorMessage(null)
              }}
              disabled={isValidating}
              autoFocus
            />
            <p className="text-[0.75rem] text-muted-foreground">
              Token ini akan disimpan di browser (localStorage) dan dikirimkan pada setiap permintaan API.
            </p>
          </div>

          <DialogFooter className="gap-2 sm:justify-between">
            {isAuthenticated ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                onClick={() => {
                  clearToken()
                  setInputToken("")
                  toast.info("Token API telah dihapus.")
                }}
                disabled={isValidating}
              >
                <LogOut className="mr-1.5 h-3.5 w-3.5" />
                Hapus Token
              </Button>
            ) : (
              <div />
            )}

            <div className="flex gap-2">
              {isAuthenticated && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={closeTokenModal}
                  disabled={isValidating}
                >
                  Batal
                </Button>
              )}
              <Button type="submit" size="sm" disabled={isValidating}>
                {isValidating ? (
                  <>
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    Memverifikasi...
                  </>
                ) : (
                  <>
                    <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" />
                    Simpan Token
                  </>
                )}
              </Button>
            </div>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
