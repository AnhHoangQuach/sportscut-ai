from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from agent_office.limits import RESET_MARGIN, detect, parse_reset, rest_until

NOW = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)


def test_claude_epoch_message():
    hit = detect("claude", "Claude AI usage limit reached|1795400000", "", 1, NOW)
    assert hit and hit.reset_at == datetime.fromtimestamp(1795400000, timezone.utc) + RESET_MARGIN


def _has_tz(name):
    try:
        ZoneInfo(name)
        return True
    except ZoneInfoNotFoundError:
        return False


@pytest.mark.skipif(not _has_tz("Asia/Saigon"), reason="no tz database on this machine")
def test_claude_resets_clock_with_timezone():
    hit = detect("claude", "", "5-hour limit reached ∙ resets 8pm (Asia/Saigon)", 1, NOW)
    assert hit is not None
    # 20:00 in Saigon (UTC+7) is 13:00 UTC, later the same day
    assert hit.reset_at == datetime(2026, 11, 22, 13, 0, tzinfo=timezone.utc) + RESET_MARGIN


def test_clock_in_the_past_rolls_to_tomorrow():
    r = parse_reset("You've hit your limit · resets 3am (UTC)", NOW)
    assert r == datetime(2026, 11, 23, 3, 0, tzinfo=timezone.utc) + RESET_MARGIN


def test_codex_relative_message():
    hit = detect("codex", "", "You've hit your usage limit. Upgrade to Pro or try again in 2 days 3 hours 5 minutes.",
                 1, NOW)
    assert hit and hit.reset_at == NOW + timedelta(days=2, hours=3, minutes=5) + RESET_MARGIN


def test_codex_json_event():
    out = '{"type":"error","error":{"type":"usage_limit_reached","resets_in_seconds":600}}'
    hit = detect("codex", out, "", 1, NOW)
    assert hit and hit.reset_at == NOW + timedelta(seconds=600) + RESET_MARGIN


def test_weak_signal_needs_nonzero_exit():
    code = "def handle_429(): raise RateLimited  # rate limited by upstream\nstatus 429"
    assert detect("codex", code, "", 0, NOW) is None
    assert detect("codex", "", "error: status 429 Too Many Requests", 1, NOW) is not None


def test_normal_output_is_not_a_limit():
    assert detect("claude", '{"result": "Implemented the limiter"}', "", 0, NOW) is None


def test_backoff_ladder_without_reset_time():
    ladder = [15, 30, 60]
    assert rest_until(None, 0, ladder, NOW) == (NOW + timedelta(minutes=15), False)
    assert rest_until(None, 1, ladder, NOW) == (NOW + timedelta(minutes=30), False)
    assert rest_until(None, 5, ladder, NOW) == (NOW + timedelta(minutes=60), False)
    future = NOW + timedelta(hours=2)
    assert rest_until(future, 3, ladder, NOW) == (future, True)


def test_a_successful_run_is_never_a_limit_even_if_it_mentions_one():
    # e.g. Codex read limits.py or a test fixture and its transcript quotes the phrases
    transcript = "exec cat tests/test_limits.py\nYou've hit your usage limit. Try again in 2 hours.\n"
    assert detect("codex", "Done: added the clip exporter", transcript, 0, NOW) is None
    assert detect("claude", '{"result": "Claude AI usage limit reached|1795400000 handled"}', "", 0, NOW) is None


def test_only_the_end_of_a_failed_run_is_searched():
    # The CLI prints its limit error last; an old quote early in a long transcript is not one.
    early = "read docs: 'usage limit reached' handling\n" + ("x" * 5000) + "\nerror: tests failed\n"
    assert detect("codex", "", early, 1, NOW) is None
    assert detect("codex", "", ("x" * 5000) + "\nYou've hit your usage limit.\n", 1, NOW) is not None
