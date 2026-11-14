# -*- coding: utf-8 -*-
"""
RotorWeb — détection du contrôleur de rotor.

Utilisé par l'assistant « Changer de contrôleur » de la page web et par detect.sh :

    sudo /opt/rotorweb/detect.sh          (ou : python -m rotorweb.detect --config config.json)

La détection n'envoie QUE des demandes de position (lecture), jamais de mouvement.
"""
import argparse
import glob
import json
import os
import shutil
import sys
import time
from pathlib import Path

from rotorweb.drivers import DRIVER_MAP, DRIVERS, make_driver

# Essais dans l'ordre : (pilote, vitesse). Les plus courants d'abord.
PROBES = [
    ("gs232b", 9600), ("easycomm", 9600), ("arduino", 115200), ("dcu1", 4800), ("rot2prog", 600),
    ("rot2prog", 1200), ("gs232b", 4800), ("gs232b", 19200), ("gs232b", 38400), ("gs232b", 57600),
    ("gs232b", 115200), ("gs232b", 1200), ("easycomm", 19200), ("easycomm", 115200), ("rot2prog", 460800),
]
QUICK = 6   # nombre d'essais en mode rapide


class _Quiet:
    """Contrôleur minimal pour faire tourner un pilote hors du serveur."""
    def __init__(self, rotor, elevation=False):
        self.cfg = {"rotor": rotor, "elevation": elevation, "serial_port": rotor.get("serial_port")}

    def tlog(self, *a, **k):
        pass


def list_ports():
    """Ports série USB (/dev/serial/by-id de préférence : nom stable)."""
    out, seen = [], set()
    for p in sorted(glob.glob("/dev/serial/by-id/*")):
        real = os.path.realpath(p)
        seen.add(real)
        out.append({"path": p, "dev": real, "name": _nice(Path(p).name)})
    for p in sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")):
        if p not in seen:
            out.append({"path": p, "dev": p, "name": Path(p).name})
    if os.path.exists("/dev/rotor"):
        real = os.path.realpath("/dev/rotor")
        for o in out:
            if o["dev"] == real:
                o["rotor_link"] = True
    return out


def _nice(n):
    n = n.replace("usb-", "").replace("_", " ")
    for k, v in (("1a86", "CH340"), ("FTDI", "FTDI"), ("Arduino", "Arduino"), ("Prolific", "Prolific"),
                 ("Silicon Labs", "CP210x")):
        if k.lower() in n.lower() and v not in n:
            n = f"{v} · {n}"
    return n[:80]


def i2c_ads1115():
    """Un ADS1115 répond-il sur le bus I2C (montage GPIO) ?"""
    if not os.path.exists("/dev/i2c-1"):
        return None
    try:
        from smbus2 import SMBus
        with SMBus(1) as b:
            for addr in (0x48, 0x49, 0x4A, 0x4B):
                try:
                    b.read_i2c_block_data(addr, 0x01, 2)
                    return addr
                except OSError:
                    continue
    except Exception:
        return None
    return None


def probe_one(port, key, baud, simulate=False, sim_device="gs232b", base=None):
    """Essaie un pilote à une vitesse. Retourne (az, el, détail) ou None."""
    rotor = dict(base or {})
    rotor.update(driver=key, serial_port=port, baud=baud)
    q = _Quiet(rotor)
    if simulate and key != sim_device:
        time.sleep(0.15)
        return None
    drv = make_driver(q, simulate)
    try:
        drv.open()
        if key == "arduino":
            if simulate:
                return (None, None, "RWDIY (simulation)")
            drv.port.write(b"V\n")
            time.sleep(0.3)
            v = drv.port.read(64).decode(errors="replace")
            return (None, None, v.strip()) if "RWDIY" in v else None
        for _ in range(3):
            pos = drv.poll()
            if pos and pos[0] is not None and -400 <= pos[0] <= 900:
                detail = ""
                if key == "gs232b" and not simulate:
                    # GS-232A répond « +0123 », GS-232B « AZ=123 »
                    drv.port.write(b"C\r")
                    time.sleep(0.25)
                    raw = drv.port.read(64).decode(errors="replace")
                    if "AZ=" not in raw.upper() and "+" in raw:
                        detail = "gs232a"
                return (pos[0], pos[1], detail)
            time.sleep(0.2)
        return None
    except Exception:
        return None
    finally:
        try:
            drv.close()
        except Exception:
            pass


def probe_port(port, full=False, simulate=False, sim_device="gs232b", progress=None, base=None):
    """Détecte le contrôleur branché sur un port. Retourne une liste de résultats (le premier est le bon)."""
    tries = PROBES if full else PROBES[:QUICK]
    found = []
    for i, (key, baud) in enumerate(tries):
        if progress:
            progress(i + 1, len(tries), key, baud)
        r = probe_one(port, key, baud, simulate, sim_device, base)
        if r:
            az, el, detail = r
            k = "gs232a" if detail == "gs232a" else key
            found.append({"driver": k, "baud": baud, "az": az, "el": el, "detail": detail,
                          "label": DRIVER_MAP[k]["label"]})
            break
    return found


