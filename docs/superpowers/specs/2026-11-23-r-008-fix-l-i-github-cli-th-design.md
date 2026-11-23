# R-008 design

## Product Owner request

đã fix lỗi github cli thử lại xem

## Design (goal, approaches, choice)

Goal (R-008): the PO has fixed the GitHub CLI on their machine and wants the office to try GitHub again. Today the only work waiting on GitHub is R-001's T-035 ('Scaffold SportsCut packaging, version CLI, and Segment model'). It was approved in review round 1 and its branch `office/T-035` is clean and pushed. It is sitting in stage `pr` with a Tech Lead `wait` (retry_at 2026-11-23T06:54Z), set because gh had no collaborator access and the network lookup failed. T-036 (ffmpeg media helpers) depends on it, so R-001 stalls until T-035 merges. Done means: `office retry-github` prints `T-035: PR / merge retried now` (or `T-035 back to pr`) instead of `GitHub chưa ổn: ...`; T-035 then gets a `pr_url`, auto-merges into `main` with green tests and reaches `done`; and T-036 leaves `todo` and starts. Approaches considered: (A) treat it as an operational retry. The orchestrator runs the existing GitHub preflight through `office retry-github` (or its automatic environment recheck). The preflight clears T-035's retry_at and the normal PR/merge flow continues. No product or orchestrator code changes. (B) Have an agent create the PR itself. This is rejected: the 2026-11-23 decision says agent and Tech Lead sandboxes have no network or GitHub credentials, and Codex never pushes or opens PRs. (C) Redo T-035 from the base branch. This is rejected: the branch is already approved and pushed, and the Tech Lead guidance says not to redo the implementation or merge main again. Chosen: A, the simplest option, because it uses the `office retry-github` mechanism that already exists and changes no described behaviour or spec. The single task below only records the retry plan and its verification. If the preflight still fails, the office keeps T-035 blocked as an environment problem for the user and shows the exact fix hint. Per the 2026-11-23 GitHub-environment decision, that case goes back to the PO's machine and never to an agent.

## Tasks

See the rows for R-008 in `INDEX.md`.
