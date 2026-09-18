# 11: End-to-End Verification, Antislop Audit, and Build Check

**What to build:** Comprehensive validation of the Sonance frontend application across all pages, verifying routing, theme persistence, error toast handling, antislop copywriting standards, and successful production build.

**Blocked by:** 04: Voice Profile Creation with Client Audio Validation; 05: Voice Profile Rename and Deletion; 07: TTS Job History and Audio Waveform Player; 10: Real-time Voice Changer Studio Interface

**Status:** ready-for-agent

- [ ] End-to-end user journeys tested across `/profiles`, `/tts`, and `/voice-changer`.
- [ ] Navigation header links active states correctly across all pages.
- [ ] Antislop audit verifying clean, natural prose without artificial AI clichés or em dashes.
- [ ] Theme switcher persists dark and light modes cleanly without layout flash.
- [ ] Production compilation `npm run build` succeeds without type errors or lint warnings.
