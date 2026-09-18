# 08: Web Audio API Microphone Capture and PCM Framing

**What to build:** Audio input and output processing in the browser using the Web Audio API, capturing raw microphone audio, converting Float32 samples to 16-bit mono PCM chunks of 10 to 100 ms duration, calculating live RMS audio levels, and providing a PCM chunk playback queue.

**Blocked by:** 01: Project Setup, Tooling, and Theme Shell

**Status:** ready-for-agent

- [ ] Audio helper module in `lib/audio/pcm.ts` for Float32 to 16-bit signed integer PCM conversion.
- [ ] React hook `useAudioCapture` managing microphone permission, stream acquisition, and frame slicing.
- [ ] Configurable sample rate (16000, 24000, 44100, 48000 Hz) and chunk duration (10 to 100 ms).
- [ ] Real-time audio input level (RMS / decibels) calculation for UI metering.
- [ ] Audio buffer queue playback helper to smoothly play returned 16-bit PCM chunks without clicks or gaps.
