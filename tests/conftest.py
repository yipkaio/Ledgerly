import pytest


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch, tmp_path_factory):
    path = tmp_path_factory.mktemp("database") / "expenses.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
