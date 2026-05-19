import os
import subprocess
from pathlib import Path

from .router import router


PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMMIT_ENV_VARS = ('COMMIT_SHA', 'GIT_COMMIT', 'SOURCE_COMMIT', 'RENDER_GIT_COMMIT')


def _commit_from_env() -> tuple[str, str] | None:
    for name in COMMIT_ENV_VARS:
        value = os.environ.get(name)
        if value:
            return value, name
    return None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding='utf-8').strip()
    except OSError:
        return None


def _git_metadata_dir() -> Path | None:
    git_path = PROJECT_ROOT / '.git'
    if git_path.is_dir():
        return git_path

    git_file = _read_text(git_path)
    if git_file is None or not git_file.startswith('gitdir:'):
        return None

    git_dir = Path(git_file.removeprefix('gitdir:').strip())
    if not git_dir.is_absolute():
        git_dir = PROJECT_ROOT / git_dir
    return git_dir


def _commit_from_packed_refs(git_dir: Path, ref: str) -> str | None:
    packed_refs = _read_text(git_dir / 'packed-refs')
    if packed_refs is None:
        return None

    for line in packed_refs.splitlines():
        if not line or line.startswith(('#', '^')):
            continue
        parts = line.split()
        if len(parts) == 2 and parts[1] == ref:
            return parts[0]
    return None


def _commit_from_git_metadata() -> str | None:
    git_dir = _git_metadata_dir()
    if git_dir is None:
        return None

    head = _read_text(git_dir / 'HEAD')
    if head is None:
        return None

    if not head.startswith('ref:'):
        return head

    ref = head.removeprefix('ref:').strip()
    return _read_text(git_dir / ref) or _commit_from_packed_refs(git_dir, ref)


def _commit_from_git_command() -> str | None:
    try:
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    commit_hash = result.stdout.strip()
    return commit_hash or None


def get_deployed_commit_hash() -> tuple[str, str]:
    env_commit = _commit_from_env()
    if env_commit is not None:
        return env_commit

    git_metadata_commit = _commit_from_git_metadata()
    if git_metadata_commit is not None:
        return git_metadata_commit, 'git_metadata'

    git_commit = _commit_from_git_command()
    if git_commit is not None:
        return git_commit, 'git_command'

    return 'unknown', 'unknown'


@router.get(
    path='/version',
    name='Service Version',
    description='Returns the commit hash this service is running from.',
)
async def version_handler() -> dict[str, str]:
    commit_hash, source = get_deployed_commit_hash()
    return {'commit_hash': commit_hash, 'source': source}
