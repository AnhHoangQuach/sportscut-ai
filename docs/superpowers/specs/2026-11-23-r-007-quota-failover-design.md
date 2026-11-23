# R-007: Two-way quota failover

## Goal

Keep the office moving when exactly one subscription is quota-limited, without changing the normal Claude/Codex division of work while both subscriptions are available.

## Behaviour

- Normal: Claude remains PM, Tech Lead and reviewer; Codex remains developer and tester.
- Claude quota/daily budget rest: Codex runs Claude steps with a read-only sandbox.
- Codex quota/daily budget rest: Claude runs dev/test with write tools only in the task worktree.
- Both resting: dispatch no work and wait for the earliest reset.
- Busy sessions and repeated CLI failures do not trigger failover.
- Interrupted work is checkpointed before the replacement agent resumes it.
- `agent_failover` records the preferred agent, replacement, step and reason.

## Files

- `agent-office/agent_office/{models,scheduler,pipeline,stats}.py`
- `agent-office/agent_office/agents/{claude,codex}.py`
- `agent-office/agent_office/dashboard/static/app.js`
- `agent-office/tests/{fake_agent,test_environment,test_parallel,test_pipeline}.py`
- `docs/{01-multi-agent,02-quota-song-song-rao-chan,06-code-implementation}.md`

## Measurement

The fake-agent suite covers both failover directions, both-available and both-resting states. Acceptance command: `cd agent-office && python -m pytest -q`.

