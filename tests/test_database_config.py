from pathlib import Path

import pytest

from app.config import ConfigurationError
from test_config import configured_settings


def test_database_path_default(monkeypatch):
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    assert configured_settings(monkeypatch).database_path == Path("data/expenses.db")


@pytest.mark.parametrize("path", ["", "   ", ":memory:"])
def test_invalid_database_path(monkeypatch, path):
    with pytest.raises(ConfigurationError):
        configured_settings(monkeypatch, DATABASE_PATH=path)
