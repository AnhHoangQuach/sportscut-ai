# Rest reasons plan

1. Failing tests: `tests/test_limits.py` (exit 0, tail only), `tests/test_rest_reason.py`.
2. `limits.detect` exit-0 / tail rule.
3. `Agent.rest_detail`, `rest_log`; cause-specific messages in `pipeline._rest`.
4. `scheduler.rest_reason`, task wait reasons; `cli.sleep_message`; dashboard hint.
5. Docs 09, INDEX, DECISIONS.

Verify: `cd agent-office && python -m pytest -q`
