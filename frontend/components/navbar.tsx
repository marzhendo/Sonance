"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { KeyRound, Mic, Radio, Volume2, Waves } from "lucide-react"
import { ThemeToggle } from "@/components/theme-toggle"
import { useAuth } from "@/hooks/use-auth"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

const NAV_ITEMS = [
  { href: "/profiles", label: "Profiles", icon: Mic },
  { href: "/tts", label: "Text to Speech", icon: Volume2 },
  { href: "/voice-changer", label: "Voice Changer", icon: Radio },
]

export function Navbar() {
  const pathname = usePathname()
  const { isAuthenticated, openTokenModal } = useAuth()

  return (
    <header className="sticky top-0 z-40 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container flex h-14 max-w-screen-2xl items-center justify-between px-4 sm:px-8">
        <div className="flex items-center gap-6 md:gap-8">
          <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Waves className="h-4 w-4" />
            </div>
            <span>Sonance</span>
          </Link>
          <nav className="flex items-center gap-1 sm:gap-2">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon
              const isActive = pathname.startsWith(item.href)
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-muted text-foreground"
                      : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                  )}
                >
                  <Icon className="h-4 w-4" />
                  <span>{item.label}</span>
                </Link>
              )
            })}
          </nav>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant={isAuthenticated ? "outline" : "default"}
            size="sm"
            onClick={openTokenModal}
            className="flex items-center gap-1.5 text-xs"
            title={isAuthenticated ? "Kelola API Token" : "Atur API Token"}
          >
            <KeyRound className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">
              {isAuthenticated ? "API Token" : "Set API Token"}
            </span>
          </Button>
          <ThemeToggle />
        </div>
      </div>
    </header>
  )
}
