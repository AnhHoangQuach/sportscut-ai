# Worktree setup command

Date: 2026-11-23  
Request: configure every Agent Office worktree with its own Python virtual environment.

## Design

Set `[office].setup_cmd` to the SportsCut command documented in
`docs/02-quota-song-song-rao-chan.md` section 2.7. The command creates `.venv`, tries to install
the project with its development dependencies, and falls back to installing `pytest` while the
repository has no root `pyproject.toml`.

`ffmpeg` remains a machine-level Homebrew dependency and is not installed per worktree.

## Files

- `.agent-office/config.toml`
- `docs/superpowers/INDEX.md`
- `docs/superpowers/specs/2026-11-23-worktree-setup-command-design.md`
- `docs/superpowers/plans/2026-11-23-worktree-setup-command.md`

## Acceptance criteria

- Agent Office configuration parses as TOML.
- `[office].setup_cmd` exactly matches the documented SportsCut example.
- Homebrew reports an installed `ffmpeg` formula.
