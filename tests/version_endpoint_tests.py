import subprocess
from pathlib import Path

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
    assert data['source'] in {
        'COMMIT_SHA',
        'GIT_COMMIT',
        'SOURCE_COMMIT',
        'RENDER_GIT_COMMIT',
        'git_metadata',
        'git_command',
        'unknown',
    }


def test_get_deployed_commit_hash_prefers_env(monkeypatch) -> None:
    monkeypatch.setenv('COMMIT_SHA', 'abc123')

    assert version.get_deployed_commit_hash() == ('abc123', 'COMMIT_SHA')


def test_get_deployed_commit_hash_falls_back_to_git_metadata(monkeypatch) -> None:
    monkeypatch.delenv('COMMIT_SHA', raising=False)
    monkeypatch.delenv('GIT_COMMIT', raising=False)
    monkeypatch.delenv('SOURCE_COMMIT', raising=False)
    monkeypatch.delenv('RENDER_GIT_COMMIT', raising=False)
    monkeypatch.setattr(version, '_commit_from_git_metadata', lambda: 'def456')

    assert version.get_deployed_commit_hash() == ('def456', 'git_metadata')


def test_get_deployed_commit_hash_falls_back_to_git_command(monkeypatch) -> None:
    monkeypatch.delenv('COMMIT_SHA', raising=False)
    monkeypatch.delenv('GIT_COMMIT', raising=False)
    monkeypatch.delenv('SOURCE_COMMIT', raising=False)
    monkeypatch.delenv('RENDER_GIT_COMMIT', raising=False)
    monkeypatch.setattr(version, '_commit_from_git_metadata', lambda: None)
    monkeypatch.setattr(version, '_commit_from_git_command', lambda: 'fedcba')

    assert version.get_deployed_commit_hash() == ('fedcba', 'git_command')


def test_get_deployed_commit_hash_returns_unknown_without_source(monkeypatch) -> None:
    monkeypatch.delenv('COMMIT_SHA', raising=False)
    monkeypatch.delenv('GIT_COMMIT', raising=False)
    monkeypatch.delenv('SOURCE_COMMIT', raising=False)
    monkeypatch.delenv('RENDER_GIT_COMMIT', raising=False)
    monkeypatch.setattr(version, '_commit_from_git_metadata', lambda: None)
    monkeypatch.setattr(version, '_commit_from_git_command', lambda: None)

    assert version.get_deployed_commit_hash() == ('unknown', 'unknown')


def test_commit_from_git_metadata_reads_branch_ref(tmp_path: Path, monkeypatch) -> None:
    git_dir = tmp_path / '.git'
    ref_path = git_dir / 'refs' / 'heads' / 'main'
    ref_path.parent.mkdir(parents=True)
    (git_dir / 'HEAD').write_text('ref: refs/heads/main\n', encoding='utf-8')
    ref_path.write_text('1234567890abcdef\n', encoding='utf-8')
    monkeypatch.setattr(version, 'PROJECT_ROOT', tmp_path)

    assert version._commit_from_git_metadata() == '1234567890abcdef'  # pylint: disable=protected-access


def test_commit_from_git_metadata_reads_detached_head(tmp_path: Path, monkeypatch) -> None:
    git_dir = tmp_path / '.git'
    git_dir.mkdir()
    (git_dir / 'HEAD').write_text('abcdef1234567890\n', encoding='utf-8')
    monkeypatch.setattr(version, 'PROJECT_ROOT', tmp_path)

    assert version._commit_from_git_metadata() == 'abcdef1234567890'  # pylint: disable=protected-access


def test_commit_from_git_metadata_reads_packed_ref(tmp_path: Path, monkeypatch) -> None:
    git_dir = tmp_path / '.git'
    git_dir.mkdir()
    (git_dir / 'HEAD').write_text('ref: refs/heads/main\n', encoding='utf-8')
    (git_dir / 'packed-refs').write_text(
        '# pack-refs with: peeled fully-peeled sorted\n'
        'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa refs/heads/other\n'
        'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb refs/heads/main\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(version, 'PROJECT_ROOT', tmp_path)

    assert version._commit_from_git_metadata() == 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'  # pylint: disable=protected-access


def test_commit_from_git_command_uses_project_root(monkeypatch) -> None:
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args[0], 0, stdout='fedcba\n', stderr='')

    monkeypatch.setattr(version.subprocess, 'run', fake_run)

    assert version._commit_from_git_command() == 'fedcba'  # pylint: disable=protected-access
    assert calls[0][1]['cwd'] == version.PROJECT_ROOT
