# 07: TTS Job History and Audio Waveform Player

**What to build:** The TTS job history list showing job statuses with background polling, alongside an audio playback interface to listen to synthesized `.opus` files with seek, play/pause controls, and direct download links.

**Blocked by:** 06: TTS Generation Form and Voice Profile Selector

**Status:** ready-for-agent

- [ ] Job history table/card list querying `GET /api/v1/tts/jobs`.
- [ ] Automated polling interval (refetch every 2-3s) while any job is in `queued` or `processing` status.
- [ ] Status badges for queued, processing, completed, and failed jobs.
- [ ] Embedded audio player component supporting `.opus` audio playback from `GET /api/v1/tts/jobs/{id}/audio`.
- [ ] Play, pause, progress bar seek, and time indicator controls.
- [ ] Direct download button for completed audio files.
