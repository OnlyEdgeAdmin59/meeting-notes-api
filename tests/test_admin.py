import pytest

import admin
import db
from conftest import GOOD_WEBHOOK


def test_add_list_deactivate(capsys):
    admin.main(["add", "Oficina", GOOD_WEBHOOK, "--limit", "5"])
    out = capsys.readouterr().out
    key = out.split("cliente): ")[1].strip()
    assert db.find_client_by_key(key).monthly_limit == 5
    admin.main(["list"])
    assert "Oficina" in capsys.readouterr().out
    admin.main(["deactivate", "1"])
    assert db.find_client_by_key(key) is None


def test_rejects_bad_webhook():
    with pytest.raises(SystemExit):
        admin.main(["add", "X", "https://evil.example/hook"])


def test_new_key_rotates(capsys):
    admin.main(["add", "X", GOOD_WEBHOOK])
    old = capsys.readouterr().out.split("cliente): ")[1].strip()
    admin.main(["new-key", "1"])
    new = capsys.readouterr().out.split(": ")[1].split()[0]
    assert db.find_client_by_key(old) is None and db.find_client_by_key(new) is not None
