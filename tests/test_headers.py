import re
from pathlib import Path

import pytest
from conftest import GOOD_WEBHOOK

REQUIRED = ["Strict-Transport-Security", "Content-Security-Policy", "X-Frame-Options", "X-Content-Type-Options"]


@pytest.mark.parametrize("method,path,kw", [
    ("get", "/", {}),
    ("get", "/health", {}),
    ("get", "/static/index.html", {}),
    ("get", "/static/app.js", {}),
    ("post", "/api/test", {"json": {"webhook_url": GOOD_WEBHOOK}}),
    ("post", "/api/test", {"json": {"webhook_url": "https://evil"}}),        # 400
    ("post", "/api/test", {"json": {}, "headers": {"X-API-Key": "bad"}}),   # 401
])
def test_security_headers_on_every_response(client, method, path, kw):
    r = getattr(client, method)(path, **kw)
    for h in REQUIRED:
        assert h in r.headers, f"{h} missing on {path} ({r.status_code})"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "max-age=" in r.headers["Strict-Transport-Security"]


def test_csp_blocks_inline_scripts(client):
    csp = client.get("/").headers["Content-Security-Policy"]
    script_src = re.search(r"script-src ([^;]+)", csp).group(1)
    assert "'unsafe-inline'" not in script_src and "'unsafe-eval'" not in script_src
    assert "frame-ancestors 'none'" in csp


@pytest.mark.parametrize("page", ["public/index.html", "public/test.html"])
def test_pages_compatible_with_csp(page):
    html = Path(page).read_text(encoding="utf-8")
    assert not re.search(r"<script>(?!</script>)", html), "inline <script> would be blocked by CSP"
    assert not re.search(r"\son[a-z]+\s*=", html), "inline event handler would be blocked by CSP"
    for src in re.findall(r'<script src="([^"]+)"', html):
        assert src.startswith("/static/") or src == "https://cdn.tailwindcss.com"
