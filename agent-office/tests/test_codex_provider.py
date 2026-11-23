"""Codex through a custom model provider such as codex-lb (a local proxy that needs its own key).

The office reads ~/.codex/config.toml (or $CODEX_HOME) to learn the provider's `env_key`, passes
that variable through to `codex exec`, can load it from the git-ignored `.agent-office/.env`, and
treats a missing variable as an environment problem for the user, not quota or a failing CLI."""
import json

from agent_office.agents import CodexAgent
from agent_office.agents.base import subscription_env
from agent_office.cli import main as office_main
from agent_office.codex_provider import missing_env_var, provider_info, read_env_file
from agent_office.config import AgentConfig
from agent_office.scheduler import next_step

LB_CONFIG = """\
model = "gpt-5.3-codex"
model_provider = "codex-lb"

[model_providers.codex-lb]
name = "openai"
base_url = "http://127.0.0.1:2455/backend-api/codex"
wire_api = "responses"
env_key = "CODEX_LB_API_KEY"
"""


def codex_home(tmp_path, monkeypatch, text=LB_CONFIG):
    home = tmp_path / "codex-home"
    home.mkdir(exist_ok=True)
    (home / "config.toml").write_text(text)
    monkeypatch.setenv("CODEX_HOME", str(home))
    return home


def events(repo):
    return [json.loads(x) for x in (repo / ".agent-office/events.jsonl").read_text().splitlines()]


# ---------------------------------------------------------------- reading the codex config
def test_provider_info_reads_env_key_and_base_url(tmp_path, monkeypatch):
    codex_home(tmp_path, monkeypatch)
    info = provider_info()
    assert info.name == "codex-lb" and info.env_key == "CODEX_LB_API_KEY"
    assert info.base_url == "http://127.0.0.1:2455/backend-api/codex"


def test_default_openai_login_has_no_env_key(tmp_path, monkeypatch):
    codex_home(tmp_path, monkeypatch, 'model = "gpt-5"\n')
    info = provider_info()
    assert info.name == "openai" and info.env_key == ""


def test_missing_or_broken_config_is_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "nowhere"))
    assert provider_info().env_key == ""
    codex_home(tmp_path, monkeypatch, "model_provider = [broken")
    assert provider_info().error


