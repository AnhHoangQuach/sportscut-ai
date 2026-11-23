# Server errors (codex-lb 502) retry in minutes and the other CLI covers the work

Request: PO (Hoang) 2026-11-23: "đã triển khai tính năng khi agent hết lỗi cli thì tự động triển khai
lấy task làm tiếp chưa" with a dashboard screenshot: Developer and Tester (Codex through codex-lb)
resting "CLI lỗi codex" for ~30 minutes after `turn.failed ... unexpected status 502 Bad Gateway`,
Tester rested 13 times that day, while PM and Tech Lead (Claude) sat idle.

## Root cause
- A 502 from the proxy was an unexplained failure: after 2 of them the CLI rested as `failure` on
  the 15 → 30 → 60 minute ladder, and every failed probe climbed the ladder again.
- Failover (R-007, roles split) ran only for `quota`, `budget`, `env`, so nobody took dev/test.

## Design
- `limits.TRANSIENT_PATTERNS` + `transient_error(stdout, stderr, exit_code)`: 502/503/504, Bad
  Gateway, Service Unavailable, Gateway Timeout, connection refused/reset/closed, ECONNREFUSED,
  "error sending request", "stream disconnected before completion", "upstream connect error",
  "... timed out". Failed runs only, tail only (like limit phrases). "AssertionError: 502 != 200" is
  not a match.
- `_call`: one transient error rests the CLI at once with cause `upstream`; ladder
  `[limits] upstream_retry_minutes = [1, 2, 5]` (last value repeats). A new outage starts at 1 min.
- `_wake` for `upstream`: `CliAgent.server_problem()` first (Codex: TCP connect to the provider's
  `base_url`, e.g. codex-lb `:2455`); still down → rest again without a probe. A probe failing with a
  transient error stays `upstream`.
- Failover for every rest cause (`FAILOVER_CAUSES` in `scheduler.py`), including `upstream` and
  `failure`: the other CLI keeps the work moving (refines R-007).
- One chat message per outage (who covers); the awake message and event say why work resumes
  (`agent_awake.cause`). Dashboard: label "máy chủ lỗi tạm thời", "thử lại lúc", card line
  "→ PM @claude đang làm thay" (`covered_by` in `/api/state`), event "làm tiếp (máy chủ chạy lại)".

## Files
`agent-office/agent_office/{limits,config,scheduler,pipeline,models,codex_provider,cli}.py`,
`agent_office/agents/{base,codex}.py`, `agent_office/dashboard/{server.py,static/app.js,static/office.js}`,
`agent-office/tests/{test_upstream,test_dashboard,fake_agent}.py`, `docs/01`, `docs/02`.

## Acceptance
- A 502 on a dev run rests Codex for 1 minute, cause `upstream`, and Claude (PM) runs the dev step
  right away; the task moves on to test.
- Failed probes give rests of 1, 2, 5, 5 minutes.
- With codex-lb's port closed, wake spends no probe.
- `cd agent-office && python -m pytest -q` passes.
