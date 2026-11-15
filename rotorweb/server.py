#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RotorWeb — Contrôle de rotor par page web (Raspberry Pi + contrôleur de rotor)

Le serveur est le SEUL à ouvrir le port série du K3NG. Il fait l'arbitre entre :
  - la page web (WebSocket)
  - le port TCP GS-232 (pour un port COM virtuel sur le PC)
  - le port rotctld (protocole réseau Hamlib, ex. Gpredict)
  - WSJT-X (messages UDP : dernier DX affiché, pointage sur demande)
"""
import argparse
import asyncio
import hashlib
import hmac
import json
import logging
import math
import os
import queue
import subprocess
import re
import secrets
import socket
import struct
import threading
import time
from collections import deque
from pathlib import Path

from aiohttp import web, WSMsgType

from rotorweb import auth
from rotorweb.automation import AutomationMixin
from rotorweb.tracking import TrackingMixin
from rotorweb.satlist import SatListMixin
from rotorweb.updater import UpdaterMixin
from rotorweb import backup
from rotorweb.lookup import Lookup
from rotorweb import detect
from rotorweb.i18n import tr
from rotorweb.geo import angdiff, grid_bearing, valid_grid
from rotorweb.ha_mqtt import HABridge, MODE_FROM_LABEL
from rotorweb.drivers import DRIVERS, DRIVER_MAP, DIY_DRIVERS, DIYDriver, NotCalibrated, make_driver

VERSION = "2.1"
BASE_DIR = Path(__file__).resolve().parent
log = logging.getLogger("rotorweb")

DEFAULT_CONFIG = {
    "callsign": "",
    "grid": "",
    "lang": "fr",                     # langue de la station : courriels, Home Assistant
    "power_park": True,               # repos avant d'éteindre le Raspberry Pi
    "serial_port": "/dev/rotor",
    "baud": 9600,
    "web_port": 8080,
    "gs232_port": 4001,
    "gs232_emulation": "B",          # "B" = GS-232B (AZ=245), "A" = GS-232A (+0245)
    "rotctld_enabled": True,
    "rotctld_port": 4533,
    "elevation": False,
    "rotor": {"driver": "gs232b", "serial_port": "", "baud": 0, "tcp_host": "127.0.0.1", "tcp_port": 4534,
              "rot2prog_ph": 2, "stop_at": 0, "range": 450, "path": "short", "offset": 0, "no_go": [],
              "anticipation": 2, "stall_seconds": 12, "deadtime": 0.5, "el_range": 180,
              "cal_az": [], "cal_el": [],
              "gpio": {"cw": 17, "ccw": 27, "up": 22, "down": 23, "active_low": True,
                       "ads_address": 72, "ads_ch_az": 0, "ads_ch_el": 1}},
    "poll_interval": 0.5,
    "arrive_tolerance": 2,
    "users": {},
    "start_operating": False,
    "wsjtx_enabled": True,
    "wsjtx_group": "224.0.0.1",
    "wsjtx_port": 2237,
    "timezone": "America/Toronto",
    "weather_interval": 300,
    "arrival_timeout": 180,
    "email": {"enabled": False, "smtp_host": "smtp.gmail.com", "smtp_port": 587,
              "username": "", "password": "", "to": ""},
    "mqtt": {"enabled": False, "host": "", "port": 1883, "username": "", "password": "",
             "discovery_prefix": "homeassistant", "base_topic": "rotorweb", "node_id": ""},
    "lookup": {"source": "both", "hamqth_user": "", "hamqth_pass": "", "qrz_user": "", "qrz_pass": ""},
    "rotor_profiles": {},
    "update": {"repo": "RadioamateursduFjord/rotorweb", "url": "", "check_hours": 24},
    "rotor_profile": "",
    "https_cert": "",
    "https_key": "",
    "secret": "",
}

DEFAULT_STATE = {
    "operating": False,
    "estop": False,
    "block_virtual": False,
    "mode": "manual",               # manual | schedule | track
    "wsjtx_path": "short",
    "presets": [],
    "history": [],
    "schedules": [],
    "rest": {"az": 0, "wind_align": False},
    "wind": {"enabled": True, "max_speed": 50, "max_gust": 70, "clear_minutes": 15, "source": "openmeteo"},
    "wind_override_until": 0,
    "user_prefs": {},               # par utilisateur : langue, disposition du tableau de bord
}
MANUAL_SOURCES = ("web", "virtual", "rotctld", "ha")
MODE_NAMES = {"manual": "Manuel", "schedule": "Horaire", "track": "Suivi"}
HELPER = "/usr/local/sbin/rotorweb-helper"   # actions système permises par sudo (installé par install.sh)

# --------------------------------------------------------------------------
# Lien vers le contrôleur (thread dédié, via un pilote de drivers.py)
# --------------------------------------------------------------------------
class RotorLink(threading.Thread):
    def __init__(self, ctrl):
        super().__init__(daemon=True, name="rotor")
        self.ctrl = ctrl
        self.q = queue.Queue()
        self.reload = threading.Event()
        self.paused = threading.Event()
        self.idle = threading.Event()
        self.driver = None

    def send(self, cmd):
        self.q.put(cmd)

    def _drain(self):
        try:
            while True:
                self.q.get_nowait()
        except queue.Empty:
            pass

    def emergency(self):
        self._drain()
        self.q.put("S")
        self.q.put("S")

    def request_reload(self):
        self._drain()
        self.reload.set()

    def pause(self, timeout=8.0):
        """Libère le port série (détection d'un contrôleur). Bloquant : appeler hors de la boucle asyncio."""
        self.idle.clear()
        self.paused.set()
        self.request_reload()
        return self.idle.wait(timeout)

    def resume(self):
        self.paused.clear()

    # Décalage d'antenne : azimut réel = azimut du rotor + décalage
    def _offset(self):
        return float(self.ctrl.cfg["rotor"].get("offset", 0) or 0)

    def to_true(self, az):
        ext = 360 if az >= 360 else 0
        return int(round(((az % 360) + self._offset()) % 360)) + ext

    def to_rotor(self, true_az):
        return (float(true_az) - self._offset()) % 360

    def _dispatch(self, drv, cmd):
        if cmd == "S":
            drv.stop("all")
        elif cmd == "A":
            drv.stop("az")
        elif cmd == "E":
            drv.stop("el")
        elif cmd in ("R", "L", "U", "D"):
            drv.manual("az" if cmd in "RL" else "el", 1 if cmd in "RU" else -1)
        elif cmd.startswith("CAL "):
            drv.calibrate_controller(cmd[4:])
        elif cmd.startswith("M"):
            drv.goto(self.to_rotor(int(cmd[1:])))
        elif cmd.startswith("W"):
            a, e = cmd[1:].split()
            drv.goto(self.to_rotor(int(a)), int(e))

    def run(self):
        while True:
            drv = None
            if self.paused.is_set():
                self.ctrl.set_connected(False, "détection en cours")
                while self.paused.is_set():
                    self.idle.set()
                    time.sleep(0.2)
                self.reload.clear()
            try:
                drv = make_driver(self.ctrl, self.ctrl.simulate)
                self.ctrl.tlog("system", "info", f"Pilote : {DRIVER_MAP[drv.key]['label']}"
                               + (" (simulation)" if self.ctrl.simulate else ""))
                drv.open()
                self.driver = drv
                self.ctrl.set_connected(True)
                last_poll, fails = 0.0, 0
                while not self.reload.is_set():
                    try:
                        cmd = self.q.get(timeout=drv.tick_interval)
                    except queue.Empty:
                        cmd = None
                    if cmd:
                        try:
                            self._dispatch(drv, cmd)
                        except NotCalibrated:
                            self.ctrl.tlog("system", "info", "Calibration requise avant un pointage (onglet Réglage)", blocked=True)
                        except ValueError as e:
                            self.ctrl.tlog("system", "info", str(e), blocked=True)
                    drv.tick()
                    if time.time() - last_poll >= float(self.ctrl.cfg["poll_interval"]):
                        last_poll = time.time()
                        pos = drv.poll()
                        if pos and pos[0] is not None:
                            fails = 0
                            self.ctrl.set_position(self.to_true(pos[0]), pos[1])
                        else:
                            fails += 1
                            if fails == 10 and not isinstance(drv, DIYDriver):
                                self.ctrl.tlog("system", "info", "Le contrôleur ne répond pas à la demande de position "
                                               "(vérifie le pilote, la vitesse et le câble)", blocked=True)
                        self.ctrl.set_rotor_live(drv.info())
                self.reload.clear()
                self.ctrl.tlog("system", "info", "Reconnexion du contrôleur avec les nouveaux réglages…")
            except Exception as e:
                log.warning("Lien contrôleur : %s", e)
                self.ctrl.set_connected(False, str(e))
                time.sleep(3)
            finally:
                self.driver = None
                if drv:
                    try:
                        drv.stop("all")
                    except Exception:
                        pass
                    drv.close()


# --------------------------------------------------------------------------
# Lecture des messages UDP WSJT-X (format QDataStream)
# --------------------------------------------------------------------------
class QReader:
    def __init__(self, b):
        self.b, self.i = b, 0

    def u32(self):
        v = struct.unpack_from(">I", self.b, self.i)[0]
        self.i += 4
        return v

    def u64(self):
        v = struct.unpack_from(">Q", self.b, self.i)[0]
        self.i += 8
        return v

    def boolean(self):
        v = self.b[self.i] != 0
        self.i += 1
        return v

    def utf8(self):
        n = self.u32()
        if n == 0xFFFFFFFF:
            return ""
        v = self.b[self.i:self.i + n].decode("utf-8", "replace")
        self.i += n
        return v


class WsjtxProtocol(asyncio.DatagramProtocol):
    def __init__(self, ctrl):
        self.ctrl = ctrl

    def datagram_received(self, data, addr):
        try:
            self.ctrl.on_wsjtx(data, addr)
        except Exception as e:
            log.debug("Paquet WSJT-X ignoré : %s", e)


# --------------------------------------------------------------------------
# Contrôleur principal
# --------------------------------------------------------------------------
class Controller(AutomationMixin, TrackingMixin, SatListMixin, UpdaterMixin):
    def __init__(self, config_path, simulate=False):
        self.config_path = Path(config_path)
        self.simulate = simulate
        self.cfg = self._load_config()
        self.cfg.pop("password", None)  # ancien réglage v1.0, remplacé par les comptes
        self._cfg_mtime = self.config_path.stat().st_mtime if self.config_path.exists() else 0
        self.login_fails = {}
        self.state_path = self.config_path.with_name("state.json")
        self.state = self._load_state()
        if not self.cfg.get("start_operating"):
            self.state["operating"] = False
        self.state.pop("wsjtx_follow", None)
        if self.state.get("mode") not in MODE_NAMES:  # v1.7 : le mode Automatique (WSJT-X) est retiré
            self.state["mode"] = "manual"
        self.loop = None
        self.az = None
        self.el = None
        self.target_az = None
        self.target_el = None
        self.connected = False
        self.conn_error = ""
        self.websockets = set()
        self.clients = {"web": 0, "virtual": 0, "rotctld": 0}
        self.logbuf = deque(maxlen=400)
        self.manual_deadline = None
        self.last_pos_push = 0.0
        self.wsjtx = {"seen": 0, "dx_call": "", "dx_grid": "", "mode": "", "freq": 0,
                      "bearing": None, "distance": None, "id": ""}
        self._wsjtx_key = None
        self.rotor = RotorLink(self)
        self.no_auth = False
        self.version = VERSION
        self.rotor_live = {}
        self.manual_active = False
        self._stall = None
        self.auto_init()
        self.track_init()
        self.satlist_init()
        self.updater_init()
        self.lookup = Lookup(self)
        self.ws_users = {}
        self.probe_state = {"busy": False}
        self.ha = HABridge(self)

    # ---------- config / état ----------
    def _load_config(self):
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        if self.config_path.exists():
            disk = json.loads(self.config_path.read_text(encoding="utf-8"))
            for k in ("email", "mqtt", "rotor", "lookup", "update"):
                if isinstance(disk.get(k), dict):
                    disk[k] = {**cfg[k], **disk[k]}
            if isinstance(disk.get("rotor"), dict) and isinstance(disk["rotor"].get("gpio"), dict):
                disk["rotor"]["gpio"] = {**cfg["rotor"]["gpio"], **disk["rotor"]["gpio"]}
            cfg.update(disk)
        if not cfg.get("secret"):
            cfg["secret"] = secrets.token_hex(16)
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        return cfg

    def users(self):
        """Comptes relus depuis config.json s'il a changé (ajout via users.sh sans redémarrage)."""
        try:
            m = self.config_path.stat().st_mtime
            if m != self._cfg_mtime:
                self._cfg_mtime = m
                disk = json.loads(self.config_path.read_text(encoding="utf-8"))
                self.cfg["users"] = disk.get("users", {})
        except Exception:
            pass
        return self.cfg.get("users") or {}

    def save_config(self):
        self.users()
        tmp = self.config_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.config_path)
        self._cfg_mtime = self.config_path.stat().st_mtime

    def _load_state(self):
        st = json.loads(json.dumps(DEFAULT_STATE))
        p = self.config_path.with_name("state.json")
        if p.exists():
            try:
                disk = json.loads(p.read_text(encoding="utf-8"))
                for k in ("rest", "wind"):
                    if isinstance(disk.get(k), dict):
                        disk[k] = {**st[k], **disk[k]}
                st.update(disk)
            except Exception:
                pass
        return st

    def save_state(self):
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.state_path)

    # ---------- démarrage ----------
    async def start(self):
        self.loop = asyncio.get_running_loop()
        self.rotor.start()
        await asyncio.start_server(self.handle_gs232, "0.0.0.0", int(self.cfg["gs232_port"]))
        log.info("Port GS-232 (COM virtuel) : TCP %s", self.cfg["gs232_port"])
        if self.cfg.get("rotctld_enabled"):
            await asyncio.start_server(self.handle_rotctld, "0.0.0.0", int(self.cfg["rotctld_port"]))
            log.info("Port rotctld (Hamlib) : TCP %s", self.cfg["rotctld_port"])
        if self.cfg.get("wsjtx_enabled"):
            try:
                sock = self._wsjtx_socket()
                await self.loop.create_datagram_endpoint(lambda: WsjtxProtocol(self), sock=sock)
                log.info("Écoute WSJT-X : %s:%s", self.cfg["wsjtx_group"], self.cfg["wsjtx_port"])
            except OSError as e:
                log.warning("WSJT-X UDP indisponible : %s", e)
                self.tlog("system", "info", f"Écoute WSJT-X impossible : {e}")
        asyncio.create_task(self._watchdog())
        self.auto_start()
        self.track_start()
        self.satlist_start()
        self.updater_start()
        self.ha.start()
        mode = "SIMULATION" if self.simulate else self.cfg["serial_port"]
        self.tlog("system", "info", f"RotorWeb {VERSION} démarré ({mode})")

    def _wsjtx_socket(self):
        group, port = self.cfg["wsjtx_group"], int(self.cfg["wsjtx_port"])
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        s.bind(("", port))
        first = int(group.split(".")[0]) if group[0].isdigit() else 0
        if 224 <= first <= 239:
            mreq = struct.pack("4s4s", socket.inet_aton(group), socket.inet_aton("0.0.0.0"))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        s.setblocking(False)
        return s

    # ---------- appels depuis le thread série ----------
    def _threadsafe(self, fn, *args):
        if self.loop:
            self.loop.call_soon_threadsafe(fn, *args)

    def tlog(self, src, direction, text, poll=False, blocked=False, peer=""):
        entry = {"t": time.time(), "src": src, "dir": direction, "text": text,
                 "poll": poll, "blocked": blocked, "peer": peer}
        if self.loop and threading.current_thread() is not threading.main_thread():
            self._threadsafe(self._push_log, entry)
        else:
            self._push_log(entry)

    def _push_log(self, entry):
        if not entry["poll"]:
            self.logbuf.append(entry)
        self.broadcast({"type": "log", "entry": entry})

    def set_position(self, az, el):
        self._threadsafe(self._on_position, az, el)

    def set_rotor_live(self, info):
        self._threadsafe(self._on_rotor_live, info)

    def _on_rotor_live(self, info):
        if info != self.rotor_live:
            self.rotor_live = info
            self.broadcast({"type": "live", "live": info})
        if info.get("relay_az") == 0 and self.manual_active and self.rotor_cfg_driver() in DIY_DRIVERS \
                and self.manual_deadline is None:
            self.manual_active = False  # limite de course atteinte

    def rotor_cfg_driver(self):
        return self.cfg["rotor"].get("driver", "gs232b")

    def set_connected(self, ok, err=""):
        self._threadsafe(self._on_connected, ok, err)

    def _on_connected(self, ok, err):
        if ok != self.connected:
            self.tlog("system", "info", "Contrôleur connecté" if ok else f"Contrôleur déconnecté : {err}")
        self.connected, self.conn_error = ok, err
        self.broadcast_state()

    def _on_position(self, az, el):
        changed = (az != self.az) or (el != self.el)
        self.az, self.el = az, el
        tol = float(self.cfg.get("arrive_tolerance", 2))
        if self.target_az is not None and abs(((az - self.target_az) + 540) % 360 - 180) <= tol:
            self.target_az = None
            changed = True
        if self.target_el is not None and el is not None and abs(el - self.target_el) <= tol:
            self.target_el = None
        now = time.time()
        self.check_confirm()
        if changed or now - self.last_pos_push > 2:
            self.last_pos_push = now
            self.broadcast({"type": "pos", "az": az, "el": el,
                            "target_az": self.target_az, "target_el": self.target_el})
            self.ha.sync()

    # ---------- diffusion ----------
    def broadcast(self, msg):
        for ws in list(self.websockets):
            if not ws.closed:
                asyncio.ensure_future(self._safe_send(ws, msg))

    @staticmethod
    async def _safe_send(ws, msg):
        try:
            await ws.send_json(msg)
        except Exception:
            pass

    def public_state(self):
        return {
            "type": "state", "version": VERSION, "simulate": self.simulate,
            "callsign": self.cfg["callsign"], "grid": self.cfg["grid"],
            "elevation": bool(self.cfg["elevation"]), "max_azimuth": self.cfg["rotor"].get("range", 450),
            "ports": {"web": self.cfg["web_port"], "gs232": self.cfg["gs232_port"],
                      "rotctld": self.cfg["rotctld_port"] if self.cfg.get("rotctld_enabled") else None},
            "az": self.az, "el": self.el, "target_az": self.target_az, "target_el": self.target_el,
            "connected": self.connected, "conn_error": self.conn_error,
            "operating": self.state["operating"], "estop": self.state["estop"],
            "block_virtual": self.state["block_virtual"],
            "wsjtx_path": self.state["wsjtx_path"],
            "presets": self.state["presets"], "history": self.state["history"],
            "clients": self.clients, "wsjtx": self.wsjtx,
            "mode": self.state["mode"],
            "schedules": [{**x, "label": self.target_label(x["target"])} for x in self.state["schedules"]],
            "sched": self.sched_info, "regions": self.regions_public(),
            "rest": self.state["rest"], "rest_az": round(self.rest_az()),
            "wind": self.state["wind"], "weather": self.weather,
            "wind_locked": self.wind_locked, "wind_calm_since": self.wind_calm_since,
            "wind_override_until": self.state.get("wind_override_until") or 0,
            "timezone": self.cfg.get("timezone"),
            "mqtt": self.ha.status(),
            "track": self.track_public(), "targets": self.targets_public(), "satlist": self.satlist_public(),
            "lang": self.cfg.get("lang", "fr"), "lookup": self.lookup.public(), "update": self.update_public(),
            "power_park": bool(self.cfg.get("power_park", True)), "power_ok": self.simulate or os.path.exists(HELPER),
            "profiles": sorted(self.cfg.get("rotor_profiles") or {}), "profile": self.cfg.get("rotor_profile") or "",
            "rotor": self.cfg["rotor"], "drivers": DRIVERS, "live": self.rotor_live,
            "email": {k: (self.cfg.get("email") or {}).get(k) for k in ("enabled", "username", "to")}
                     | {"has_password": bool((self.cfg.get("email") or {}).get("password"))},
        }

    def broadcast_state(self):
        self.broadcast(self.public_state())
        if hasattr(self, "ha"):
            self.ha.sync()

    # ---------- règles de sécurité ----------
    def can_move(self, source):
        if self.state["estop"]:
            return False, "ARRÊT D'URGENCE actif"
        if not self.state["operating"]:
            return False, "Hors opération"
        if source in ("virtual", "rotctld") and self.state["block_virtual"]:
            return False, "Port virtuel bloqué"
        if source == "schedule" and self.state["mode"] != "schedule":
            return False, "Mode Horaire inactif"
        if source == "track" and self.state["mode"] != "track":
            return False, "Mode Suivi inactif"
        if self.wind_locked and source != "wind":
            if not (source in MANUAL_SOURCES and self.override_active()):
                return False, f"Verrou vent ({self.wind_desc()})"
        if not self.connected:
            return False, "Contrôleur non connecté"
        return True, ""

    def set_mode(self, mode, who="", why=""):
        if mode == self.state["mode"]:
            return
        self.state["mode"] = mode
        self.pending_confirm = None
        self.sched_applied = "__reapply__"
        self.sched_fail_notified = None
        self.sched_track = None
        self.track_last_cmd = None
        self._track_refused_until = 0
        self._wsjtx_key = None
        self.save_state()
        self.tlog("web", "info", f"Mode {MODE_NAMES[mode]}{(' — ' + why) if why else ''}", peer=who)
        if mode == "schedule":
            self.scheduler_tick()
        self.broadcast_state()

    def _manual_takeover(self, source, peer):
        # Une commande manuelle en mode Horaire ou Suivi repasse en mode Manuel
        if source in MANUAL_SOURCES and self.state["mode"] != "manual":
            self.set_mode("manual", who=peer, why="commande manuelle")

    def request_move(self, source, az, el=None, peer="", label="", quiet=False):
        ok, reason = self.can_move(source)
        az = int(round(float(az))) % 360
        desc = f"{label} → " if label else ""
        if ok and source != "wind":
            for zone in self.cfg["rotor"].get("no_go") or []:
                a, b = float(zone[0]) % 360, float(zone[1]) % 360
                if (a <= az <= b) if a <= b else (az >= a or az <= b):
                    ok, reason = False, f"zone interdite ({round(a)}°–{round(b)}°)"
                    break
        if ok and self.rotor_cfg_driver() in DIY_DRIVERS and not self.rotor_live.get("calibrated", False):
            ok, reason = False, "calibration requise (onglet Réglage)"
        if not ok:
            if not quiet:
                self.tlog(source, "info", f"REFUSÉ {desc}{az}° : {reason}", blocked=True, peer=peer)
            return False, reason
        self._manual_takeover(source, peer)
        if el is not None and self.cfg["elevation"]:
            el = max(0, min(180, int(round(float(el)))))
            cmd = f"W{az:03d} {el:03d}"
            self.target_el = el
        else:
            cmd = f"M{az:03d}"
        self.target_az = az
        self.manual_deadline = None
        self.manual_active = False
        self._stall = None
        self.rotor.send(cmd)
        if source != "virtual" and not quiet:  # le trafic du port virtuel est déjà affiché
            self.tlog(source, "info", f"{desc}Rotation vers {az}°" + (f" / él. {el}°" if el is not None and self.cfg["elevation"] else ""), peer=peer)
        self.broadcast({"type": "pos", "az": self.az, "el": self.el,
                        "target_az": self.target_az, "target_el": self.target_el})
        return True, ""

    def request_manual(self, source, direction, peer=""):
        ok, reason = self.can_move(source)
        if not ok:
            self.tlog(source, "info", f"REFUSÉ rotation {direction} : {reason}", blocked=True, peer=peer)
            return False, reason
        if direction in ("U", "D") and not self.cfg["elevation"]:
            return False, "Élévation désactivée"
        self._manual_takeover(source, peer)
        self.target_az = None
        self.manual_active = True
        self._stall = None
        self.rotor.send(direction)
        if source == "web":
            self.manual_deadline = time.time() + 1.0
        noms = {"R": "droite (horaire)", "L": "gauche (anti-horaire)", "U": "haut", "D": "bas"}
        if source != "virtual":
            self.tlog(source, "info", f"Rotation manuelle {noms[direction]}", peer=peer)
        return True, ""

    def request_stop(self, source, peer="", why=""):
        # Un STOP est TOUJOURS accepté, peu importe la source et les blocages
        self.manual_deadline = None
        self.manual_active = False
        self.target_az = self.target_el = None
        self.rotor.send("S")
        if source != "virtual":
            self.tlog(source, "info", f"STOP{(' — ' + why) if why else ''}", peer=peer)
        self.broadcast({"type": "pos", "az": self.az, "el": self.el, "target_az": None, "target_el": None})

    def emergency_stop(self, source, peer=""):
        self.state["estop"] = True
        self.pending_confirm = None
        self.manual_active = False
        self.manual_deadline = None
        self.target_az = self.target_el = None
        self.rotor.emergency()
        self.save_state()
        self.tlog(source, "info", "🛑 ARRÊT D'URGENCE déclenché", blocked=True, peer=peer)
        self.broadcast_state()

    def rearm(self, peer=""):
        self.state["estop"] = False
        self.save_state()
        self.tlog("web", "info", "Arrêt d'urgence réarmé", peer=peer)
        self.broadcast_state()

    async def _watchdog(self):
        # Rotation manuelle web : si le bouton n'est plus tenu (ou la connexion coupe), on arrête
        while True:
            await asyncio.sleep(0.2)
            if self.manual_deadline and time.time() > self.manual_deadline:
                self.request_stop("web", why="bouton relâché / connexion perdue")
            self._check_stall()

    def _check_stall(self):
        """Détection de blocage : le rotor devrait bouger mais sa position ne change pas."""
        limit = float(self.cfg["rotor"].get("stall_seconds", 12) or 0)
        moving = (self.target_az is not None) or self.manual_active
        if not (limit > 0 and moving and self.connected and self.az is not None):
            self._stall = None
            return
        now = time.time()
        if self._stall is None or angdiff(self.az, self._stall[0]) > 1.0:
            self._stall = (self.az, now)
        elif now - self._stall[1] > limit:
            self._stall = None
            pos = self.az
            self.request_stop("system", why="rotor immobile")
            self.tlog("system", "info", f"⚠ Rotor immobile depuis {int(limit)} s à {pos}° : arrêt de sécurité "
                                        f"(butée, blocage ou capteur ?)", blocked=True)
            self.send_email("⚠ ALERTE : rotor immobile",
                            f"Le rotor devait bouger mais sa position est restée à {pos}° pendant {int(limit)} s.\n"
                            f"Les commandes ont été coupées par sécurité.\n\nCauses possibles : butée atteinte, "
                            f"rotor bloqué (glace, vent), moteur, câble ou capteur de position.")

    # ---------- port GS-232 (COM virtuel) ----------
    def _fmt(self, what):
        az = int(self.az or 0)
        el = int(self.el or 0)
        if self.cfg.get("gs232_emulation", "B").upper() == "A":
            return {"az": f"+0{az:03d}", "azel": f"+0{az:03d}+0{el:03d}", "el": f"+0{el:03d}"}[what]
        return {"az": f"AZ={az:03d}", "azel": f"AZ={az:03d} EL={el:03d}", "el": f"EL={el:03d}"}[what]

    def gs232_command(self, line, ip):
        c = line.strip().upper()
        poll = c in ("C", "C2", "B")
        resp = None
        blocked_note = ""
        if c == "C":
            resp = self._fmt("az")
        elif c == "C2":
            resp = self._fmt("azel")
        elif c == "B":
            resp = self._fmt("el")
        elif c in ("S", "A", "E"):
            self.tlog("virtual", "rx", c, peer=ip)
            self.request_stop("virtual", ip)
            return None
        else:
            self.tlog("virtual", "rx", c, peer=ip)
            m = re.fullmatch(r"M\s*(\d{1,3})", c)
            w = re.fullmatch(r"W\s*(\d{1,3})\s+(\d{1,3})", c)
            if m:
                ok, blocked_note = self.request_move("virtual", int(m.group(1)), peer=ip)
            elif w:
                ok, blocked_note = self.request_move("virtual", int(w.group(1)), int(w.group(2)), peer=ip)
            elif c in ("R", "L", "U", "D"):
                ok, blocked_note = self.request_manual("virtual", c, ip)
            else:
                self.tlog("virtual", "info", f"Commande non supportée : {c}", peer=ip)
            return None
        self.tlog("virtual", "rx", c, poll=True, peer=ip)
        self.tlog("virtual", "tx", resp, poll=True, peer=ip)
        return resp

    async def handle_gs232(self, reader, writer):
        ip = (writer.get_extra_info("peername") or ("?",))[0]
        self.clients["virtual"] += 1
        self.tlog("virtual", "info", f"Client connecté ({ip})", peer=ip)
        self.broadcast_state()
        buf = b""
        try:
            while True:
                data = await reader.read(256)
                if not data:
                    break
                buf += data
                if len(buf) > 2048:
                    buf = b""
                while True:
                    m = re.search(rb"[\r\n]", buf)
                    if not m:
                        break
                    line = buf[:m.start()].decode("ascii", "replace").strip()
                    buf = buf[m.end():]
                    if not line:
                        continue
                    resp = self.gs232_command(line, ip)
                    if resp is not None:
                        writer.write((resp + "\r\n").encode("ascii"))
                        await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self.clients["virtual"] -= 1
            self.tlog("virtual", "info", f"Client déconnecté ({ip})", peer=ip)
            self.broadcast_state()
            try:
                writer.close()
            except Exception:
                pass

    # ---------- port rotctld (Hamlib réseau) ----------
    def rotctld_command(self, line, ip):
        parts = line.strip().split()
        if not parts:
            return None
        c = parts[0]
        if c in ("p", "\\get_pos"):
            self.tlog("rotctld", "rx", c, poll=True, peer=ip)
            return f"{float(self.az or 0):.6f}\n{float(self.el or 0):.6f}"
        self.tlog("rotctld", "rx", line.strip(), peer=ip)
        if c in ("P", "\\set_pos") and len(parts) >= 3:
            try:
                az, el = float(parts[1]) % 360, float(parts[2])
            except ValueError:
                return "RPRT -1"
            ok, _ = self.request_move("rotctld", az, el if self.cfg["elevation"] else None, peer=ip)
            return "RPRT 0" if ok else "RPRT -1"
        if c in ("S", "\\stop"):
            self.request_stop("rotctld", ip)
            return "RPRT 0"
        if c in ("_", "\\get_info"):
            return f"RotorWeb {VERSION}"
        if c == "\\dump_state":
            return f"1\n0\n0.000000\n{float(self.cfg['rotor'].get('range', 450)):.6f}\n0.000000\n90.000000"
        if c in ("q", "Q", "\\quit"):
            return "QUIT"
        return "RPRT -4"

    async def handle_rotctld(self, reader, writer):
        ip = (writer.get_extra_info("peername") or ("?",))[0]
        self.clients["rotctld"] += 1
        self.tlog("rotctld", "info", f"Client connecté ({ip})", peer=ip)
        self.broadcast_state()
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                resp = self.rotctld_command(line.decode("ascii", "replace"), ip)
                if resp == "QUIT":
                    break
                if resp is not None:
                    writer.write((resp + "\n").encode("ascii"))
                    await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self.clients["rotctld"] -= 1
            self.tlog("rotctld", "info", f"Client déconnecté ({ip})", peer=ip)
            self.broadcast_state()
            try:
                writer.close()
            except Exception:
                pass

    # ---------- WSJT-X ----------
    def on_wsjtx(self, data, addr):
        r = QReader(data)
        if r.u32() != 0xADBCCBDA:
            return
        r.u32()  # schéma
        mtype = r.u32()
        wid = r.utf8()
        self.wsjtx["seen"] = time.time()
        self.wsjtx["id"] = wid
        if mtype != 1:  # 1 = Status
            return
        freq = r.u64()
        mode = r.utf8()
        dx_call = r.utf8()
        r.utf8()      # report
        r.utf8()      # tx mode
        r.boolean()   # tx enabled
        r.boolean()   # transmitting
        r.boolean()   # decoding
        r.u32()       # rx df
        r.u32()       # tx df
        r.utf8()      # de call
        r.utf8()      # de grid
        dx_grid = r.utf8().strip().upper()
        self.wsjtx.update({"freq": freq, "mode": mode, "dx_call": dx_call, "dx_grid": dx_grid})
        key = (dx_call, dx_grid)
        if key == self._wsjtx_key:
            return
        self._wsjtx_key = key
        self.wsjtx["bearing"] = self.wsjtx["distance"] = None
        if dx_call:
            self.tlog("wsjtx", "rx", f"DX {dx_call} {dx_grid or '(grid inconnu)'}", peer=addr[0])
        if valid_grid(dx_grid) and valid_grid(self.cfg["grid"]):
            b, d = grid_bearing(self.cfg["grid"], dx_grid, self.state["wsjtx_path"])
            self.wsjtx["bearing"], self.wsjtx["distance"] = round(b), round(d)
        self.broadcast_state()

    # ---------- réglage du contrôleur, course et calibration ----------
    def _travel_for(self, true_az):
        rc = self.cfg["rotor"]
        rotor_az = (float(true_az) - float(rc.get("offset", 0) or 0)) % 360
        t0 = (rotor_az - float(rc.get("stop_at", 0))) % 360
        cands = [t for t in (t0, t0 + 360) if t <= float(rc.get("range", 450))]
        cur = self.rotor_live.get("travel")
        if cur is not None and cands:
            return min(cands, key=lambda t: abs(t - cur))
        return cands[0] if cands else t0

    async def rotor_cmd(self, cmd, d, ip, toast):
        rc = self.cfg["rotor"]
        if cmd == "rotor_save":
            drv = d.get("driver")
            if drv not in DRIVER_MAP:
                await toast("Pilote inconnu")
                return True
            try:
                rc.update(driver=drv, serial_port=str(d.get("serial_port", "")).strip(),
                          baud=int(d.get("baud") or 0), tcp_host=str(d.get("tcp_host") or "127.0.0.1").strip(),
                          tcp_port=int(d.get("tcp_port") or 4534), rot2prog_ph=int(d.get("rot2prog_ph") or 2))
                if isinstance(d.get("gpio"), dict):
                    g = rc.setdefault("gpio", {})
                    for k in ("cw", "ccw", "up", "down", "ads_address", "ads_ch_az", "ads_ch_el"):
                        if k in d["gpio"]:
                            g[k] = int(d["gpio"][k])
                    g["active_low"] = bool(d["gpio"].get("active_low", True))
            except (TypeError, ValueError):
                await toast("Valeur invalide dans les réglages du contrôleur")
                return True
            self.save_config()
            self.az = None
            self.target_az = None
            self.rotor.request_reload()
            self.tlog("web", "info", f"Contrôleur : {DRIVER_MAP[drv]['label']}", peer=ip)
            self.broadcast_state()
            await toast("Contrôleur enregistré — reconnexion…", "ok")
            return True
        if cmd == "course_save":
            try:
                stop_at = int(d.get("stop_at", 0)) % 360
                rng = max(90, min(720, int(d.get("range", 450))))
                rc.update(stop_at=stop_at, range=rng,
                          path=d.get("path") if d.get("path") in ("short", "avoid_overlap") else "short",
                          anticipation=max(0.0, min(20.0, float(d.get("anticipation", 2)))),
                          stall_seconds=max(0, min(300, int(d.get("stall_seconds", 12)))),
                          deadtime=max(0.1, min(5.0, float(d.get("deadtime", 0.5)))),
                          el_range=90 if int(d.get("el_range", 180)) == 90 else 180)
            except (TypeError, ValueError):
                await toast("Valeur invalide dans la course")
                return True
            self.save_config()
            self.tlog("web", "info", f"Course : butée {stop_at}°, amplitude {rng}°, chemin {rc['path']}", peer=ip)
            self.broadcast_state()
            await toast("Course enregistrée", "ok")
            return True
        if cmd == "nogo_add":
            try:
                a, b = int(d["from"]) % 360, int(d["to"]) % 360
            except (KeyError, TypeError, ValueError):
                await toast("Zone invalide")
                return True
            rc.setdefault("no_go", []).append([a, b])
            self.save_config()
            self.tlog("web", "info", f"Zone interdite ajoutée : {a}°–{b}°", peer=ip)
            self.broadcast_state()
            return True
        if cmd == "nogo_del":
            i = int(d.get("index", -1))
            if 0 <= i < len(rc.get("no_go", [])):
                rc["no_go"].pop(i)
                self.save_config()
                self.broadcast_state()
            return True
        if cmd == "offset_set":
            try:
                if "offset" in d:
                    off = float(d["offset"])
                else:
                    if self.az is None:
                        await toast("Position actuelle inconnue")
                        return True
                    rotor_az = (self.az - float(rc.get("offset", 0) or 0)) % 360
                    off = float(d["real"]) - rotor_az
            except (TypeError, ValueError):
                await toast("Valeur invalide")
                return True
            off = ((off + 180) % 360) - 180
            rc["offset"] = round(off, 1)
            self.save_config()
            self.tlog("web", "info", f"Décalage d'antenne : {rc['offset']:+.1f}°", peer=ip)
            self.broadcast_state()
            await toast(f"Décalage enregistré : {rc['offset']:+.1f}°", "ok")
            return True
        if cmd in ("cal_end", "cal_point"):
            axis = "el" if d.get("axis") == "el" else "az"
            raw = self.rotor_live.get("raw_el" if axis == "el" else "raw_az")
            if raw is None:
                await toast("Aucune valeur brute du capteur (contrôleur « bidouille » branché ?)")
                return True
            key = "cal_el" if axis == "el" else "cal_az"
            pts = rc.setdefault(key, [])
            try:
                if cmd == "cal_end":
                    which = d.get("which")
                    if axis == "az":
                        deg = 0.0 if which == "ccw" else float(rc.get("range", 450))
                    else:
                        deg = 0.0 if which == "down" else float(rc.get("el_range", 180))
                else:
                    deg = self._travel_for(float(d["deg"])) if axis == "az" else float(d["deg"])
            except (KeyError, TypeError, ValueError):
                await toast("Valeur invalide")
                return True
            pts[:] = [p for p in pts if abs(float(p[1]) - deg) > 0.5 and int(p[0]) != int(raw)]
            pts.append([int(raw), round(deg, 1)])
            pts.sort(key=lambda p: p[1])
            self.save_config()
            self.tlog("web", "info", f"Calibration {axis} : brut {raw} = {deg:.1f}°"
                                     + (" de course" if axis == "az" else ""), peer=ip)
            self.broadcast_state()
            return True
        if cmd in ("cal_del", "cal_clear"):
            key = "cal_el" if d.get("axis") == "el" else "cal_az"
            pts = rc.setdefault(key, [])
            if cmd == "cal_clear":
                pts.clear()
            else:
                i = int(d.get("index", -1))
                if 0 <= i < len(pts):
                    pts.pop(i)
            self.save_config()
            self.broadcast_state()
            return True
        if cmd == "sim_jam" and self.simulate:
            drv = self.rotor.driver
            if drv and drv.motor:
                drv.motor.SPEED = 0.0 if d.get("jam") else 6.0
                self.tlog("system", "info", f"[SIMULATION] rotor {'bloqué' if d.get('jam') else 'libéré'}")
            return True
        if cmd == "cal_controller":
            which = d.get("which")
            if self.rotor_cfg_driver() not in ("gs232a", "gs232b") or which not in ("O", "F", "O2", "F2"):
                await toast("Calibration du contrôleur disponible seulement en GS-232 (K3NG, Yaesu)")
                return True
            self.rotor.send("CAL " + which)
            self.tlog("web", "info", f"Commande de calibration GS-232 envoyée : {which}", peer=ip)
            await toast(f"Commande {which} envoyée au contrôleur", "ok")
            return True
        return False

    # ---------- traduction (courriels, Home Assistant : langue de la station) ----------
    def tr(self, text):
        return tr(text, self.cfg.get("lang", "fr"))

    # ---------- préférences par utilisateur (langue, tableau de bord) ----------
    def user_prefs(self, user):
        p = self.state.setdefault("user_prefs", {}).setdefault(user or "?", {})
        p.setdefault("lang", self.cfg.get("lang", "fr"))
        p.setdefault("layout", {})
        return p

    # ---------- arrêt / redémarrage du Raspberry Pi ----------
    async def system_cmd(self, action, ip, toast):
        names = {"poweroff": "Arrêt du Raspberry Pi", "reboot": "Redémarrage du Raspberry Pi",
                 "restart": "Redémarrage de RotorWeb"}
        if action not in names:
            return
        if not self.simulate and not os.path.exists(HELPER):
            await toast("Commande système non installée : relance sudo ./update.sh", "error")
            return
        self.tlog("web", "info", f"⏻ {names[action]} demandé", peer=ip)
        if action in ("poweroff", "reboot") and self.cfg.get("power_park", True) and self.state["operating"] \
                and not self.state["estop"] and self.connected:
            az = self.rest_az()
            ok, _ = self.request_move("system", az, 0 if self.cfg.get("elevation") else None,
                                      label=f"Repos avant {'arrêt' if action == 'poweroff' else 'redémarrage'} ({round(az)}°)")
            if ok:
                await toast("Antenne en route vers le repos, puis " + names[action].lower() + "…", "ok")
                t0 = time.time()
                while self.target_az is not None and time.time() - t0 < 90:
                    await asyncio.sleep(1)
        self.request_stop("system", why=names[action])
        self.save_state()
        await asyncio.sleep(1.0)
        self.broadcast({"type": "system", "action": action})
        if self.simulate:
            self.tlog("system", "info", f"[SIMULATION] {names[action]} (non exécuté)")
            return
        await asyncio.sleep(0.5)
        subprocess.Popen(["sudo", "-n", HELPER, action], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ---------- changement de contrôleur : détection, profils ----------
    def _rotor_snapshot(self):
        return {**json.loads(json.dumps(self.cfg["rotor"])), "elevation": bool(self.cfg.get("elevation"))}

    def _apply_rotor(self, rotor, ip, label):
        prev = self._rotor_snapshot()
        detect.backup_config(self.config_path)
        self.cfg.setdefault("rotor_profiles", {})["↩ Précédent"] = prev
        el = rotor.pop("elevation", None)
        self.cfg["rotor"] = {**json.loads(json.dumps(DEFAULT_CONFIG["rotor"])), **rotor}
        if el is not None:
            self.cfg["elevation"] = bool(el)
        self.save_config()
        self.az = None
        self.target_az = self.target_el = None
        self.rotor.request_reload()
        self.tlog("web", "info", f"Contrôleur : {label}", peer=ip)
        self.broadcast_state()

    async def ctrl_cmd(self, cmd, d, ip, ws, toast):
        if cmd == "ctrl_scan":
            ports = await self.loop.run_in_executor(None, detect.list_ports)
            if self.simulate:
                ports = [{"path": "/dev/serial/by-id/usb-Simulation_K3NG-if00", "dev": "/dev/ttyACM0",
                          "name": "Simulation · Arduino (K3NG)"}] + ports
            ads = await self.loop.run_in_executor(None, detect.i2c_ads1115)
            await self._safe_send(ws, {"type": "ctrl_ports", "ports": ports, "ads1115": ads,
                                       "current": self.cfg["rotor"].get("serial_port") or self.cfg.get("serial_port")})
            return True
        if cmd == "ctrl_probe":
            if self.probe_state["busy"]:
                await toast("Détection déjà en cours")
                return True
            port = str(d.get("port") or "")
            if not port:
                await toast("Choisis un port")
                return True
            self.probe_state["busy"] = True
            self.request_stop("system", why="détection du contrôleur")
            self.tlog("web", "info", f"Détection du contrôleur sur {port}…", peer=ip)
            loop = self.loop

            def progress(i, n, key, baud):
                asyncio.run_coroutine_threadsafe(self._safe_send(ws, {
                    "type": "ctrl_progress", "i": i, "n": n, "label": detect.DRIVER_MAP[key]["label"], "baud": baud}), loop)

            def work():
                self.rotor.pause()
                try:
                    return detect.probe_port(port, full=bool(d.get("full")), simulate=self.simulate,
                                             sim_device=self.rotor_cfg_driver() if self.rotor_cfg_driver() not in ("hamlib", "gpio") else "gs232b",
                                             progress=progress, base=self.cfg["rotor"])
                finally:
                    self.rotor.resume()
            try:
                found = await self.loop.run_in_executor(None, work)
            finally:
                self.probe_state["busy"] = False
            self.tlog("web", "info", ("Détecté : " + found[0]["label"] + f" @ {found[0]['baud']}") if found
                      else "Aucun contrôleur reconnu", peer=ip, blocked=not found)
            await self._safe_send(ws, {"type": "ctrl_found", "port": port, "found": found})
            return True
        if cmd == "ctrl_apply":
            drv = d.get("driver")
            if drv not in DRIVER_MAP:
                await toast("Pilote inconnu")
                return True
            new = self._rotor_snapshot()
            try:
                new.update(driver=drv, serial_port=str(d.get("serial_port") or new.get("serial_port") or ""),
                           baud=int(d.get("baud") or 0))
                if d.get("tcp_host"):
                    new.update(tcp_host=str(d["tcp_host"]), tcp_port=int(d.get("tcp_port") or 4534))
                if d.get("ads_address") is not None:
                    new.setdefault("gpio", {})["ads_address"] = int(d["ads_address"])
                if "elevation" in d:
                    new["elevation"] = bool(d["elevation"])
            except (TypeError, ValueError):
                await toast("Valeur invalide")
                return True
            if d.get("reset_cal"):
                new.update(cal_az=[], cal_el=[], offset=0)
            if d.get("reset_course"):
                new.update(stop_at=0, range=450 if drv not in ("rot2prog",) else 360, no_go=[], path="short")
            self.cfg["rotor_profile"] = ""
            self._apply_rotor(new, ip, DRIVER_MAP[drv]["label"])
            await toast("Contrôleur changé — reconnexion… (ancienne config gardée dans « ↩ Précédent »)", "ok")
            return True
        if cmd == "profile_save":
            name = str(d.get("name", "")).strip()[:30]
            if not name:
                await toast("Donne un nom au profil")
                return True
            self.cfg.setdefault("rotor_profiles", {})[name] = self._rotor_snapshot()
            self.cfg["rotor_profile"] = name
            self.save_config()
            self.tlog("web", "info", f"Profil de rotor enregistré : {name}", peer=ip)
            self.broadcast_state()
            await toast(f"Profil « {name} » enregistré", "ok")
            return True
        if cmd == "profile_load":
            name = d.get("name")
            prof = (self.cfg.get("rotor_profiles") or {}).get(name)
            if not prof:
                await toast("Profil introuvable")
                return True
            self._apply_rotor(json.loads(json.dumps(prof)), ip, f"profil « {name} »")
            if not name.startswith("↩"):
                self.cfg["rotor_profile"] = name
                self.save_config()
            self.broadcast_state()
            await toast(f"Profil « {name} » chargé — reconnexion…", "ok")
            return True
        if cmd == "profile_del":
            name = d.get("name")
            if (self.cfg.get("rotor_profiles") or {}).pop(name, None) is not None:
                if self.cfg.get("rotor_profile") == name:
                    self.cfg["rotor_profile"] = ""
                self.save_config()
                self.broadcast_state()
            return True
        return False

    # ---------- commandes de Home Assistant ----------
    def on_ha_command(self, key, p):
        who = "Home Assistant"
        if key == "wind/input":
            if self.state["wind"].get("source") != "ha":
                return
            try:
                d = json.loads(p)
                sp = float(d["speed"])
                gu = float(d.get("gust", sp))
                di = d.get("dir")
                di = None if di in (None, "", "unknown", "unavailable") else round(float(di)) % 360
            except Exception:
                self.tlog("ha", "info", f"Données de vent invalides : {p[:80]}", blocked=True)
                return
            self.weather.update(speed=round(sp), gust=round(gu), dir=di, fetched=time.time(), error="",
                                simulated=False, time="Home Assistant")
            self.wind_evaluate()
            self.broadcast_state()
            return
        self.tlog("ha", "rx", f"{key} = {p}")
        try:
            if key == "cible":
                self.request_move("ha", float(p), peer=who)
            elif key == "mode":
                m = MODE_FROM_LABEL.get(p)
                if m:
                    self.set_mode(m, who=who)
            elif key == "preset":
                for pr in self.state["presets"]:
                    if pr["name"] == p:
                        self.request_move("ha", pr["az"], peer=who, label=pr["name"])
                        break
            elif key == "grid":
                g = p.strip().upper()
                if not g:
                    pass
                elif not valid_grid(g):
                    self.tlog("ha", "info", f"Grid invalide : {g}", blocked=True)
                elif not valid_grid(self.cfg.get("grid")):
                    self.tlog("ha", "info", "Grid de la station non défini", blocked=True)
                else:
                    b, _ = grid_bearing(self.cfg["grid"], g)
                    ok, _ = self.request_move("ha", b, peer=who, label=g)
                    if ok:
                        self.state["history"] = ([g] + [h for h in self.state["history"] if h != g])[:12]
                        self.save_state()
            elif key in ("operation", "bloquer_virtuel", "protection_vent"):
                on = p.upper() in ("ON", "1", "TRUE")
                if key == "protection_vent":
                    self.state["wind"]["enabled"] = on
                    self.wind_evaluate()
                else:
                    self.state["operating" if key == "operation" else "block_virtual"] = on
                names = {"operation": ("EN OPÉRATION", "HORS OPÉRATION"),
                         "bloquer_virtuel": ("Port virtuel BLOQUÉ", "Port virtuel débloqué"),
                         "protection_vent": ("Protection vent active", "Protection vent DÉSACTIVÉE")}
                self.tlog("ha", "info", names[key][0 if on else 1], peer=who)
                self.save_state()
            elif key == "arret_urgence":
                self.emergency_stop("ha", who)
            elif key == "rearmer":
                self.rearm(who)
            elif key == "stop":
                self.request_stop("ha", who)
            elif key == "repos":
                az = self.rest_az()
                self.request_move("ha", az, peer=who, label=f"Repos ({round(az)}°)")
            elif key == "update" and p.strip().lower() == "install":
                asyncio.ensure_future(self.install_update(who, self._noop_toast))
            elif key == "ignorer_vent":
                ok, reason = self.wind_override(15, who)
                if not ok:
                    self.tlog("ha", "info", reason, blocked=True)
        except (ValueError, TypeError) as e:
            self.tlog("ha", "info", f"Commande invalide ({key}) : {e}", blocked=True)
        self.ha.last.pop(key, None)  # renvoie l'état réel à HA (ex. commande refusée)
        self.broadcast_state()

    @staticmethod
    async def _noop_toast(*a, **k):
        pass

    # ---------- sauvegarde / restauration (HTTP) ----------
    async def api_backup(self, request):
        data = await request.post()
        pw = str(data.get("password", ""))
        try:
            self.users()
            payload = backup.make_payload(json.loads(json.dumps(self.cfg)), json.loads(json.dumps(self.state)), VERSION)
            blob = await self.loop.run_in_executor(None, backup.encrypt, payload, pw)
        except backup.BackupError as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)
        self.tlog("web", "info", "💾 Sauvegarde des réglages téléchargée", peer=f"{request.get('user')}@{request.remote}")
        name = backup.file_name(self.cfg)
        return web.Response(body=blob, content_type="application/octet-stream",
                            headers={"Content-Disposition": f'attachment; filename="{name}"'})

    async def api_restore(self, request):
        data = await request.post()
        f = data.get("file")
        pw = str(data.get("password", ""))
        if f is None or not hasattr(f, "file"):
            return web.json_response({"ok": False, "error": "Choisis un fichier .rwbackup"}, status=400)
        blob = f.file.read()
        try:
            payload = await self.loop.run_in_executor(None, backup.decrypt, blob, pw)
        except backup.BackupError as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)
        if data.get("action") != "apply":
            return web.json_response({"ok": True, "summary": backup.summary(payload)})
        who = f"{request.get('user')}@{request.remote}"
        self.request_stop("system", why="restauration")
        old = await self.loop.run_in_executor(None, backup.apply, payload, self.config_path)
        self.tlog("web", "info", f"💾 Réglages restaurés depuis une sauvegarde du {payload.get('created')} — redémarrage", peer=who)
        self.broadcast({"type": "system", "action": "restart"})
        # Le service redémarre (systemd : Restart=always) et relit les réglages restaurés
        self.loop.call_later(1.5, os._exit, 0)
        return web.json_response({"ok": True, "restarting": True, "old": old})

    # ---------- commandes de la page web ----------
    async def on_ws_cmd(self, d, ip, ws):
        cmd = d.get("cmd")

        async def toast(text, level="warn"):
            await self._safe_send(ws, {"type": "toast", "level": level, "text": text})

        if await self.track_cmd(cmd, d, ip, ws, toast):
            return
        if await self.satlist_cmd(cmd, d, ip, ws, toast):
            return
        if await self.ctrl_cmd(cmd, d, ip, ws, toast):
            return
        if await self.updater_cmd(cmd, d, ip, ws, toast):
            return
        user = self.ws_users.get(ws, "?")
        if cmd == "lookup":
            q = str(d.get("q", "")).strip()[:60]
            if not q:
                return
            res = await self.lookup.search(q, self.user_prefs(user)["lang"])
            await self._safe_send(ws, res)
            return
        if cmd == "lookup_save":
            c = self.lookup.cfg()
            if d.get("source") in ("hamqth", "qrz", "both", "qrz_first", "prefix"):
                c["source"] = d["source"]
            for k in ("hamqth_user", "qrz_user"):
                if k in d:
                    c[k] = str(d[k]).strip()
            for k in ("hamqth_pass", "qrz_pass"):
                if d.get(k):
                    c[k] = str(d[k])
                if d.get("clear_" + k):
                    c[k] = ""
            self.lookup.hamqth_sid = (None, 0)
            self.lookup.qrz_key = (None, 0)
            self.lookup.cache.clear()
            self.save_config()
            self.broadcast_state()
            await toast("Recherche d'indicatifs enregistrée", "ok")
            return
        if cmd == "prefs_save":
            p = self.user_prefs(user)
            if d.get("lang") in ("fr", "en"):
                p["lang"] = d["lang"]
            if d.get("device") in ("desktop", "mobile") and isinstance(d.get("layout"), list):
                p["layout"][d["device"]] = [
                    {"id": str(m.get("id", ""))[:20], "size": m.get("size") if m.get("size") in ("full", "half", "third") else "half",
                     "variant": str(m.get("variant") or "")[:12], "on": bool(m.get("on", True))}
                    for m in d["layout"][:30] if isinstance(m, dict)]
            if d.get("reset") in ("desktop", "mobile"):
                p["layout"].pop(d["reset"], None)
            self.save_state()
            await self._safe_send(ws, {"type": "prefs", "prefs": p})
            return
        if cmd == "system":
            await self.system_cmd(d.get("action"), ip, toast)
            return
        if cmd == "power_park":
            self.cfg["power_park"] = bool(d.get("value"))
            self.save_config()
            self.broadcast_state()
            return
        if await self.auto_cmd(cmd, d, ip, toast):
            return
        if await self.rotor_cmd(cmd, d, ip, toast):
            return
        if cmd == "mqtt_save":
            m = dict(self.cfg.get("mqtt") or {})
            try:
                m.update(enabled=bool(d.get("enabled")), host=str(d.get("host", "")).strip(),
                         port=int(d.get("port") or 1883), username=str(d.get("username", "")).strip(),
                         discovery_prefix=str(d.get("discovery_prefix") or "homeassistant").strip())
            except ValueError:
                await toast("Port MQTT invalide")
                return
            if d.get("password"):
                m["password"] = str(d["password"])
            if d.get("clear_password"):
                m["password"] = ""
            self.cfg["mqtt"] = m
            self.save_config()
            await self.loop.run_in_executor(None, self.ha.restart)
            self.tlog("web", "info", f"Home Assistant (MQTT) : {'activé — ' + m['host'] if m['enabled'] else 'désactivé'}", peer=ip)
            self.broadcast_state()
            await toast("Réglages Home Assistant enregistrés — connexion en cours…" if m["enabled"] else
                        "Intégration Home Assistant désactivée", "ok")
            return
        if cmd == "goto":
            ok, reason = self.request_move("web", float(d["az"]), d.get("el"), peer=ip,
                                           label=d.get("label", ""))
            if ok and d.get("grid") and valid_grid(d["grid"]):
                g = d["grid"].upper()
                hist = [h for h in self.state["history"] if h != g]
                self.state["history"] = ([g] + hist)[:12]
                self.save_state()
                self.broadcast_state()
            if not ok:
                await toast(f"Refusé : {reason}")
        elif cmd == "stop":
            self.request_stop("web", ip)
        elif cmd == "manual":
            if d.get("dir") in ("R", "L", "U", "D"):
                ok, reason = self.request_manual("web", d["dir"], ip)
                if not ok:
                    await toast(f"Refusé : {reason}")
        elif cmd == "manual_keep":
            if self.manual_deadline:
                self.manual_deadline = time.time() + 1.0
        elif cmd == "manual_end":
            if self.manual_deadline:
                self.request_stop("web", ip)
        elif cmd == "estop":
            self.emergency_stop("web", ip)
        elif cmd == "rearm":
            self.rearm(ip)
        elif cmd == "set":
            key, val = d.get("key"), d.get("value")
            if key in ("operating", "block_virtual"):
                self.state[key] = bool(val)
            elif key == "wsjtx_path" and val in ("short", "long"):
                self.state[key] = val
                self._wsjtx_key = None
            else:
                return
            labels = {"operating": ("EN OPÉRATION", "HORS OPÉRATION"),
                      "block_virtual": ("Port virtuel BLOQUÉ", "Port virtuel débloqué")}
            if key in labels:
                self.tlog("web", "info", labels[key][0] if val else labels[key][1], peer=ip)
            self.save_state()
            self.broadcast_state()
        elif cmd == "preset_add":
            name = str(d.get("name", "")).strip()[:24]
            az = int(round(float(d.get("az", 0)))) % 360
            if name:
                self.state["presets"].append({"name": name, "az": az})
                self.save_state()
                self.broadcast_state()
        elif cmd == "preset_del":
            i = int(d.get("index", -1))
            if 0 <= i < len(self.state["presets"]):
                self.state["presets"].pop(i)
                self.save_state()
                self.broadcast_state()
        elif cmd == "history_clear":
            self.state["history"] = []
            self.save_state()
            self.broadcast_state()
        elif cmd == "wsjtx_point":
            if self.wsjtx.get("bearing") is not None:
                ok, reason = self.request_move("web", self.wsjtx["bearing"], peer=ip,
                                               label=f"{self.wsjtx['dx_call']} {self.wsjtx['dx_grid']}")
                if not ok:
                    await toast(f"Refusé : {reason}")
        elif cmd == "settings":
            call = str(d.get("callsign", "")).strip().upper()[:12]
            grid = str(d.get("grid", "")).strip().upper()
            if grid and not valid_grid(grid):
                await toast("Grid invalide (ex. FN46 ou FN46lw)")
                return
            tzname = str(d.get("timezone", "")).strip() or self.cfg.get("timezone")
            try:
                from zoneinfo import ZoneInfo
                ZoneInfo(tzname)
            except Exception:
                await toast(f"Fuseau horaire inconnu : {tzname}")
                return
            self.cfg["timezone"] = tzname
            if d.get("lang") in ("fr", "en"):
                self.cfg["lang"] = d["lang"]
            self.cfg["callsign"] = call
            self.cfg["grid"] = grid
            self.save_config()
            self._wsjtx_key = None
            self.tlog("web", "info", f"Réglages : {call} {grid}", peer=ip)
            self.broadcast_state()
            await toast("Réglages enregistrés", "ok")

    # ---------- web / authentification ----------
    PUBLIC = {"/login", "/manifest.webmanifest", "/sw.js", "/icon-192.png", "/icon-512.png", "/i18n-en.json",
              "/apple-touch-icon.png", "/favicon.png", "/ha/rotorweb-compass-card.js",
              "/favicon.svg", "/logo.svg", "/wordmark.svg", "/logo-horizontal.svg", "/icon-maskable-192.png", "/icon-maskable-512.png"}

    def current_user(self, request):
        return auth.check_token(self.cfg["secret"], self.users(), request.cookies.get("rw_session", ""))

    @web.middleware
    async def auth_mw(self, request, handler):
        if request.path in self.PUBLIC or self.no_auth:
            request["user"] = "test" if self.no_auth else None
            return await handler(request)
        user = self.current_user(request)
        if user:
            request["user"] = user
            return await handler(request)
        if request.path == "/ws" or request.path.startswith("/api/"):
            raise web.HTTPUnauthorized()
        raise web.HTTPFound("/login")

    async def index(self, request):
        return web.FileResponse(BASE_DIR / "static" / "index.html",
                                headers={"Cache-Control": "no-cache"})

    async def static_file(self, request):
        name = request.path.lstrip("/").replace("ha/", "", 1)
        types = {"manifest.webmanifest": "application/manifest+json", "sw.js": "text/javascript",
                 "i18n-en.json": "application/json",
                 "rotorweb-compass-card.js": "text/javascript",
                 "favicon.svg": "image/svg+xml", "logo.svg": "image/svg+xml", "wordmark.svg": "image/svg+xml",
                 "logo-horizontal.svg": "image/svg+xml"}
        resp = web.FileResponse(BASE_DIR / "static" / name, headers={"Cache-Control": "no-cache"})
        if name in types:
            resp.content_type = types[name]
        return resp

    async def api_me(self, request):
        return web.json_response({"user": request.get("user")})

    @staticmethod
    def _req_lang(request):
        c = request.cookies.get("rw_lang")
        if c in ("fr", "en"):
            return c
        al = (request.headers.get("Accept-Language") or "").lower()
        return "en" if al.startswith("en") else "fr"

    def _login_page(self, error="", lang="fr"):
        title = self.cfg["callsign"] or "RotorWeb"
        note = ""
        if not self.users():
            note = tr("Aucun compte n'existe encore. Sur le Raspberry Pi, lance :", lang) + \
                "<br><code>sudo /opt/rotorweb/users.sh add NOM</code>"
        html = LOGIN_HTML
        for k in ("Connexion", "Contrôle du rotor", "Utilisateur", "Mot de passe", "Se connecter"):
            html = html.replace("{{" + k + "}}", tr(k, lang))
        other = "en" if lang == "fr" else "fr"
        html = (html.replace("{{TITLE}}", title).replace("{{ERR}}", tr(error, lang))
                .replace("{{NOTE}}", note).replace("{{LANG}}", lang).replace("{{OTHER}}", other)
                .replace("{{OTHERNAME}}", "English" if other == "en" else "Français"))
        return web.Response(text=html, content_type="text/html")

    async def login_get(self, request):
        if self.current_user(request):
            raise web.HTTPFound("/")
        lang = request.query.get("lang")
        if lang in ("fr", "en"):
            resp = self._login_page(lang=lang)
            resp.set_cookie("rw_lang", lang, max_age=365 * 86400, samesite="Lax")
            return resp
        return self._login_page(lang=self._req_lang(request))

    async def login_post(self, request):
        ip = request.remote or "?"
        fails, until = self.login_fails.get(ip, (0, 0))
        lang = self._req_lang(request)
        if until > time.time():
            return self._login_page(f"Trop d'essais. Réessaie dans {int(until - time.time())} s.", lang)
        data = await request.post()
        user = str(data.get("username", "")).strip().lower()
        pw = str(data.get("password", ""))
        stored = self.users().get(user)
        if stored and await asyncio.get_running_loop().run_in_executor(None, auth.verify_password, pw, stored):
            self.login_fails.pop(ip, None)
            self.tlog("web", "info", f"Connexion de {user}", peer=ip)
            if "lang" not in self.state.get("user_prefs", {}).get(user, {}) and request.cookies.get("rw_lang"):
                self.user_prefs(user)["lang"] = lang
                self.save_state()
            resp = web.HTTPFound("/")
            resp.set_cookie("rw_session", auth.make_token(self.cfg["secret"], user, stored),
                            max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="Lax",
                            secure=request.secure)
            raise resp
        fails += 1
        self.login_fails[ip] = (fails, time.time() + 120 if fails >= 5 else 0)
        self.tlog("system", "info", f"Échec de connexion ({user or '?'})", blocked=True, peer=ip)
        await asyncio.sleep(1.0)
        return self._login_page("Utilisateur ou mot de passe incorrect", lang)

    async def logout(self, request):
        resp = web.HTTPFound("/login")
        resp.del_cookie("rw_session")
        raise resp

    async def ws_handler(self, request):
        ws = web.WebSocketResponse(heartbeat=15)
        await ws.prepare(request)
        user = request.get("user") or "?"
        ip = f"{user}@{request.remote or '?'}"
        self.websockets.add(ws)
        self.ws_users[ws] = user
        self.clients["web"] += 1
        await ws.send_json(self.public_state())
        await ws.send_json({"type": "whoami", "user": user})
        await ws.send_json({"type": "prefs", "prefs": self.user_prefs(user)})
        await ws.send_json({"type": "log_backlog", "entries": list(self.logbuf)})
        self.broadcast_state()
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        await self.on_ws_cmd(json.loads(msg.data), ip, ws)
                    except Exception as e:
                        log.exception("Commande web")
                        await self._safe_send(ws, {"type": "toast", "level": "error", "text": str(e)})
        finally:
            self.websockets.discard(ws)
            self.ws_users.pop(ws, None)
            self.clients["web"] -= 1
            if self.manual_deadline:
                self.request_stop("web", ip, why="page web fermée")
            self.broadcast_state()
        return ws