def test_env_file_parsing(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# codex-lb\nexport CODEX_LB_API_KEY='sk-clb-123'\nEMPTY=\nBAD LINE\nQ=\"a b\"\n")
    assert read_env_file(f) == {"CODEX_LB_API_KEY": "sk-clb-123", "EMPTY": "", "Q": "a b"}
    assert read_env_file(tmp_path / "missing") == {}


def test_missing_env_var_is_read_from_codex_output():
    out = '{"type":"turn.failed","error":{"message":"Missing environment variable: `CODEX_LB_API_KEY`."}}'
    assert missing_env_var(out) == "CODEX_LB_API_KEY"
    assert missing_env_var("all good") == ""


# ---------------------------------------------------------------- the child environment
def test_env_file_and_provider_key_reach_codex(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("CODEX_LB_API_KEY=from-file\n")
    monkeypatch.delenv("CODEX_LB_API_KEY", raising=False)
    env = subscription_env(tmp_path, env_file=env_file)
    assert env["CODEX_LB_API_KEY"] == "from-file"


def test_shell_key_of_the_codex_provider_is_kept_even_if_it_is_an_api_key_name(tmp_path, monkeypatch):
    codex_home(tmp_path, monkeypatch, LB_CONFIG.replace("CODEX_LB_API_KEY", "OPENAI_API_KEY"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local-proxy")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-strip-me")
    agent = CodexAgent(AgentConfig(cmd="codex"))
    env = agent.child_env(tmp_path)
    assert env["OPENAI_API_KEY"] == "sk-local-proxy" and "ANTHROPIC_API_KEY" not in env


def test_codex_agent_reports_the_missing_key_before_running(tmp_path, monkeypatch):
    codex_home(tmp_path, monkeypatch)
    monkeypatch.delenv("CODEX_LB_API_KEY", raising=False)
    agent = CodexAgent(AgentConfig(cmd="codex", env_file=str(tmp_path / ".env")))
    assert agent.env_problem() == "CODEX_LB_API_KEY"
    (tmp_path / ".env").write_text("CODEX_LB_API_KEY=x\n")
    assert agent.env_problem() == ""


# ---------------------------------------------------------------- the office
def test_missing_key_rests_codex_as_environment_problem_and_resumes_when_fixed(env, tmp_path, monkeypatch):
    codex_home(tmp_path, monkeypatch)
    monkeypatch.delenv("CODEX_LB_API_KEY", raising=False)
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    dev = office.store.agents["dev"]
    assert dev.status.value == "resting" and dev.rest_cause == "env"
    assert "CODEX_LB_API_KEY" in dev.rest_detail and dev.failures == 0
    assert not [c for c in env.calls() if c["agent"] == "codex"]  # no wasted call
    said = [e for e in events(env.repo) if e["event"] == "message" and e.get("topic") == "env"]
    assert len(said) == 1 and "CODEX_LB_API_KEY" in said[0]["text"] and ".agent-office/.env" in said[0]["text"]
    why = next(r for r in next_step(office.store, env.now).waiting_on if r.startswith("codex resting"))
    assert "environment" in why and "CODEX_LB_API_KEY" in why and not why.split("; ", 1)[1].startswith("quota")

    env.advance(minutes=6)  # still missing: rest again quietly, no second message
    env.run_all(office)
    assert dev.rest_cause == "env"
    assert len([e for e in events(env.repo) if e["event"] == "message" and e.get("topic") == "env"]) == 1

    (env.repo / ".agent-office" / ".env").write_text("CODEX_LB_API_KEY=sk-clb-test\n")
    env.advance(minutes=6)
    env.run_all(office)  # meanwhile Claude covered the Codex roles (failover), so the work went on
    assert dev.rest_cause == "" and office.store.tasks["T-001"].stage.value != "todo"
    said = [e["text"] for e in events(env.repo) if e["event"] == "message" and e.get("topic") == "awake"]
    assert said and "CODEX_LB_API_KEY" in said[-1]
    office.add_request("Export clips")
    env.run_all(office)
    dev_calls = [c for c in env.calls() if c["agent"] == "codex"]
    assert dev_calls and all(c["env"].get("CODEX_LB_API_KEY") == "sk-clb-test" for c in dev_calls)


def test_missing_env_error_from_codex_output_is_an_environment_problem(env, monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no-codex-config"))
    env.script(codex_dev=[{"missing_env": "CODEX_LB_API_KEY"}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    dev = office.store.agents["dev"]
    assert dev.rest_cause == "env" and "CODEX_LB_API_KEY" in dev.rest_detail
    assert office.store.agents["pm"].status.value != "resting"  # claude keeps working


def test_doctor_reports_codex_provider_and_missing_key(env, tmp_path, monkeypatch, capsys):
    codex_home(tmp_path, monkeypatch)
    monkeypatch.delenv("CODEX_LB_API_KEY", raising=False)
    rc = office_main(["--repo", str(env.repo), "doctor"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "codex-lb" in out and "http://127.0.0.1:2455/backend-api/codex" in out
    assert "FAIL" in out and "CODEX_LB_API_KEY" in out and ".agent-office/.env" in out
    (env.repo / ".agent-office" / ".env").write_text("CODEX_LB_API_KEY=sk-clb-test\n")
    office_main(["--repo", str(env.repo), "doctor"])
    out = capsys.readouterr().out
    line = next(ln for ln in out.splitlines() if "CODEX_LB_API_KEY" in ln)
    assert line.startswith("ok") and "sk-clb-test" not in out  # never print the secret


def test_init_keeps_the_env_file_out_of_git(env):
    assert ".env" in (env.repo / ".agent-office" / ".gitignore").read_text().split()
    (env.repo / ".agent-office" / ".env").write_text("CODEX_LB_API_KEY=x\n")
    import subprocess
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=env.repo,
                         capture_output=True, text=True).stdout
    assert ".agent-office/.env" not in out


# ---------------------------------------------------------------- follow-up: key still missing, run looked hung
def test_provider_in_a_codex_profile_is_found(tmp_path, monkeypatch):
    codex_home(tmp_path, monkeypatch, 'profile = "lb"\n\n[profiles.lb]\nmodel_provider = "codex-lb"\n\n'
               + LB_CONFIG.split("\n\n", 1)[1])
    info = provider_info()
    assert info.name == "codex-lb" and info.env_key == "CODEX_LB_API_KEY"


def test_call_log_says_where_the_env_came_from_without_the_value(env, tmp_path, monkeypatch):
    codex_home(tmp_path, monkeypatch)
    (env.repo / ".agent-office" / ".env").write_text("export CODEX_LB_API_KEY='sk-clb-secret'\n")
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    logs = sorted((env.repo / ".agent-office" / "logs").rglob("*-dev.log"))
    text = logs[0].read_text()
    assert "--- env:" in text and ".agent-office/.env" in text and "CODEX_LB_API_KEY" in text
    assert "codex-lb needs CODEX_LB_API_KEY: set" in text and "sk-clb-secret" not in text
    started = [ln for ln in env.lines if "[dev@codex]" in ln and "log " in ln]
    assert started and "-dev.log" in started[0]  # the log path is shown when the call starts


def test_codex_that_hangs_after_missing_env_is_stopped_at_once(env, tmp_path, monkeypatch):
    import time
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no-codex-config"))
    env.script(codex_dev=[{"missing_env": "CODEX_LB_API_KEY", "hang": 60}])
    office = env.office()
    office.add_request("Cut highlights")
    t0 = time.monotonic()
    env.run_all(office)
    assert time.monotonic() - t0 < 30
    assert office.store.agents["dev"].rest_cause == "env"
