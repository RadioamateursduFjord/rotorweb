# -*- coding: utf-8 -*-
"""
RotorWeb — sauvegarde et restauration des réglages.

Le fichier .rwbackup contient TOUT ce qui est propre à la station (config.json et state.json :
réglages, contrôleur, calibration, profils, horaires, préréglages, courriels, Home Assistant,
comptes…), compressé puis chiffré par mot de passe (AES-256, clé dérivée PBKDF2, 200 000 itérations).

Le chiffrement est fait par openssl : on peut ouvrir une sauvegarde à la main au besoin :
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in fichier.rwbackup | gunzip > sauvegarde.json

En terminal :
    python -m rotorweb.backup create  fichier.rwbackup --config /opt/rotorweb/config.json
    python -m rotorweb.backup restore fichier.rwbackup --config /opt/rotorweb/config.json
"""
import argparse
import getpass
import gzip
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

FORMAT = "rotorweb-backup"
FORMAT_VERSION = 1
ITER = "200000"


class BackupError(ValueError):
    pass


def _openssl(args, data, password):
    env = dict(os.environ, RW_BACKUP_PASS=password)
    r = subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", ITER, "-salt", "-pass", "env:RW_BACKUP_PASS"] + args,
                       input=data, capture_output=True, env=env)
    if r.returncode != 0:
        raise BackupError("Mot de passe incorrect ou fichier de sauvegarde invalide")
    return r.stdout


def make_payload(cfg, state, version):
    return {"format": FORMAT, "format_version": FORMAT_VERSION, "rotorweb_version": version,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"), "callsign": cfg.get("callsign", ""),
            "grid": cfg.get("grid", ""), "config": cfg, "state": state}


def encrypt(payload, password):
    if not password or len(password) < 6:
        raise BackupError("Mot de passe de sauvegarde trop court (6 caractères minimum)")
    raw = gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    return _openssl([], raw, password)


def decrypt(data, password):
    if not data.startswith(b"Salted__"):
        raise BackupError("Ce fichier n'est pas une sauvegarde RotorWeb")
    raw = _openssl(["-d"], data, password)
    try:
        payload = json.loads(gzip.decompress(raw).decode("utf-8"))
    except Exception:
        raise BackupError("Mot de passe incorrect ou fichier de sauvegarde invalide")
    if payload.get("format") != FORMAT or not isinstance(payload.get("config"), dict):
        raise BackupError("Ce fichier n'est pas une sauvegarde RotorWeb")
    return payload


def migrate(payload):
    """Adapte une sauvegarde d'une version plus ancienne."""
    st = payload.setdefault("state", {})
    if st.get("mode") == "auto":           # mode Automatique (WSJT-X) retiré en v1.7
        st["mode"] = "manual"
    st.pop("wsjtx_follow", None)
    payload["config"].setdefault("lang", "fr")
    return payload


def summary(payload):
    cfg, st = payload.get("config", {}), payload.get("state", {})
    rotor = cfg.get("rotor") or {}
    return {"rotorweb_version": payload.get("rotorweb_version"), "created": payload.get("created"),
            "callsign": cfg.get("callsign", ""), "grid": cfg.get("grid", ""), "driver": rotor.get("driver", ""),
            "elevation": bool(cfg.get("elevation")), "users": sorted((cfg.get("users") or {}).keys()),
            "schedules": len(st.get("schedules") or []), "presets": len(st.get("presets") or []),
            "profiles": len(cfg.get("rotor_profiles") or {}), "calibrated": bool(rotor.get("cal_az")),
            "email": bool((cfg.get("email") or {}).get("enabled")), "mqtt": bool((cfg.get("mqtt") or {}).get("enabled")),
            "web_port": cfg.get("web_port")}


def apply(payload, config_path):
    """Écrit la sauvegarde à la place des réglages actuels (copie des actuels gardée à côté)."""
    payload = migrate(payload)
    config_path = Path(config_path)
    state_path = config_path.with_name("state.json")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for p in (config_path, state_path):
        if p.exists():
            shutil.copy2(p, p.with_name(f"{p.name}.avant-restauration-{stamp}"))
    for p, data in ((config_path, payload["config"]), (state_path, payload["state"])):
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    try:
        os.chmod(config_path, 0o600)
    except OSError:
        pass
    return f"{config_path.name}.avant-restauration-{stamp}"


def file_name(cfg):
    call = "".join(c for c in (cfg.get("callsign") or "station") if c.isalnum()) or "station"
    return f"rotorweb-{call}-{time.strftime('%Y-%m-%d')}.rwbackup"


# --------------------------------------------------------------------------- terminal
def _version():
    try:
        from rotorweb.server import VERSION
        return VERSION
    except Exception:
        return "?"


def cli():
    ap = argparse.ArgumentParser(description="RotorWeb — sauvegarde / restauration")
    ap.add_argument("action", choices=("create", "restore", "show"))
    ap.add_argument("file")
    ap.add_argument("--config", default="/opt/rotorweb/config.json")
    ap.add_argument("--yes", action="store_true", help="ne pas demander de confirmation")
    a = ap.parse_args()
    en = False
    try:
        en = json.loads(Path(a.config).read_text()).get("lang") == "en"
    except Exception:
        pass
    T = (lambda fr, e: e if en else fr)
    try:
        if a.action == "create":
            cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
            sp = Path(a.config).with_name("state.json")
            st = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
            pw = getpass.getpass(T("Mot de passe de la sauvegarde : ", "Backup password: "))
            if pw != getpass.getpass(T("Encore une fois : ", "Once more: ")):
                print(T("Les mots de passe ne correspondent pas.", "Passwords do not match."))
                return 1
            Path(a.file).write_bytes(encrypt(make_payload(cfg, st, _version()), pw))
            print(T("✔ Sauvegarde créée :", "✔ Backup created:"), a.file)
            return 0
        data = Path(a.file).read_bytes()
        pw = getpass.getpass(T("Mot de passe de la sauvegarde : ", "Backup password: "))
        payload = decrypt(data, pw)
        s = summary(payload)
        print(T("Sauvegarde du", "Backup from"), s["created"], f"(RotorWeb v{s['rotorweb_version']})")
        print(f"  {s['callsign'] or '—'} · grid {s['grid'] or '—'} · {s['driver']}"
              f" · {T('comptes', 'accounts')} : {', '.join(s['users']) or '—'}"
              f" · {T('horaires', 'schedules')} : {s['schedules']} · {T('préréglages', 'presets')} : {s['presets']}")
        if a.action == "show":
            return 0
        if not a.yes:
            ok = input(T("Remplacer les réglages actuels par cette sauvegarde ? [o/N] ",
                         "Replace the current settings with this backup? [y/N] ")).strip().lower()
            if not ok.startswith(("o", "y")):
                print(T("Annulé.", "Cancelled."))
                return 1
        old = apply(payload, a.config)
        print(T("✔ Réglages restaurés. Anciens réglages gardés dans", "✔ Settings restored. Old settings kept in"), old)
        return 0
    except BackupError as e:
        print("✖", e)
        return 2


if __name__ == "__main__":
    sys.exit(cli())