LOGIN_HTML = """<!doctype html><html lang="{{LANG}}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0e1319"><link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/apple-touch-icon.png"><link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="icon" href="/favicon.png" sizes="32x32">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes">
<title>{{TITLE}} · RotorWeb — {{Connexion}}</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0e1319;color:#e6edf3;
font-family:system-ui,sans-serif}form{box-sizing:border-box;background:#161e28;padding:28px;border-radius:16px;width:min(340px,90vw);
border:1px solid #2a3747}img{width:72px;height:72px;display:block;margin:0 auto 10px}img.wm{width:auto;height:44px;margin:-8px auto 6px}
h1{font-size:20px;margin:0 0 4px;text-align:center}p{color:#8b9bb0;margin:0 0 18px;text-align:center}
label{display:block;font-size:13px;color:#8b9bb0;margin:0 0 4px}
input,button{width:100%;box-sizing:border-box;padding:13px;border-radius:10px;font-size:16px}
input{background:#0e1319;border:1px solid #2a3747;color:#e6edf3;margin-bottom:14px}
input:focus{outline:2px solid #2f81f7;outline-offset:-1px}
button{background:#2f81f7;color:#fff;border:0;font-weight:600;cursor:pointer}
.err{color:#e5484d;min-height:1.2em;margin:12px 0 0}.note{font-size:13px;margin-top:12px}
code{background:#0e1319;padding:2px 6px;border-radius:4px;color:#e6edf3}
.lng{display:block;text-align:center;margin-top:14px;color:#8b9bb0;font-size:13px}</style>
</head><body><form method="post" action="/login">
<img src="/logo.svg" alt=""><img class="wm" src="/wordmark.svg" alt="RotorWeb"><h1>{{TITLE}}</h1><p>{{Contrôle du rotor}}</p>
<label for="u">{{Utilisateur}}</label>
<input id="u" name="username" autocomplete="username" autocapitalize="none" spellcheck="false" required autofocus>
<label for="p">{{Mot de passe}}</label>
<input id="p" type="password" name="password" autocomplete="current-password" required>
<button>{{Se connecter}}</button><p class="err">{{ERR}}</p><p class="note">{{NOTE}}</p>
<a class="lng" href="/login?lang={{OTHER}}">{{OTHERNAME}}</a></form></body></html>"""


