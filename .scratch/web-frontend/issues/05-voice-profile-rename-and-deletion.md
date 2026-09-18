# 05: Voice Profile Rename and Deletion

**What to build:** Inline or modal renaming for voice profiles, along with a destructive confirmation dialog for profile deletion, handling active session conflicts (409) gracefully and synchronizing query cache.

**Blocked by:** 03: Voice Profile List and Status Polling

**Status:** ready-for-agent

- [ ] Rename dialog or inline edit triggering `PATCH /api/v1/voice-profiles/{id}`.
- [ ] Delete confirmation dialog warning the user of permanent data deletion.
- [ ] Delete mutation calling `DELETE /api/v1/voice-profiles/{id}`.
- [ ] Error handling for 409 conflict when a voice profile is locked or in use by an active session.
- [ ] Cache invalidation on successful mutation and feedback toast notifications.
