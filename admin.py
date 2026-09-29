"""Alta manual de clientes (mientras no hay registro automático).

Uso (con DATABASE_URL apuntando a la base de producción):
  python admin.py add "Oficina Pérez" https://hooks.slack.com/services/XXX/YYY/ZZZ [--limit 20]
  python admin.py list
  python admin.py deactivate <id>
  python admin.py set-webhook <id> <url>
  python admin.py set-limit <id> <n>
  python admin.py new-key <id>        # rota la API key (la anterior deja de funcionar)
"""
import argparse
import sys

from sqlalchemy import func, select

import db

SLACK_PREFIX = "https://hooks.slack.com/services/"


def _check_webhook(url):
    if not url.startswith(SLACK_PREFIX):
        sys.exit(f"El webhook debe empezar con {SLACK_PREFIX}")


def main(argv=None):
    p = argparse.ArgumentParser(description="Clientes de NoteMeeting")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add"); a.add_argument("name"); a.add_argument("webhook"); a.add_argument("--limit", type=int, default=db.DEFAULT_MONTHLY_LIMIT)
    sub.add_parser("list")
    d = sub.add_parser("deactivate"); d.add_argument("id", type=int)
    w = sub.add_parser("set-webhook"); w.add_argument("id", type=int); w.add_argument("webhook")
    l = sub.add_parser("set-limit"); l.add_argument("id", type=int); l.add_argument("limit", type=int)
    k = sub.add_parser("new-key"); k.add_argument("id", type=int)
    args = p.parse_args(argv)

    if args.cmd == "add":
        _check_webhook(args.webhook)
        c, key = db.create_client(args.name, args.webhook, args.limit)
        print(f"Cliente #{c.id} creado: {c.name} (límite {c.monthly_limit}/mes)")
        print(f"API KEY (se muestra solo esta vez, envíasela al cliente): {key}")
        return

    with db.session() as s:
        if args.cmd == "list":
            for c in s.scalars(select(db.Client).order_by(db.Client.id)):
                used = db.meetings_this_month(c.id)
                open_tasks = s.scalar(select(func.count(db.Task.id)).where(db.Task.client_id == c.id, db.Task.status == "open"))
                print(f"#{c.id} {'ACTIVO' if c.active else 'inactivo'} {c.name} · {used}/{c.monthly_limit} reuniones este mes · {open_tasks} tareas abiertas")
            return
        c = s.get(db.Client, args.id)
        if c is None:
            sys.exit("No existe ese cliente")
        if args.cmd == "deactivate":
            c.active = False
        elif args.cmd == "set-webhook":
            _check_webhook(args.webhook); c.webhook_url = args.webhook
        elif args.cmd == "set-limit":
            c.monthly_limit = args.limit
        elif args.cmd == "new-key":
            key = db.new_api_key(); c.api_key_hash = db.hash_key(key)
            print(f"Nueva API KEY para #{c.id}: {key}")
        s.commit()
        print("OK")


if __name__ == "__main__":
    main()
