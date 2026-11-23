# Worktree setup command plan

1. Confirm `.agent-office/config.toml` is not covered by `protected_paths`.
2. Confirm `ffmpeg` is installed by Homebrew; install it only if absent.
3. Add the section 2.7 SportsCut `setup_cmd` under `[office]`.
4. Parse the configuration and verify the exact command value.
5. Record the request in the feature index.

Verify:

```sh
python3 -c 'import tomllib; print(tomllib.load(open(".agent-office/config.toml", "rb"))["office"]["setup_cmd"])'
brew list --versions ffmpeg
```
