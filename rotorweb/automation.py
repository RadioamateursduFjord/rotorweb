# -*- coding: utf-8 -*-
"""
RotorWeb — automatismes : horaires, protection contre le vent, courriels.

Mélangé (mixin) dans la classe Controller de server.py.
"""
import asyncio
import logging
import smtplib
import ssl
import time
import uuid
from datetime import datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import aiohttp

from rotorweb.geo import angdiff, grid_bearing, grid_to_latlon, valid_grid

log = logging.getLogger("rotorweb")

# Régions prédéfinies : le cap est calculé depuis le grid de la station
REGIONS = [
    ("eu_ouest", "Europe de l'Ouest (Paris)", "JN18"),
    ("eu_est", "Europe de l'Est (Moscou)", "KO85"),
    ("afr_ouest", "Afrique de l'Ouest (Dakar)", "IK14"),
    ("afr_sud", "Afrique du Sud (Johannesburg)", "KG33"),
    ("moyen_orient", "Moyen-Orient (Dubaï)", "LL75"),
    ("inde", "Inde (New Delhi)", "ML88"),
    ("chine", "Chine (Pékin)", "OM89"),
    ("japon", "Japon (Tokyo)", "PM95"),
    ("asie_se", "Asie du Sud-Est (Singapour)", "OJ11"),
    ("australie", "Australie (Sydney)", "QF56"),
    ("nz", "Nouvelle-Zélande (Auckland)", "RF73"),
    ("hawaii", "Hawaï (Honolulu)", "BL11"),
    ("alaska", "Alaska (Anchorage)", "BP51"),
    ("usa_ouest", "Ouest américain (Los Angeles)", "DM04"),
    ("mexique", "Mexique / Amérique centrale", "EK09"),
    ("caraibes", "Caraïbes (Porto Rico)", "FK68"),
    ("bresil", "Amérique du Sud – Brésil (São Paulo)", "GG66"),
    ("argentine", "Amérique du Sud – Argentine (Buenos Aires)", "GF05"),
]
REGION_MAP = {k: (n, g) for k, n, g in REGIONS}
JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"


def _hm(s):
    h, m = str(s).split(":")
    return int(h) * 60 + int(m)


