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


def _commit_from_git() -> str | None:
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

    git_commit = _commit_from_git()
    if git_commit is not None:
        return git_commit, 'git'

    return 'unknown', 'unknown'


@router.get(
    path='/version',
    name='Service Version',
    description='Returns the commit hash this service is running from.',
)
async def version_handler() -> dict[str, str]:
    commit_hash, source = get_deployed_commit_hash()
    return {'commit_hash': commit_hash, 'source': source}
