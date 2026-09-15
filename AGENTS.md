<!-- antislop:start -->
## antislop
For UI, copy, people, mobile layout, or code comments work, load the antislop skill for the task:
- Core filter, always on: `antislop`
- Copy & text: `antislop-copywriting`
- People: `antislop-human`
- Mobile / responsive: `antislop-layoutmobile`
- Code comments: `antislop-code`
Before starting, ask the user when antislop applies: during the work, or after it is done.
<!-- antislop:end -->

## Development and Services

### Background Worker and Queue
- Broker: Redis Queue (RQ) configured via `SONANCE_REDIS_URL`.
- Default queue name: `training`.
- Run worker daemon: `python -m backend.workers.training_worker` (requires `SONANCE_REDIS_URL`).
- Tests: Test suite uses in-memory queue fallback (`InMemoryQueue`) by default without requiring an active Redis server.
