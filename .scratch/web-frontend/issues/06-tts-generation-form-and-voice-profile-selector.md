# 06: TTS Generation Form and Voice Profile Selector

**What to build:** The speech synthesis configuration form on `/tts`, enabling users to enter text, select from available `ready` voice profiles, fine-tune voice parameters (language, speed, pitch shift, temperature), and submit TTS generation jobs.

**Blocked by:** 02: API Client, Auth Context, and Token Modal; 03: Voice Profile List and Status Polling

**Status:** ready-for-agent

- [ ] Route page `/tts` layout with generation form and job history sections.
- [ ] Textarea input with character counter and non-empty validation.
- [ ] Profile selector dropdown populated exclusively with profiles having `status === "ready"`.
- [ ] Language select dropdown (e.g. id, en, ja).
- [ ] Sliders with numerical readouts for speed (0.5 to 2.0, default 1.0), pitch shift (-12 to 12 semitones, default 0), and temperature (0.1 to 1.0, default 0.7).
- [ ] Mutation dispatching `POST /api/v1/tts/jobs` with form payload and loading button state.
