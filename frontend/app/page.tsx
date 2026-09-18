import Link from "next/link"
import { ArrowRight, Mic, Radio, Volume2 } from "lucide-react"
import { buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

const MODULES = [
  {
    title: "Voice Profiles",
    description:
      "Upload reference audio samples (.opus format, 10 to 30 seconds), monitor model training, and manage ready voice identities.",
    href: "/profiles",
    icon: Mic,
    badge: "Core",
    action: "Manage Profiles",
  },
  {
    title: "Text to Speech",
    description:
      "Synthesize speech from text using trained voice profiles with granular control over speed, pitch shift, and temperature.",
    href: "/tts",
    icon: Volume2,
    badge: "Offline TTS",
    action: "Open Studio",
  },
  {
    title: "Voice Changer",
    description:
      "Low-latency real-time voice conversion over WebSocket streaming with live pitch shifting and automatic session recovery.",
    href: "/voice-changer",
    icon: Radio,
    badge: "Real-time",
    action: "Launch Session",
  },
]

export default function HomePage() {
  return (
    <div className="container max-w-screen-xl px-4 py-12 md:py-20 sm:px-8">
      <div className="mx-auto max-w-3xl text-center">
        <Badge variant="outline" className="mb-4">
          Sonance Voice AI
        </Badge>
        <h1 className="text-4xl font-bold tracking-tight sm:text-5xl md:text-6xl">
          Voice Profile, Speech Synthesis, and Real-time Voice Changer
        </h1>
        <p className="mt-4 text-base text-muted-foreground sm:text-lg">
          Integrated audio suite powered by FastAPI backend and GPU-accelerated neural pipelines.
        </p>
      </div>

      <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {MODULES.map((module) => {
          const Icon = module.icon
          return (
            <Card key={module.title} className="flex flex-col justify-between transition-all hover:border-foreground/20">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Icon className="h-5 w-5" />
                  </div>
                  <Badge variant="secondary">{module.badge}</Badge>
                </div>
                <CardTitle className="mt-4 text-xl">{module.title}</CardTitle>
                <CardDescription className="text-sm leading-relaxed">
                  {module.description}
                </CardDescription>
              </CardHeader>
              <CardContent className="pt-0">
                <Link
                  href={module.href}
                  className={cn(buttonVariants({ variant: "outline" }), "w-full justify-between")}
                >
                  <span>{module.action}</span>
                  <ArrowRight className="h-4 w-4" />
                </Link>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