def backup_config(path):
    """Copie datée de config.json (on garde les 8 dernières)."""
    path = Path(path)
    if not path.exists():
        return None
    dst = path.with_name(f"config.json.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(path, dst)
    olds = sorted(path.parent.glob("config.json.bak-*"))
    for o in olds[:-8]:
        try:
            o.unlink()
        except OSError:
            pass
    return dst


# ----------------------------------------------------------------------------- terminal
T = {
    "fr": {
        "title": "Changer / redétecter le contrôleur du rotor",
        "ports": "Ports USB série détectés :", "none": "Aucun port USB série détecté.",
        "which": "Numéro du port du contrôleur", "probing": "Détection sur",
        "found": "Trouvé", "notfound": "Aucun contrôleur reconnu à ces vitesses.",
        "full": "Essayer toutes les vitesses (plus long) ? [o/N] ", "manual": "Choisis le modèle à la main :",
        "model": "Numéro du modèle", "baud": "Vitesse (Entrée = défaut", "keep": "Garder la course et la calibration actuelles ? [O/n] ",
        "saved": "Configuration enregistrée. Copie de l'ancienne :", "restart": "Redémarrage de RotorWeb…",
        "gpio": "Un ADS1115 répond sur le bus I2C (montage GPIO) à l'adresse", "usegpio": "Utiliser le montage GPIO ? [o/N] ",
        "cancel": "Annulé.", "yes": "o", "pos": "position lue",
        "manualq": "Aucun port trouvé. Choisir le modèle à la main ? [O/n] ",
    },
    "en": {
        "title": "Change / re-detect the rotor controller",
        "ports": "USB serial ports found:", "none": "No USB serial port found.",
        "which": "Controller port number", "probing": "Probing",
        "found": "Found", "notfound": "No controller recognized at these speeds.",
        "full": "Try every speed (slower)? [y/N] ", "manual": "Pick the model manually:",
        "model": "Model number", "baud": "Speed (Enter = default", "keep": "Keep the current travel and calibration? [Y/n] ",
        "saved": "Configuration saved. Copy of the old one:", "restart": "Restarting RotorWeb…",
        "gpio": "An ADS1115 answers on the I2C bus (GPIO build) at address", "usegpio": "Use the GPIO build? [y/N] ",
        "cancel": "Cancelled.", "yes": "y", "pos": "position read",
        "manualq": "No port found. Pick the model manually? [Y/n] ",
    },
}


def _ask(msg, default=""):
    try:
        v = input(msg).strip()
    except EOFError:
        return default
    return v or default


def cli():
    ap = argparse.ArgumentParser(description="RotorWeb — détection du contrôleur")
    ap.add_argument("--config", default="/opt/rotorweb/config.json")
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("--lang", choices=("fr", "en"))
    args = ap.parse_args()
    cfgp = Path(args.config)
    cfg = json.loads(cfgp.read_text(encoding="utf-8")) if cfgp.exists() else {}
    L = T[args.lang or cfg.get("lang", "fr") if (args.lang or cfg.get("lang")) in ("fr", "en") else "fr"]
    rotor = dict(cfg.get("rotor") or {})
    print(f"\n== {L['title']} ==\n")
    ports = list_ports() if not args.simulate else [{"path": "/dev/sim0", "dev": "/dev/sim0", "name": "Simulation"}]
    choice = None
    if ports:
        print(L["ports"])
        for i, p in enumerate(ports, 1):
            print(f"  {i}) {p['name']}  →  {p['dev']}{'  (/dev/rotor)' if p.get('rotor_link') else ''}")
        n = _ask(f"{L['which']} [1] : ", "1")
        try:
            port = ports[int(n) - 1]
        except (ValueError, IndexError):
            print(L["cancel"])
            return 1
        def prog(i, n, key, baud):
            print(f"  {L['probing']} {port['name']} : {DRIVER_MAP[key]['label']} @ {baud}…", flush=True)
        res = probe_port(port["path"], simulate=args.simulate, progress=prog, base=rotor)
        if not res and _ask(L["full"]).lower().startswith(L["yes"]):
            res = probe_port(port["path"], full=True, simulate=args.simulate, progress=prog, base=rotor)
        if res:
            r = res[0]
            pos = f" ({L['pos']} : {r['az']}°)" if r["az"] is not None else ""
            print(f"\n✔ {L['found']} : {r['label']} @ {r['baud']}{pos}")
            choice = {"driver": r["driver"], "serial_port": port["path"], "baud": r["baud"]}
        else:
            print(f"\n⚠ {L['notfound']}")
    else:
        print(L["none"])
        addr = i2c_ads1115()
        if addr is not None:
            print(f"{L['gpio']} 0x{addr:02X}")
            if _ask(L["usegpio"]).lower().startswith(L["yes"]):
                choice = {"driver": "gpio"}
                rotor.setdefault("gpio", {})["ads_address"] = addr
    if not choice:
        if not ports and _ask(L["manualq"], L["yes"]).lower()[:1] not in (L["yes"], ""):
            print(L["cancel"])
            return 1
        print(L["manual"])
        for i, d in enumerate(DRIVERS, 1):
            print(f"  {i}) {d['label']}")
        try:
            d = DRIVERS[int(_ask(f"{L['model']} : ")) - 1]
        except (ValueError, IndexError):
            print(L["cancel"])
            return 1
        b = _ask(f"{L['baud']} {d['baud'] or '-'}) : ", "")
        choice = {"driver": d["key"], "baud": int(b) if b.isdigit() else 0}
        if d["kind"] == "serial" and ports:
            choice["serial_port"] = port["path"]
    keep = not _ask(L["keep"]).lower().startswith("n")
    bak = backup_config(cfgp)
    rotor.update(choice)
    if not keep:
        rotor["cal_az"], rotor["cal_el"], rotor["offset"] = [], [], 0
    profiles = cfg.setdefault("rotor_profiles", {})
    if cfg.get("rotor"):
        profiles["↩ Précédent"] = {**cfg["rotor"], "elevation": cfg.get("elevation", False)}  # nom fixe (traduit à l'affichage)
    cfg["rotor"] = rotor
    cfg["rotor_profile"] = ""
    tmp = cfgp.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(cfgp)
    print(f"\n✔ {L['saved']} {bak}")
    return 0


if __name__ == "__main__":
    sys.exit(cli())
