# Rest reasons: say why the office sleeps, never call a failing CLI "out of quota"

Date: 2026-11-23  
Request: PO (Hoang) 2026-11-23: "Nothing to do while agents rest; sleeping 14 min" although quota was left.

## Root cause

- Two CLI failures in a row (`FAILURES_BEFORE_REST = 2`: not logged in, sandbox/network error, bad
  flag...) put the agent on the 15/30/60-min backoff, but the office logged it as
  `usage limit ('repeated failures')` and the agent said "Mình hết quota rồi".
- `limits.detect` searched the whole output, and strong phrases even on a successful run: an agent
  that reads code/docs quoting "usage limit reached" could be put to rest.
- The sleep line said "while agents rest" for any wait (also a task's Tech Lead / GitHub retry),
  without naming which agent or task, why, or which log to read.

## Design

- `detect`: exit 0 is never a limit; a failed run is searched only in the last 2000 characters of
  stdout and of stderr (`TAIL_CHARS`).
- `Agent.rest_detail` (the CLI's last error line, or the matched quota phrase) and `Agent.rest_log`.
  Rest messages and echo lines depend on the cause: quota / daily budget / CLI failing.
- `scheduler.rest_reason()`; waiting reasons name the cause, detail and log; task waits say
  `Tech Lead decision` or `GitHub network retry n/4`; env-blocked tasks say "fix GitHub".
- `cli.sleep_message(plan)`: "Nothing can run now; sleeping N min until HH:MM ... Waiting on:" plus
  one line per reason. The dashboard shows `rest_detail`.

## Files

- `agent-office/agent_office/{limits.py,models.py,pipeline.py,scheduler.py,cli.py,dashboard/static/app.js}`
- `agent-office/tests/{test_limits.py,test_rest_reason.py}`
- `docs/09-van-hanh.md`, `docs/superpowers/{INDEX.md,DECISIONS.md}`, this spec and its plan

## Acceptance criteria

- A successful run quoting a limit phrase is not a limit; a phrase early in a long failed transcript is not.
- Repeated CLI failures rest with cause `failure`, the stderr line and the log path, and are not
  reported as quota.
- The sleep message lists each waiting reason; a task retry is not called an agent rest.
