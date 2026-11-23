# R-008: Retry GitHub PR/merge for T-035 after the gh fix

Date: 2026-11-23

Request: PO 2026-11-23 "đã fix lỗi github cli thử lại xem"

## Why no code changes

The existing `office retry-github` command (`pipeline.Office.retry_github`) covers this case.
T-035 was already approved and pushed, so the remaining work belonged to the office's GitHub
retry flow. Reimplementing T-035, rebasing it, or merging main into it is out of scope.

## Steps (run by the office / on the PO's machine)

1. Run `office doctor`. All GitHub checks must pass: `gh` is on PATH, the checkout has a
   github.com remote, `api.github.com:443` is reachable, `gh api user` succeeds, and the user
   has push permission on `AnhHoangQuach/sportscut-ai`.
2. Run `office retry-github`. Its output must contain either
   `T-035: PR / merge retried now` or `T-035 back to pr`, and must not contain
   `GitHub chưa ổn:`.
3. Run `office status` and confirm that T-035 has a non-empty `pr_url`.
4. Run `git fetch origin && git log origin/main --oneline -5` and confirm that the T-035
   merge appears. Then run `git ls-tree origin/main sportscut/models.py` and confirm that it
   finds the file.
5. Confirm that T-035's stage is `done` and that T-036 is no longer `todo`.

## Outcome (observed 2026-11-23)

T-035 merged as 30227a6 (PR #12). T-036 then ran and merged as f650dcd (PR #14).

## If the preflight still fails

T-035 stays `blocked` with "environment problem for the user". The office reports the `->`
fix hint to the PO; it is never handed to the Tech Lead, and nothing is waived. The office
re-checks the environment every 5 minutes by itself and resumes the retry when the preflight
passes.

## Related

- [GitHub PR environment design](../specs/2026-11-23-github-pr-environment-design.md)
- [Rest reasons design](../specs/2026-11-23-rest-reasons-design.md)
