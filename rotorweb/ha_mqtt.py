# -*- coding: utf-8 -*-
"""
RotorWeb — intégration Home Assistant par MQTT (découverte automatique).

Les entités apparaissent seules dans Home Assistant, regroupées sous un appareil
« RotorWeb ». Chaque entité porte l'attribut rotorweb_role, utilisé par la carte
boussole pour se retrouver sans dépendre des noms d'entités.
"""
import json
import logging
import re
import socket
import threading
import time
import uuid
from datetime import datetime, timezone

try:
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover
    mqtt = None

from rotorweb.geo import valid_grid

log = logging.getLogger("rotorweb")

MODE_LABELS = {"manual": "Manuel", "schedule": "Horaire", "track": "Suivi"}
MODE_FROM_LABEL = {"Manuel": "manual", "Manual": "manual", "Horaire": "schedule", "Schedule": "schedule",
                   "Suivi": "track", "Tracking": "track"}
NO_PRESET = "—"
EVENT_TYPES = ["arrivee", "repos", "alerte", "verrou_vent", "verrou_leve", "contournement", "passage_sat", "mise_a_jour", "info"]


def event_type_for(subject):
    s = subject.lower()
    if "ignoré" in s:
        return "contournement"
    if "verrou vent activé" in s or "fin du contournement" in s:
        return "verrou_vent"
    if "verrou vent levé" in s:
        return "verrou_leve"
    if "alerte" in s or "non démarrée" in s or "impossible" in s:
        return "alerte"
    if "repos" in s:
        return "repos"
    if s.startswith("✔"):
        return "arrivee"
    return "info"


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class HABridge:
    def __init__(self, ctrl):
        self.ctrl = ctrl
        self.client = None
        self.connected = False
        self.error = ""
        self.last = {}
        self._disc_sig = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ réglages
    def cfg(self):
        return self.ctrl.cfg.get("mqtt") or {}

    def node(self):
        n = self.cfg().get("node_id") or ""
        if not n:
            call = re.sub(r"[^a-z0-9]", "", (self.ctrl.cfg.get("callsign") or "").lower())
            n = f"rotorweb_{call}" if call else "rotorweb"
        return re.sub(r"[^a-zA-Z0-9_-]", "_", n)

    def base(self):
        return f"{self.cfg().get('base_topic') or 'rotorweb'}/{self.node()}"

    def status(self):
        c = self.cfg()
        return {"enabled": bool(c.get("enabled")), "host": c.get("host", ""), "port": c.get("port", 1883),
                "username": c.get("username", ""), "has_password": bool(c.get("password")),
                "discovery_prefix": c.get("discovery_prefix", "homeassistant"),
                "node": self.node(), "connected": self.connected, "error": self.error,
                "available": mqtt is not None}

    # ------------------------------------------------------------ connexion
    def start(self):
        c = self.cfg()
        if not c.get("enabled") or not c.get("host"):
            return
        if mqtt is None:
            self.error = "Module paho-mqtt absent (relance update.sh)"
            return
        self.error = ""
        cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id=f"{self.node()}-{uuid.uuid4().hex[:6]}")
        if c.get("username"):
            cl.username_pw_set(c["username"], c.get("password") or None)
        cl.will_set(f"{self.base()}/availability", "offline", qos=1, retain=True)
        cl.on_connect = self._on_connect
        cl.on_disconnect = self._on_disconnect
        cl.on_message = self._on_message
        cl.reconnect_delay_set(1, 30)
        self.client = cl
        try:
            cl.connect_async(c["host"], int(c.get("port") or 1883), keepalive=30)
            cl.loop_start()
        except Exception as e:
            self.error = str(e)
            self.ctrl.tlog("ha", "info", f"Connexion MQTT impossible : {e}", blocked=True)

    def stop(self):
        cl, self.client = self.client, None
        if cl:
            try:
                cl.publish(f"{self.base()}/availability", "offline", qos=1, retain=True)
                cl.disconnect()
                cl.loop_stop()
            except Exception:
                pass
        self.connected = False
        self.last = {}
        self._disc_sig = None

    def restart(self):
        self.stop()
        self.start()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", False):
            self.connected = False
            self.error = f"Refusé par le broker : {reason_code}"
            self.ctrl.tlog("ha", "info", f"MQTT : {self.error}", blocked=True)
            self.ctrl._threadsafe(self.ctrl.broadcast_state)
            return
        self.connected = True
        self.error = ""
        b = self.base()
        prefix = self.cfg().get("discovery_prefix") or "homeassistant"
        client.subscribe([(f"{b}/+/set", 1), (f"{b}/wind/input", 1), (f"{prefix}/status", 1)])
        client.publish(f"{b}/availability", "online", qos=1, retain=True)
        self.ctrl.tlog("ha", "info", f"Connecté au broker MQTT {self.cfg().get('host')} ({b})")
        self.ctrl._threadsafe(self.full_sync)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        if self.connected:
            self.ctrl.tlog("ha", "info", f"MQTT déconnecté ({reason_code})", blocked=True)
        self.connected = False
        self.last = {}
        self.ctrl._threadsafe(self.ctrl.broadcast_state)

    def _on_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8", "replace").strip()
        prefix = self.cfg().get("discovery_prefix") or "homeassistant"
        if msg.topic == f"{prefix}/status":
            if payload == "online":  # Home Assistant vient de redémarrer
                self.ctrl._threadsafe(self.full_sync)
            return
        key = msg.topic[len(self.base()) + 1:]
        key = key[:-4] if key.endswith("/set") else key
        self.ctrl._threadsafe(self.ctrl.on_ha_command, key, payload)

    def _pub(self, topic, payload, retain=True):
        cl = self.client
        if cl and self.connected:
            if not isinstance(payload, str):
                payload = json.dumps(payload, ensure_ascii=False)
            cl.publish(topic, payload, qos=1, retain=retain)

    # ------------------------------------------------------------ découverte
    def _entities(self):
        """(composant, clé, nom, options supplémentaires)."""
        ctrl = self.ctrl
        t = ctrl.tr
        b = self.base()
        presets = [NO_PRESET] + [p["name"] for p in ctrl.state.get("presets", [])]
        ents = [
            ("sensor", "azimut", "Azimut", {"unit_of_measurement": "°", "state_class": "measurement",
                                             "icon": "mdi:compass", "suggested_display_precision": 0}),
            ("sensor", "destination", "Destination", {"unit_of_measurement": "°", "icon": "mdi:target"}),
            ("sensor", "plage", "Plage horaire", {"icon": "mdi:calendar-clock"}),
            ("sensor", "dx", "Station DX", {"icon": "mdi:radio-tower"}),
            ("sensor", "suivi", "Suivi", {"icon": "mdi:satellite-variant"}),
            ("sensor", "prochain_passage", "Prochain passage", {"icon": "mdi:orbit"}),
            ("sensor", "passage_sat", "Prochain bon passage satellite", {"icon": "mdi:satellite-uplink"}),
            ("sensor", "passage_sat_heure", "Heure du prochain bon passage", {"device_class": "timestamp",
                                                                           "icon": "mdi:clock-start"}),
            ("sensor", "vent", "Vent", {"unit_of_measurement": "km/h", "device_class": "wind_speed",
                                        "state_class": "measurement"}),
            ("sensor", "rafales", "Rafales", {"unit_of_measurement": "km/h", "device_class": "wind_speed",
                                              "state_class": "measurement"}),
            ("number", "cible", "Azimut cible", {"min": 0, "max": 359, "step": 1, "mode": "box",
                                                 "unit_of_measurement": "°", "icon": "mdi:crosshairs-gps",
                                                 "command_topic": f"{b}/cible/set"}),
            ("select", "mode", "Mode", {"options": [t(v) for v in MODE_LABELS.values()], "icon": "mdi:auto-mode",
                                        "command_topic": f"{b}/mode/set"}),
            ("select", "preset", "Préréglage", {"options": presets, "icon": "mdi:star",
                                                "command_topic": f"{b}/preset/set"}),
            ("text", "grid", "Pointer vers grid", {"min": 0, "max": 8, "icon": "mdi:grid",
                                                   "command_topic": f"{b}/grid/set"}),
            ("switch", "operation", "En opération", {"icon": "mdi:power", "command_topic": f"{b}/operation/set"}),
            ("switch", "bloquer_virtuel", "Bloquer port virtuel", {"icon": "mdi:lan-disconnect",
                                                                   "command_topic": f"{b}/bloquer_virtuel/set"}),
            ("switch", "protection_vent", "Protection vent", {"icon": "mdi:weather-windy",
                                                              "command_topic": f"{b}/protection_vent/set"}),
            ("button", "arret_urgence", "Arrêt d'urgence", {"icon": "mdi:alert-octagon",
                                                           "command_topic": f"{b}/arret_urgence/set"}),
            ("button", "rearmer", "Réarmer", {"icon": "mdi:restart", "command_topic": f"{b}/rearmer/set"}),
            ("button", "stop", "STOP", {"icon": "mdi:stop", "command_topic": f"{b}/stop/set"}),
            ("button", "repos", "Repos", {"icon": "mdi:home-export-outline", "command_topic": f"{b}/repos/set"}),
            ("button", "ignorer_vent", "Ignorer verrou vent 15 min", {"icon": "mdi:weather-windy-variant",
                                                                     "command_topic": f"{b}/ignorer_vent/set"}),
            ("binary_sensor", "k3ng", "Contrôleur connecté", {"device_class": "connectivity"}),
            ("binary_sensor", "verrou_vent", "Verrou vent", {"device_class": "problem", "icon": "mdi:weather-windy"}),
            ("binary_sensor", "urgence", "Arrêt d'urgence actif", {"device_class": "problem",
                                                                   "icon": "mdi:alert-octagon"}),
            ("event", "notification", "Notifications", {"event_types": EVENT_TYPES, "icon": "mdi:bell-ring"}),
            ("update", "update", "Mise à jour RotorWeb", {"command_topic": f"{b}/update/set", "payload_install": "install",
                                                         "entity_category": "config", "title": "RotorWeb"}),
        ]
        if ctrl.cfg.get("elevation"):
            ents.insert(1, ("sensor", "elevation", "Élévation", {"unit_of_measurement": "°",
                                                                  "state_class": "measurement"}))
        return [(c, k, t(n), x) for c, k, n, x in ents]

    def publish_discovery(self):
        ctrl = self.ctrl
        prefix = self.cfg().get("discovery_prefix") or "homeassistant"
        b = self.base()
        node = self.node()
        call = ctrl.cfg.get("callsign") or ""
        device = {"identifiers": [node], "name": f"RotorWeb {call}".strip(), "manufacturer": "RotorWeb",
                  "model": ctrl.tr("Contrôleur de rotor"), "sw_version": ctrl.version,
                  "configuration_url": f"{'https' if ctrl.cfg.get('https_cert') else 'http'}://{local_ip()}:{ctrl.cfg['web_port']}"}
        ents = self._entities()
        sig = json.dumps([e[:2] + (e[3].get("options"),) for e in ents] + [device["name"]], ensure_ascii=False)
        # Entités retirées (ex. élévation désactivée) : on vide leur config
        if self._disc_sig:
            old = {tuple(x[:2]) for x in json.loads(self._disc_sig)[:-1]}
            for comp, key in old - {(e[0], e[1]) for e in ents}:
                self._pub(f"{prefix}/{comp}/{node}/{key}/config", "")
        for comp, key, name, extra in ents:
            cfg = {"name": name, "unique_id": f"{node}_{key}", "has_entity_name": True,
                   "availability_topic": f"{b}/availability", "device": device,
                   "json_attributes_topic": f"{b}/{key}/attr", **extra}
            if comp != "button":
                cfg["state_topic"] = f"{b}/{key}/state"
            if comp in ("switch", "binary_sensor"):
                cfg.update(payload_on="ON", payload_off="OFF")
            self._pub(f"{prefix}/{comp}/{node}/{key}/config", cfg)
            self._pub(f"{b}/{key}/attr", {"rotorweb_role": key, "rotorweb_node": node, **self._extra_attr(key)})
        self._disc_sig = sig

    # ------------------------------------------------------------ états
    def _values(self):
        c = self.ctrl
        w = c.weather or {}
        sc = c.sched_info or {}
        az = c.az
        t = c.tr
        gp = c.next_good_pass() if hasattr(c, "next_good_pass") else None
        vals = {
            "azimut": "None" if az is None else str(int(az) % 360),
            "destination": "None" if c.target_az is None else str(int(round(c.target_az)) % 360),
            "plage": t(f"{sc.get('active')} (jusqu'à {sc.get('until')})" if sc.get("active")
                       else (f"Prochaine : {sc.get('next')} · {sc.get('next_at')}" if sc.get("next") else "Aucune"))[:250],
            "dx": (f"{c.wsjtx.get('dx_call')} {c.wsjtx.get('dx_grid') or ''}".strip() if c.wsjtx.get("dx_call") else t("Aucune")),
            "vent": "None" if w.get("speed") is None else str(w["speed"]),
            "rafales": "None" if w.get("gust") is None else str(w["gust"]),
            "cible": str(int(round(c.target_az if c.target_az is not None else (az or 0))) % 360),
            "mode": t(MODE_LABELS.get(c.state.get("mode"), "Manuel")),
            "preset": NO_PRESET,
            "grid": (c.state.get("history") or [""])[0] if c.state.get("history") else "",
            "suivi": t(self._suivi(c)),
            "prochain_passage": t(self._next_pass(c)),
            "passage_sat": (f"{gp['display']} · {c.fmt_time(gp['aos'])} · max {gp['max_el']:.0f}°" if gp else t("Aucun"))[:250],
            "passage_sat_heure": (datetime.fromtimestamp(gp["aos"], timezone.utc).isoformat() if gp else "None"),
            "operation": "ON" if c.state.get("operating") else "OFF",
            "bloquer_virtuel": "ON" if c.state.get("block_virtual") else "OFF",
            "protection_vent": "ON" if c.state.get("wind", {}).get("enabled") else "OFF",
            "k3ng": "ON" if c.connected else "OFF",
            "verrou_vent": "ON" if c.wind_locked else "OFF",
            "urgence": "ON" if c.state.get("estop") else "OFF",
            "update": self._update_state(c),
        }
        if c.cfg.get("elevation"):
            vals["elevation"] = "None" if c.el is None else str(int(c.el))
        return vals

    @staticmethod
    def _update_state(c):
        if not hasattr(c, "upd"):
            return json.dumps({"installed_version": c.version, "latest_version": c.version})
        lt = c.upd.get("latest") or {}
        notes = (lt.get("notes") or {}).get(c.cfg.get("lang", "fr")) or (lt.get("notes") or {}).get("fr", "")
        repo = c.ucfg.get("repo") or ""
        return json.dumps({"installed_version": c.version, "latest_version": lt.get("version") or c.version,
                           "title": "RotorWeb", "release_summary": (notes or "")[:250],
                           "release_url": f"https://github.com/{repo}/releases" if repo else None,
                           "in_progress": bool(c.upd.get("busy"))}, ensure_ascii=False)

    @staticmethod
    def _suivi(c):
        n = c.track_now or {}
        if not n.get("key") or n.get("error"):
            return "Aucun"
        st = "en vue" if n.get("above") else "sous l'horizon"
        return f"{n['name']} · az {n.get('az', 0):.0f}° él {n.get('el', 0):.0f}° ({st})"[:250]

    @staticmethod
    def _next_pass(c):
        nx = (c.track_now or {}).get("next")
        if not nx:
            return "Aucun"
        return f"{nx['name']} · {c.fmt_time(nx['aos'])} · max {nx['max_el']:.0f}°"

    def sync(self):
        """Publie ce qui a changé (appelé à chaque changement d'état)."""
        if not (self.client and self.connected):
            return
        with self._lock:
            ents = self._entities()
            sig = json.dumps([e[:2] + (e[3].get("options"),) for e in ents]
                             + [f"RotorWeb {self.ctrl.cfg.get('callsign') or ''}".strip()], ensure_ascii=False)
            if sig != self._disc_sig:
                self.publish_discovery()
                self.last = {}
            b = self.base()
            for k, v in self._values().items():
                if self.last.get(k) != v:
                    self.last[k] = v
                    self._pub(f"{b}/{k}/state", v)
            extra = self._extra_attr("passage_sat")
            sig_attr = json.dumps(extra, ensure_ascii=False, sort_keys=True)
            if self.last.get("__attr_passage_sat") != sig_attr:
                self.last["__attr_passage_sat"] = sig_attr
                self._pub(f"{b}/passage_sat/attr", {"rotorweb_role": "passage_sat", "rotorweb_node": self.node(), **extra})

    def _extra_attr(self, key):
        """Attributs supplémentaires : la liste des prochains passages pour la carte boussole."""
        if key != "passage_sat" or not hasattr(self.ctrl, "satpasses"):
            return {}
        now = time.time()
        out = []
        for p in self.ctrl.satpasses.get("list", []):
            if p["los"] > now:
                out.append({"name": p["display"], "aos": int(p["aos"]), "los": int(p["los"]), "max_el": round(p["max_el"]),
                            "aos_az": p["aos_az"], "los_az": p["los_az"], "freq": p.get("freq", "")})
            if len(out) >= 8:
                break
        return {"passes": out}

    def full_sync(self):
        self.last = {}
        self._disc_sig = None
        self.sync()
        self.ctrl.broadcast_state()

    def event(self, subject, body, kind=None, title=None):
        if self.client and self.connected:
            self._pub(f"{self.base()}/notification/state",
                      {"event_type": kind or event_type_for(subject), "titre": title or subject,
                       "title": title or subject, "message": body[:900]},
                      retain=False)
