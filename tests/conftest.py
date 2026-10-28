import pytest


@pytest.fixture
def standalone_mind(monkeypatch):
    """Legacy anonymous HTTP scenarios exercise the explicit single-user contract."""
    monkeypatch.setenv('LOGICAOS_MULTIUSER', '0')
