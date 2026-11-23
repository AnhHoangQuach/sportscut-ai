# GitHub PR / merge environment plan

1. Tests first (`tests/test_github.py`, scripted fake `gh` on PATH, injectable preflight): classify,
   slug, permission block + resume, network backoff, other -> Tech Lead, `-R` pinning, preflight
   hints, doctor output.
2. `agent_office/github.py` (classify, run_gh, repo_slug, preflight, report).
3. Route `worktree.py` gh calls through `run_gh` with `-R`.
4. `pipeline._github_failed`, `recheck_environment`, triage skips `ENV_MARK`; `Task.net_retries`.
5. `office doctor` GitHub section; Tech Lead prompt note.
6. Docs: `docs/09-van-hanh.md` 9.1; INDEX and DECISIONS.

Verify:

```sh
cd agent-office && python -m pytest -q
```
