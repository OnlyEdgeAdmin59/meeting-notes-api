from importlib.metadata import version

import pytest

# Minimos sin CVEs conocidos segun pip-audit (2026-09-28). Si bajan, este test falla.
MINIMUMS = {
    "fastapi": "0.109.1",
    "starlette": "1.3.1",
    "python-multipart": "0.0.18",
    "requests": "2.33.0",
    "anyio": "4.14.2",
    "python-dotenv": "1.2.2",
}


def _v(s):
    return tuple(int(p) for p in s.split(".")[:3])


@pytest.mark.parametrize("pkg,minimum", MINIMUMS.items())
def test_installed_version_not_vulnerable(pkg, minimum):
    assert _v(version(pkg)) >= _v(minimum), f"{pkg} {version(pkg)} < {minimum}"