class AutomationMixin:
    # ------------------------------------------------------------ init
    def auto_init(self):
        self.weather = {"speed": None, "gust": None, "dir": None, "time": "",
                        "fetched": 0, "error": "", "simulated": False}
        self.wind_locked = False
        self.wind_calm_since = None
        self._last_fetch = 0.0
        self.sched_applied = "__reapply__"
        self.sched_fail_notified = None
        self.pending_confirm = None
        self.sched_info = {}

    def auto_start(self):
        asyncio.create_task(self._scheduler_loop())
        asyncio.create_task(self._weather_loop())

    # ------------------------------------------------------------ heure locale
    def tz(self):
        try:
            return ZoneInfo(self.cfg.get("timezone") or "America/Toronto")
        except Exception:
            return ZoneInfo("UTC")

    def now_local(self):
        return datetime.now(self.tz())

    def fmt_time(self, ts):
        return datetime.fromtimestamp(ts, self.tz()).strftime("%H:%M")

    # ------------------------------------------------------------ régions / cibles
    def regions_public(self):
        g = self.cfg.get("grid")
        out = []
        for key, name, grid in REGIONS:
            b = round(grid_bearing(g, grid)[0]) % 360 if valid_grid(g) else None
            out.append({"key": key, "name": name, "grid": grid, "bearing": b})
        return out

    def resolve_target(self, t):
        """Retourne (azimut, libellé) pour une cible d'horaire."""
        typ, val = t.get("type"), t.get("value")
        if typ == "track":
            name = self.target_name(val) if hasattr(self, "target_name") else val
            return 0.0, f"Suivi {name}"
        if typ == "az":
            az = float(val) % 360
            return az, f"{round(az)}°"
        if typ == "region":
            if val not in REGION_MAP:
                raise ValueError(f"Région inconnue : {val}")
            name, grid = REGION_MAP[val]
        elif typ == "grid":
            if not valid_grid(val):
                raise ValueError(f"Grid invalide : {val}")
            name, grid = str(val).upper(), str(val).upper()
        else:
            raise ValueError("Cible invalide")
        if not valid_grid(self.cfg.get("grid")):
            raise ValueError("Le grid de la station n'est pas défini (⚙ Réglages)")
        b = grid_bearing(self.cfg["grid"], grid)[0] % 360
        return b, f"{name} ({round(b)}°)"

    def target_label(self, t):
        try:
            return self.resolve_target(t)[1]
        except ValueError as e:
            return f"⚠ {e}"

    def rest_az(self):
        r = self.state.get("rest", {})
        d = self.weather.get("dir")
        if r.get("wind_align") and d is not None:
            # Boom de la Yagi dans l'axe du vent = moins de prise au vent.
            # On choisit le sens (face au vent ou dos au vent) le plus proche de la position actuelle.
            cur = (self.az or 0) % 360
            cands = [d % 360, (d + 180) % 360]
            return min(cands, key=lambda c: angdiff(c, cur))
        return float(r.get("az", 0)) % 360

    # ------------------------------------------------------------ horaires
    def schedule_status(self, now):
        """(plage active, début, fin) et (prochaine plage, début)."""
        active, nxt = None, None
        tz = now.tzinfo
        for s in self.state.get("schedules", []):
            if not s.get("enabled", True) or not s.get("days"):
                continue
            try:
                st, en = _hm(s["start"]), _hm(s["end"])
            except Exception:
                continue
            for off in (-1, 0):
                day = (now + timedelta(days=off)).date()
                if day.weekday() not in s["days"]:
                    continue
                a = datetime(day.year, day.month, day.day, st // 60, st % 60, tzinfo=tz)
                b = datetime(day.year, day.month, day.day, en // 60, en % 60, tzinfo=tz)
                if en <= st:
                    b += timedelta(days=1)
                if a <= now < b and active is None:
                    active = (s, a, b)
            for d in range(0, 8):
                day = (now + timedelta(days=d)).date()
                if day.weekday() in s["days"]:
                    a = datetime(day.year, day.month, day.day, st // 60, st % 60, tzinfo=tz)
                    if a > now:
                        if nxt is None or a < nxt[1]:
                            nxt = (s, a)
                        break
        return active, nxt

    def _plage_name(self, s):
        return s.get("name") or self.target_label(s["target"]).split(" (")[0]

    def scheduler_tick(self):
        now = self.now_local()
        act, nxt = self.schedule_status(now)
        info = {"active_id": None, "active": "", "until": "", "next": "", "next_at": ""}
        if act:
            s, a, b = act
            info.update(active_id=s["id"], active=f"{self._plage_name(s)} → {self.target_label(s['target'])}",
                        until=b.strftime("%H:%M"))
        if nxt:
            s, a = nxt
            when = a.strftime("%H:%M") if a.date() == now.date() else f"{JOURS[a.weekday()]} {a.strftime('%H:%M')}"
            info.update(next=self._plage_name(s), next_at=when)
        info["now"] = now.strftime("%H:%M")
        if info != self.sched_info:
            self.sched_info = info
            self.broadcast_state()
        self.check_confirm()

        if self.state.get("mode") != "schedule":
            return
        desired = act[0]["id"] if act else "REST"
        if desired == self.sched_applied:
            return
        if desired == "REST":
            self.sched_track = None
            if self.sched_applied in ("__reapply__", None, "REST"):
                # Entrée en mode Horaire hors plage : on ne bouge pas
                self.sched_applied = "REST"
                return
            az, label, kind, plage = self.rest_az(), f"Repos ({round(self.rest_az())}°)", "rest", "fin de plage"
        else:
            s = act[0]
            if s["target"].get("type") == "track":
                # La plage confie le rotor au moteur de suivi (Lune, satellite…)
                self.sched_track = s["target"]["value"]
                self.sched_applied = desired
                self.track_last_cmd = None
                self.tlog("schedule", "info", f"Plage {s['start']}–{s['end']} : suivi de {self.target_name(self.sched_track)}")
                return
            self.sched_track = None
            try:
                az, label = self.resolve_target(s["target"])
            except ValueError as e:
                if self.sched_fail_notified != desired:
                    self.sched_fail_notified = desired
                    self.tlog("schedule", "info", f"Plage « {self._plage_name(s)} » impossible : {e}", blocked=True)
                    self.send_email(f"⚠ Plage horaire impossible : {self._plage_name(s)}", f"Raison : {e}")
                return
            kind, plage = "schedule", f"{s['start']}–{s['end']}"
        ok, reason = self.request_move("schedule", az, label=label)
        if ok:
            self.sched_applied = desired
            self.sched_fail_notified = None
            self.pending_confirm = {"kind": kind, "az": az, "label": label, "plage": plage, "t": time.time()}
        elif self.sched_fail_notified != desired:
            self.sched_fail_notified = desired
            self.send_email(f"⚠ Plage horaire non démarrée : {label}",
                            f"La plage {plage} n'a pas pu orienter l'antenne vers {label}.\n"
                            f"Raison : {reason}\n\nLe rotor pointera automatiquement dès que ce sera possible "
                            f"pendant la plage.")

    async def _scheduler_loop(self):
        await asyncio.sleep(2)
        while True:
            try:
                self.scheduler_tick()
            except Exception:
                log.exception("Horaires")
            await asyncio.sleep(10)

    def check_confirm(self):
        p = self.pending_confirm
        if not p:
            return
        tol = max(3.0, float(self.cfg.get("arrive_tolerance", 2)) + 1)
        src = "wind" if p["kind"] == "wind_rest" else "schedule"
        if self.az is not None and angdiff(self.az, p["az"]) <= tol:
            self.pending_confirm = None
            self.tlog(src, "info", f"✔ Antenne arrivée : {p['label']} (position {self.az}°)")
            titre = {"schedule": "✔ Antenne dirigée vers", "rest": "✔ Antenne au repos :",
                     "wind_rest": "✔ Antenne au repos (vent) :"}[p["kind"]]
            body = (f"L'antenne est arrivée à destination.\n\n"
                    f"Direction   : {p['label']}\n"
                    f"Position lue: {self.az}°\n"
                    f"Plage       : {p['plage']}\n"
                    f"Arrivée     : {self.now_local().strftime('%H:%M:%S')} "
                    f"({int(time.time() - p['t'])} s de rotation)")
            if p["kind"] == "wind_rest":
                body += f"\n\nMétéo : {self.wind_desc()}"
            self.send_email(f"{titre} {p['label']}", body)
        elif time.time() - p["t"] > float(self.cfg.get("arrival_timeout", 180)):
            self.pending_confirm = None
            self.tlog(src, "info", f"⚠ Antenne NON arrivée : {p['label']} (position {self.az}°)", blocked=True)
            self.send_email(f"⚠ ALERTE : antenne non arrivée — {p['label']}",
                            f"Après {int(self.cfg.get('arrival_timeout', 180))} s, l'antenne n'a pas atteint "
                            f"{p['label']}.\nPosition lue : {self.az}°\n\nCauses possibles : rotor bloqué, "
                            f"vent, problème mécanique ou de capteur.")

    # ------------------------------------------------------------ vent
    def wind_desc(self):
        w = self.weather
        if w.get("speed") is None:
            return "météo inconnue"
        return f"vent {w['speed']} km/h, rafales {w['gust']} km/h, direction {w['dir']}°"

    def override_active(self):
        return float(self.state.get("wind_override_until") or 0) > time.time()

    async def _weather_loop(self):
        await asyncio.sleep(4)
        while True:
            try:
                w = self.state["wind"]
                interval = int(self.cfg.get("weather_interval", 300))
                if (w.get("enabled") and w.get("source", "openmeteo") == "openmeteo" and not self.weather.get("simulated")
                        and time.time() - self._last_fetch >= interval):
                    self._last_fetch = time.time()
                    await self.fetch_weather()
                self.wind_evaluate()
            except Exception:
                log.exception("Météo")
            await asyncio.sleep(20)

    async def fetch_weather(self):
        g = self.cfg.get("grid")
        if not valid_grid(g):
            self.weather["error"] = "Grid de la station non défini"
            self.broadcast_state()
            return
        lat, lon = grid_to_latlon(g)
        params = {"latitude": f"{lat:.3f}", "longitude": f"{lon:.3f}",
                  "current": "wind_speed_10m,wind_gusts_10m,wind_direction_10m",
                  "wind_speed_unit": "kmh", "timezone": "auto"}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
                async with s.get(OPEN_METEO, params=params) as r:
                    r.raise_for_status()
                    j = await r.json()
            c = j["current"]
            had_error = bool(self.weather.get("error"))
            self.weather.update(speed=round(c["wind_speed_10m"]), gust=round(c["wind_gusts_10m"]),
                                dir=round(c["wind_direction_10m"]) % 360, time=c.get("time", ""),
                                fetched=time.time(), error="")
            if had_error:
                self.tlog("wind", "info", f"Météo rétablie : {self.wind_desc()}")
        except Exception as e:
            if not self.weather.get("error"):
                self.tlog("wind", "info", f"Météo indisponible : {e or type(e).__name__}", blocked=True)
            self.weather["error"] = str(e) or type(e).__name__
        self.broadcast_state()

    def wind_evaluate(self):
        w = self.state["wind"]
        now = time.time()
        until = float(self.state.get("wind_override_until") or 0)
        if until and now > until:
            self.state["wind_override_until"] = 0
            self.save_state()
            self.tlog("wind", "info", "Fin du contournement du verrou vent")
            if self.wind_locked:
                self.send_email("💨 Fin du contournement : verrou vent actif",
                                f"Le contournement est terminé et le vent est encore fort ({self.wind_desc()}).\n"
                                f"L'antenne retourne au repos.")
                self.wind_go_rest()
            self.broadcast_state()
        if not w.get("enabled"):
            if self.wind_locked:
                self.wind_unlock("protection contre le vent désactivée")
            return
        sp, gu = self.weather.get("speed"), self.weather.get("gust")
        fresh = self.weather.get("fetched") and now - self.weather["fetched"] < 1800
        if sp is None or not fresh:
            return  # pas de donnée fiable : on garde l'état actuel
        over = sp > float(w["max_speed"]) or (gu is not None and gu > float(w["max_gust"]))
        if over:
            if self.wind_calm_since is not None:
                self.wind_calm_since = None
                self.broadcast_state()
            if not self.wind_locked:
                self.wind_lock()
        elif self.wind_locked:
            if self.wind_calm_since is None:
                self.wind_calm_since = now
                self.tlog("wind", "info", f"Vent sous les seuils — déverrouillage dans {w['clear_minutes']} min si ça se maintient")
                self.broadcast_state()
            elif now - self.wind_calm_since >= float(w["clear_minutes"]) * 60:
                self.wind_unlock("vent revenu sous les seuils")

    def wind_lock(self):
        w = self.state["wind"]
        self.wind_locked = True
        self.wind_calm_since = None
        self.tlog("wind", "info", f"💨 VERROU VENT activé — {self.wind_desc()}", blocked=True)
        self.send_email("💨 Verrou vent activé",
                        f"Le vent dépasse les seuils (vent {w['max_speed']} km/h / rafales {w['max_gust']} km/h).\n"
                        f"Mesure : {self.wind_desc()}\n\n"
                        f"L'antenne est envoyée au repos ({round(self.rest_az())}°) et tous les mouvements "
                        f"sont bloqués jusqu'à ce que le vent reste sous les seuils pendant "
                        f"{w['clear_minutes']} minutes.")
        self.wind_go_rest()
        self.broadcast_state()

    def wind_go_rest(self):
        az = self.rest_az()
        label = f"Repos ({round(az)}°)"
        ok, reason = self.request_move("wind", az, label=label)
        if ok:
            self.pending_confirm = {"kind": "wind_rest", "az": az, "label": label,
                                    "plage": "protection contre le vent", "t": time.time()}
        else:
            self.tlog("wind", "info", f"Antenne non déplacée au repos : {reason}", blocked=True)

    def wind_unlock(self, why):
        self.wind_locked = False
        self.wind_calm_since = None
        self.state["wind_override_until"] = 0
        self.save_state()
        self.tlog("wind", "info", f"✅ Verrou vent levé ({why})")
        self.send_email("✅ Verrou vent levé", f"Le rotor peut de nouveau bouger ({why}).\nMétéo : {self.wind_desc()}")
        self.sched_applied = "__reapply__"
        self.broadcast_state()

    def wind_override(self, minutes, who):
        if not self.wind_locked:
            return False, "Aucun verrou vent actif"
        minutes = max(5, min(120, int(minutes)))
        until = time.time() + minutes * 60
        self.state["wind_override_until"] = until
        self.save_state()
        self.tlog("web", "info", f"⚠ Verrou vent IGNORÉ pendant {minutes} min ({self.wind_desc()})",
                  blocked=True, peer=who)
        self.send_email("⚠ Verrou vent ignoré",
                        f"{who} a contourné le verrou vent pendant {minutes} minutes "
                        f"(jusqu'à {self.fmt_time(until)}).\nMétéo : {self.wind_desc()}\n\n"
                        f"Seules les commandes manuelles sont permises pendant ce temps.")
        self.broadcast_state()
        return True, ""

    def wind_override_cancel(self, who):
        if self.state.get("wind_override_until"):
            self.state["wind_override_until"] = 0
            self.save_state()
            self.tlog("web", "info", "Contournement du verrou vent annulé", peer=who)
            if self.wind_locked:
                self.wind_go_rest()
            self.broadcast_state()

    # ------------------------------------------------------------ courriel
    def email_ready(self):
        e = self.cfg.get("email") or {}
        return bool(e.get("enabled") and e.get("username") and e.get("password") and e.get("to"))

    def send_email(self, subject, body, email=True, ha=True, kind=None):
        """Notification : courriel (si configuré) et événement Home Assistant, dans la langue de la station."""
        tr_subject, tr_body = self.tr(subject), "\n".join(self.tr(x) for x in body.split("\n"))
        bridge = getattr(self, "ha", None)
        if bridge and ha:
            bridge.event(subject, tr_body, kind=kind, title=tr_subject)  # entité Notifications
        if not email or not self.email_ready() or not self.loop:
            return
        self.loop.run_in_executor(None, self._smtp_send, dict(self.cfg["email"]), tr_subject, tr_body, False)

    def _smtp_send(self, e, subject, body, raise_errors):
        try:
            call = self.cfg.get("callsign") or "RotorWeb"
            msg = EmailMessage()
            msg["Subject"] = f"[{call}] {subject}"
            msg["From"] = e["username"]
            msg["To"] = e["to"]
            msg.set_content(f"{body}\n\n—\nRotorWeb {self.version} · {call} · grid {self.cfg.get('grid') or '?'}\n"
                            f"{self.now_local().strftime('%Y-%m-%d %H:%M:%S %Z')}")
            with smtplib.SMTP(e.get("smtp_host", "smtp.gmail.com"), int(e.get("smtp_port", 587)), timeout=20) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(e["username"], e["password"].replace(" ", ""))
                s.send_message(msg)
            self.tlog("system", "info", f"📧 Courriel envoyé : {subject}")
        except Exception as ex:
            self.tlog("system", "info", f"📧 Échec du courriel « {subject} » : {ex}", blocked=True)
            if raise_errors:
                raise

    # ------------------------------------------------------------ commandes web
    async def auto_cmd(self, cmd, d, who, toast):
        """Commandes web liées aux automatismes. Retourne True si traitée."""
        if cmd == "set_mode":
            m = d.get("mode")
            if m in ("manual", "schedule", "track"):
                self.set_mode(m, who=who)
            return True
        if cmd == "sched_save":
            it = d.get("item") or {}
            try:
                _hm(it["start"]); _hm(it["end"])
                days = sorted({int(x) for x in it.get("days", []) if 0 <= int(x) <= 6})
                t = it.get("target") or {}
                if t.get("type") == "grid":
                    t["value"] = str(t.get("value", "")).strip().upper()
                self.resolve_target(t) if t.get("type") == "az" else None
                if t.get("type") not in ("region", "grid", "az", "track"):
                    raise ValueError("cible manquante")
                if t["type"] == "track":
                    self._body(t.get("value", ""))
                if t["type"] == "grid" and not valid_grid(t["value"]):
                    raise ValueError("grid invalide")
                if t["type"] == "region" and t.get("value") not in REGION_MAP:
                    raise ValueError("région invalide")
            except Exception as e:
                await toast(f"Plage invalide : {e}")
                return True
            if not days:
                await toast("Choisis au moins un jour")
                return True
            item = {"id": it.get("id") or uuid.uuid4().hex[:8], "name": str(it.get("name", "")).strip()[:40],
                    "start": it["start"], "end": it["end"], "days": days, "target": t,
                    "enabled": bool(it.get("enabled", True))}
            lst = self.state["schedules"]
            for i, s in enumerate(lst):
                if s["id"] == item["id"]:
                    lst[i] = item
                    break
            else:
                lst.append(item)
            lst.sort(key=lambda s: s["start"])
            self.save_state()
            self.sched_applied = "__reapply__"
            self.tlog("web", "info", f"Plage enregistrée : {item['start']}–{item['end']} {self.target_label(t)}", peer=who)
            self.scheduler_tick()
            self.broadcast_state()
            await toast("Plage enregistrée", "ok")
            return True
        if cmd in ("sched_del", "sched_toggle"):
            lst = self.state["schedules"]
            for s in list(lst):
                if s["id"] == d.get("id"):
                    if cmd == "sched_del":
                        lst.remove(s)
                    else:
                        s["enabled"] = bool(d.get("enabled"))
            self.save_state()
            self.sched_applied = "__reapply__"
            self.scheduler_tick()
            self.broadcast_state()
            return True
        if cmd == "rest_save":
            try:
                self.state["rest"] = {"az": int(float(d.get("az", 0))) % 360, "wind_align": bool(d.get("wind_align"))}
            except ValueError:
                await toast("Azimut de repos invalide")
                return True
            self.save_state()
            self.broadcast_state()
            await toast("Position de repos enregistrée", "ok")
            return True
        if cmd == "go_rest":
            az = self.rest_az()
            ok, reason = self.request_move("web", az, peer=who, label=f"Repos ({round(az)}°)")
            if not ok:
                await toast(f"Refusé : {reason}")
            return True
        if cmd == "wind_save":
            try:
                w = {"enabled": bool(d.get("enabled")), "max_speed": max(5, int(d["max_speed"])),
                     "max_gust": max(5, int(d["max_gust"])), "clear_minutes": max(1, int(d["clear_minutes"])),
                     "source": d.get("source") if d.get("source") in ("openmeteo", "ha") else "openmeteo"}
                if w["source"] != self.state["wind"].get("source"):
                    self.weather.update(speed=None, gust=None, dir=None, fetched=0, error="", simulated=False)
            except Exception:
                await toast("Valeurs de vent invalides")
                return True
            self.state["wind"] = w
            self.save_state()
            self.tlog("web", "info", f"Protection vent : {'active' if w['enabled'] else 'DÉSACTIVÉE'} "
                                     f"(vent {w['max_speed']} / rafales {w['max_gust']} km/h, {w['clear_minutes']} min)", peer=who)
            if w["enabled"] and w["source"] == "openmeteo" and time.time() - self._last_fetch > 60:
                self._last_fetch = 0
            self.wind_evaluate()
            self.broadcast_state()
            await toast("Protection contre le vent enregistrée", "ok")
            return True
        if cmd == "wind_override":
            ok, reason = self.wind_override(d.get("minutes", 15), who)
            if not ok:
                await toast(reason)
            return True
        if cmd == "wind_override_cancel":
            self.wind_override_cancel(who)
            return True
        if cmd == "weather_refresh":
            if self.state["wind"].get("source") == "ha":
                await toast("Source Home Assistant : les données arrivent de HA à chaque changement")
                return True
            self._last_fetch = time.time()
            self.weather["simulated"] = False
            await self.fetch_weather()
            self.wind_evaluate()
            return True
        if cmd == "sim_wind" and self.simulate:
            self.weather.update(speed=int(d.get("speed", 0)), gust=int(d.get("gust", 0)), dir=int(d.get("dir", 0)),
                                fetched=time.time(), error="", simulated=True, time="simulation")
            self.tlog("wind", "info", f"[SIMULATION] {self.wind_desc()}")
            self.wind_evaluate()
            self.broadcast_state()
            return True
        if cmd == "email_save":
            e = dict(self.cfg.get("email") or {})
            e.setdefault("smtp_host", "smtp.gmail.com")
            e.setdefault("smtp_port", 587)
            e["enabled"] = bool(d.get("enabled"))
            e["username"] = str(d.get("username", "")).strip()
            e["to"] = str(d.get("to", "")).strip()
            if d.get("password"):
                e["password"] = str(d["password"]).strip()
            self.cfg["email"] = e
            self.save_config()
            self.broadcast_state()
            await toast("Réglages courriel enregistrés", "ok")
            return True
        if cmd == "email_test":
            e = self.cfg.get("email") or {}
            if not (e.get("username") and e.get("password") and e.get("to")):
                await toast("Complète l'adresse Gmail, le mot de passe d'application et le destinataire")
                return True
            try:
                await self.loop.run_in_executor(None, self._smtp_send, dict(e), self.tr("Courriel test"),
                                                self.tr("Ceci est un test : les courriels de RotorWeb fonctionnent. 73 !"), True)
                await toast(f"Courriel test envoyé à {e['to']}", "ok")
            except Exception as ex:
                await toast(f"Échec : {ex}", "error")
            return True
        return False
