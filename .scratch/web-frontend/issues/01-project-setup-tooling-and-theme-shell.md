# 01: Project Setup, Tooling, and Theme Shell

**What to build:** The foundational web frontend shell for Sonance using Next.js 14 App Router, TypeScript, Tailwind CSS, shadcn/ui components, Lucide icons, dark/light theme switching, TanStack Query provider, and global toast notifications.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] Next.js 14 project created in `frontend/` with App Router, TypeScript, and Tailwind CSS.
- [x] Directory structure established: `app/`, `components/`, `lib/`, `hooks/`.
- [x] shadcn/ui configured with base components: Button, Card, Badge, Dialog, Sonner (Toast).
- [x] Theme toggle supporting dark and light modes via `next-themes`.
- [x] TanStack Query provider and Sonner toast container mounted in root layout.
- [x] Environment file `.env.local.example` created with `NEXT_PUBLIC_API_BASE_URL`.
- [x] `npm run dev` and `npm run build` pass cleanly without errors.
