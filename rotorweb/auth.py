#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RotorWeb — comptes utilisateurs

Les mots de passe sont stockés hachés (PBKDF2-SHA256), jamais en clair.

Gestion en ligne de commande :
  python -m rotorweb.auth list            --config /opt/rotorweb/config.json
  python -m rotorweb.auth add  NOM        --config ...
  python -m rotorweb.auth passwd NOM      --config ...
  python -m rotorweb.auth del  NOM        --config ...
"""
import argparse
import getpass
import hashlib
import hmac
import json
import re
import secrets
import sys
import time
from pathlib import Path

ITERATIONS = 120_000
USER_RE = re.compile(r"^[a-z0-9_.-]{2,32}$")
SESSION_DAYS = 30


def hash_password(pw):
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f"pbkdf2_sha256${ITERATIONS}${salt}${h}"


def verify_password(pw, stored):
    try:
        _, it, salt, h = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it)).hex()
        return hmac.compare_digest(calc, h)
    except Exception:
        return False


def _sig(secret, user, exp, stored):
    # Le bout du hash inclus dans la signature : changer le mot de passe déconnecte les sessions
    msg = f"{user}|{exp}|{stored[-16:]}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def make_token(secret, user, stored, days=SESSION_DAYS):
    exp = int(time.time()) + days * 86400
    return f"{user}|{exp}|{_sig(secret, user, exp, stored)}"


def check_token(secret, users, token):
    try:
        user, exp, sig = token.split("|")
        if int(exp) < time.time() or user not in users:
            return None
        if hmac.compare_digest(sig, _sig(secret, user, int(exp), users[user])):
            return user
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- CLI
def _load(path):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save(path, cfg):
    p = Path(path)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def _ask_password():
    while True:
        a = getpass.getpass("  Mot de passe (6 caractères minimum) : ")
        if len(a) < 6:
            print("  Trop court.")
            continue
        if getpass.getpass("  Confirme le mot de passe : ") != a:
            print("  Les deux mots de passe ne correspondent pas.")
            continue
        return a


def main():
    ap = argparse.ArgumentParser(description="Gestion des comptes RotorWeb")
    ap.add_argument("action", choices=["list", "add", "passwd", "del"])
    ap.add_argument("name", nargs="?")
    ap.add_argument("--config", default=str(Path(__file__).resolve().parent.parent / "config.json"))
    a = ap.parse_args()
    cfg = _load(a.config)
    users = cfg.setdefault("users", {})

    if a.action == "list":
        print("Comptes :", ", ".join(sorted(users)) if users else "(aucun)")
        return 0
    name = (a.name or "").strip().lower()
    if not USER_RE.match(name):
        print("Nom invalide : 2 à 32 caractères parmi a-z 0-9 _ . -")
        return 1
    if a.action == "add":
        if name in users:
            print(f"« {name} » existe déjà (utilise passwd pour changer son mot de passe).")
            return 1
        users[name] = hash_password(_ask_password())
        _save(a.config, cfg)
        print(f"✔ Compte « {name} » créé")
    elif a.action == "passwd":
        if name not in users:
            print(f"« {name} » n'existe pas.")
            return 1
        users[name] = hash_password(_ask_password())
        _save(a.config, cfg)
        print(f"✔ Mot de passe de « {name} » changé (ses sessions ouvertes sont déconnectées)")
    elif a.action == "del":
        if name not in users:
            print(f"« {name} » n'existe pas.")
            return 1
        if len(users) == 1:
            print("Impossible de supprimer le dernier compte.")
            return 1
        del users[name]
        _save(a.config, cfg)
        print(f"✔ Compte « {name} » supprimé")
    print("Changement pris en compte immédiatement (pas besoin de redémarrer).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
