import subprocess

from fastapi.testclient import TestClient

from infrastructure.endpoints import version
from main import app


def test_version_endpoint_returns_commit_hash() -> None:
    with TestClient(app) as client:
        response = client.get('/version')

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data['commit_hash'], str)
    assert data['commit_hash']
    assert data['source'] in {'COMMIT_SHA', 'GIT_COMMIT', 'SOURCE_COMMIT', 'RENDER_GIT_COMMIT', 'git', 'unknown'}


def test_get_deployed_commit_hash_prefers_env(monkeypatch) -> None:
    monkeypatch.setenv('COMMIT_SHA', 'abc123')

    assert version.get_deployed_commit_hash() == ('abc123', 'COMMIT_SHA')


def test_get_deployed_commit_hash_falls_back_to_git(monkeypatch) -> None:
    monkeypatch.delenv('COMMIT_SHA', raising=False)
    monkeypatch.delenv('GIT_COMMIT', raising=False)
    monkeypatch.delenv('SOURCE_COMMIT', raising=False)
    monkeypatch.delenv('RENDER_GIT_COMMIT', raising=False)
    monkeypatch.setattr(version, '_commit_from_git', lambda: 'def456')

    assert version.get_deployed_commit_hash() == ('def456', 'git')


def test_get_deployed_commit_hash_returns_unknown_without_source(monkeypatch) -> None:
    monkeypatch.delenv('COMMIT_SHA', raising=False)
    monkeypatch.delenv('GIT_COMMIT', raising=False)
    monkeypatch.delenv('SOURCE_COMMIT', raising=False)
    monkeypatch.delenv('RENDER_GIT_COMMIT', raising=False)
    monkeypatch.setattr(version, '_commit_from_git', lambda: None)

    assert version.get_deployed_commit_hash() == ('unknown', 'unknown')


def test_commit_from_git_uses_project_root(monkeypatch) -> None:
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args[0], 0, stdout='fedcba\n', stderr='')

    monkeypatch.setattr(version.subprocess, 'run', fake_run)

    assert version._commit_from_git() == 'fedcba'  # pylint: disable=protected-access
    assert calls[0][1]['cwd'] == version.PROJECT_ROOT
