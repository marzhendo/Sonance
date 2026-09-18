# 04: Voice Profile Creation with Client Audio Validation

**What to build:** A modal dialog for creating a new voice profile, restricting file selection strictly to `.opus`, validating audio duration (10 to 30 seconds) via browser Web Audio API before upload, validating file size (up to 10 MB), showing explicit error alerts, and submitting multipart data to the backend.

**Blocked by:** 03: Voice Profile List and Status Polling

**Status:** ready-for-agent

- [ ] "Create Profile" button opening an accessible modal dialog.
- [ ] File input accepting strictly `.opus` files with drag and drop zone.
- [ ] Web Audio API helper decoding audio data to verify duration is within 10.0 to 30.0 seconds.
- [ ] File size validation enforcing the 10 MB maximum limit.
- [ ] Explicit UI error messages explaining format, duration, and size constraints when invalid.
- [ ] Name input field with trimming and length validation.
- [ ] Form submission posting multipart form data to `POST /api/v1/voice-profiles`.
- [ ] Optimistic or immediate TanStack Query invalidation on success, closing the modal.
