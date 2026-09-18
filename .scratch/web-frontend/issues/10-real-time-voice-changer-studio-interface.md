# 10: Real-time Voice Changer Studio Interface

**What to build:** The complete interactive studio page at `/voice-changer`, enabling users to choose a ready voice profile, adjust audio parameters live, view real-time input and output VU meters, track latency metrics, and control conversion start/stop.

**Blocked by:** 03: Voice Profile List and Status Polling; 09: Real-time Voice Changer WebSocket Client and Grace Period

**Status:** ready-for-agent

- [ ] Route page `/voice-changer` layout with profile picker, control bar, and telemetry panels.
- [ ] Profile dropdown selecting available `ready` voice profiles.
- [ ] Pitch shift live slider (-12 to +12 semitones) that sends `update_settings` on the fly without session reinit.
- [ ] Sample rate selector (16000, 24000, 44100, 48000 Hz) and chunk duration slider (10 to 100 ms).
- [ ] Live visual VU meter canvas or CSS bar for input mic volume and output audio volume.
- [ ] Real-time latency metrics display (average conversion time, chunk count, round-trip estimate).
- [ ] Start and Stop conversion controls with responsive session state badges.
