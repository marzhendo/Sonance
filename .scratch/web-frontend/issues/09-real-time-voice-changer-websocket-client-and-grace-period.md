# 09: Real-time Voice Changer WebSocket Client and Grace Period

**What to build:** A resilient WebSocket client hook communicating with `/ws/voice-changer`, implementing dual-framing (JSON text control messages and binary 16-bit PCM chunks), tracking session lifecycle states, and handling reconnection within the 10-second grace period.

**Blocked by:** 02: API Client, Auth Context, and Token Modal; 08: Web Audio API Microphone Capture and PCM Framing

**Status:** ready-for-agent

- [ ] React hook `useVoiceChangerSocket` managing connection to `/ws/voice-changer?token={token}`.
- [ ] Session state machine management: `DISCONNECTED`, `CONNECTING`, `INITIALIZING`, `ACTIVE`, `GRACE_PERIOD`, `ENDED`.
- [ ] Dispatching `init_session`, `update_settings`, and `close_session` JSON messages.
- [ ] Binary framing sender for input PCM chunks and receiver for converted PCM chunks.
- [ ] Parsing server messages: `session_ready`, `settings_updated`, `metrics`, `error`, and `session_closed`.
- [ ] Grace period reconnect logic using `reconnect_session_id` when disconnected unexpectedly within 10 seconds.
