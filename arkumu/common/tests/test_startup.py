from arkumu.common.startup import should_skip_startup_warmup


def test_should_skip_startup_warmup_for_compilemessages(monkeypatch):
    monkeypatch.delenv("ARKUMU_SKIP_STARTUP_WARMUP", raising=False)

    assert should_skip_startup_warmup(["manage.py", "compilemessages"]) is True


def test_should_not_skip_startup_warmup_for_runserver(monkeypatch):
    monkeypatch.delenv("ARKUMU_SKIP_STARTUP_WARMUP", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    assert should_skip_startup_warmup(["manage.py", "runserver"]) is False


def test_should_skip_startup_warmup_when_env_override_is_enabled(monkeypatch):
    monkeypatch.setenv("ARKUMU_SKIP_STARTUP_WARMUP", "true")

    assert should_skip_startup_warmup(["manage.py", "runserver"]) is True


def test_should_skip_startup_warmup_under_pytest(monkeypatch):
    monkeypatch.delenv("ARKUMU_SKIP_STARTUP_WARMUP", raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "arkumu/common/tests/test_startup.py::test")

    assert should_skip_startup_warmup(["pytest"]) is True