async def main_async(args):
    ctrl = Controller(args.config, simulate=args.simulate)
    ctrl.no_auth = args.no_auth
    await ctrl.start()
    app = web.Application(middlewares=[ctrl.auth_mw], client_max_size=8 * 1024 * 1024)
    app.router.add_get("/", ctrl.index)
    app.router.add_get("/ws", ctrl.ws_handler)
    app.router.add_get("/login", ctrl.login_get)
    app.router.add_post("/login", ctrl.login_post)
    app.router.add_get("/logout", ctrl.logout)
    app.router.add_get("/api/me", ctrl.api_me)
    app.router.add_post("/api/backup", ctrl.api_backup)
    app.router.add_post("/api/restore", ctrl.api_restore)
    for f in ("manifest.webmanifest", "sw.js", "icon-192.png", "icon-512.png", "i18n-en.json",
              "apple-touch-icon.png", "favicon.png", "favicon.svg", "logo.svg", "wordmark.svg", "logo-horizontal.svg",
              "icon-maskable-192.png", "icon-maskable-512.png"):
        app.router.add_get("/" + f, ctrl.static_file)
    app.router.add_get("/ha/rotorweb-compass-card.js", ctrl.static_file)
    runner = web.AppRunner(app)
    await runner.setup()
    port = args.port or int(ctrl.cfg["web_port"])
    ssl_ctx = None
    if ctrl.cfg.get("https_cert") and ctrl.cfg.get("https_key"):
        import ssl
        ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_ctx.load_cert_chain(ctrl.cfg["https_cert"], ctrl.cfg["https_key"])
    await web.TCPSite(runner, "0.0.0.0", port, ssl_context=ssl_ctx).start()
    log.info("Page web : %s://0.0.0.0:%s", "https" if ssl_ctx else "http", port)
    if not ctrl.users() and not ctrl.no_auth:
        log.warning("Aucun compte ! Crée-en un :  python -m rotorweb.auth add NOM --config %s", args.config)
    await asyncio.Event().wait()


def main():
    ap = argparse.ArgumentParser(description="RotorWeb — contrôle de rotor GS-232 / K3NG")
    ap.add_argument("--config", default=str(BASE_DIR.parent / "config.json"))
    ap.add_argument("--simulate", action="store_true", help="rotor simulé, sans matériel")
    ap.add_argument("--port", type=int, help="port web (remplace la config)")
    ap.add_argument("--no-auth", action="store_true", help="désactive la connexion (TESTS SEULEMENT)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
