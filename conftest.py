"""Repo-wide test setup: the suite always uses the numpy digits number reader (T-033)."""
import pytest


@pytest.fixture(autouse=True)
def _digits_number_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPORTSCUT_NUMBER_READER", "digits")
