import re
import subprocess
from pathlib import Path

import pytest

SECRET_LIKE = [".env", "prod.env", ".env.local", "github_token.txt", "client_secrets.json", "server.pem", ".venv/x"]
TOKEN_RE = re.compile(r"ghp_[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_-]{8,}|hooks\.slack\.com/services/T(?!000/)[A-Z0-9]+/")


def _ignored(path):
    return subprocess.run(["git", "check-ignore", "-q", path]).returncode == 0


@pytest.mark.parametrize("path", SECRET_LIKE)
def test_secret_files_are_ignored(path):
    assert _ignored(path)


def test_env_example_still_tracked():
    assert not _ignored(".env.example")


def test_no_real_secrets_in_tracked_or_new_files():
    files = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                           capture_output=True, text=True, check=True).stdout.split()
    hits = [f for f in files if Path(f).is_file() and TOKEN_RE.search(Path(f).read_text(encoding="utf-8", errors="ignore"))]
    assert hits == []
