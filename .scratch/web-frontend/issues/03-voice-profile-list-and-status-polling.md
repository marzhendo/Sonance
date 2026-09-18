# 03: Voice Profile List and Status Polling

**What to build:** The `/profiles` dashboard page rendering existing voice profiles in a responsive grid, with status badges (pending, processing, ready, failed) and automated background polling for profiles under active processing or training.

**Blocked by:** 02: API Client, Auth Context, and Token Modal

**Status:** ready-for-agent

- [ ] Route page `/profiles` with header and responsive grid layout.
- [ ] Profile card component displaying profile name, status badge, sample duration, and creation date.
- [ ] TanStack Query hook `useVoiceProfiles` fetching profile list from `GET /api/v1/voice-profiles`.
- [ ] Conditional refetch interval (2-3 seconds) when any profile status is `pending` or `processing`.
- [ ] Empty state illustration and loading skeletons for initial fetch.
