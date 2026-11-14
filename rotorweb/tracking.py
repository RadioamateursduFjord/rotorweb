# -*- coding: utf-8 -*-
"""
RotorWeb — suivi de satellites, de l'ISS, de la Lune et du Soleil.

Mélangé (mixin) dans la classe Controller de server.py.

- Positions calculées avec PyEphem depuis le grid de la station.
- Éléments orbitaux (TLE) téléchargés une fois par jour sur CelesTrak.
- Le rotor ne bouge que si l'écart dépasse un seuil (ménage le moteur).
- Prépositionnement avant le lever, retournement (« flip ») pour les rotors 0–180°
  quand un passage traverserait la butée, retour au repos après le coucher.
"""
import asyncio
import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

from rotorweb.geo import angdiff, grid_to_latlon, valid_grid

try:
    import ephem
except ImportError:  # pragma: no cover
    ephem = None

log = logging.getLogger("rotorweb")

CELESTRAK = "https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=tle"
TLE_GROUPS = ("amateur", "stations")
TLE_MAX_AGE = 24 * 3600
DEFAULT_TRACKING = {
    "target": "",            # cible choisie (« moon », « sun », « sat:ISS (ZARYA) »…)
    "threshold": 3.0,        # écart (°) avant de déplacer le rotor
    "prepos_min": 3,         # prépositionnement avant le lever (minutes)
    "min_el": 0.0,           # élévation minimale de suivi (°)
    "flip": True,            # retournement pour les rotors 0–180°
    "park_after": True,      # repos après le coucher
    "notify": True,          # courriel / Home Assistant au début et à la fin
    "altitude_m": 0,         # altitude de la station
    "auto": [],              # règles : [{"target": ..., "min_el": 20}]
    "planned": [],           # passages planifiés : [{"target", "start", "end"}]
    "custom_tle": [],        # [{"name", "l1", "l2"}]
}


def _ts(d):
    """ephem.Date → horodatage Unix."""
    return ephem.Date(d).datetime().replace(tzinfo=timezone.utc).timestamp()


class TrackingMixin:
    # ------------------------------------------------------------ init
    def track_init(self):
        self.tle = {}                 # nom → (l1, l2)
        self.tle_fetched = 0.0
        self.tle_error = ""
        self.track_now = {}           # position actuelle de la cible
        self.track_active = None      # passage en cours : {"key","name","flip","los","start"}
        self.track_last_cmd = None    # (az, el) dernière commande envoyée
        self.track_passes_cache = {}  # clé → (horodatage, liste)
        self.sched_track = None       # cible de suivi d'une plage horaire
        self._load_tle_cache()

    def track_start(self):
        asyncio.create_task(self._track_loop())
        asyncio.create_task(self._tle_loop())

    @property
    def tcfg(self):
        t = self.state.setdefault("tracking", {})
        for k, v in DEFAULT_TRACKING.items():
            t.setdefault(k, v if not isinstance(v, list) else list(v))
        return t

    # ------------------------------------------------------------ TLE
    def _tle_path(self):
        return self.config_path.with_name("tle.txt")

    def _parse_tle(self, text):
        out = {}
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        i = 0
        while i <= len(lines) - 3:
            name, l1, l2 = lines[i], lines[i + 1], lines[i + 2]
            if l1.startswith("1 ") and l2.startswith("2 "):
                out[name] = (l1, l2)
                i += 3
            else:
                i += 1
        return out

    def _load_tle_cache(self):
        p = self._tle_path()
        if p.exists():
            try:
                self.tle = self._parse_tle(p.read_text(encoding="utf-8"))
                self.tle_fetched = p.stat().st_mtime
            except Exception as e:
                self.tle_error = str(e)

    async def fetch_tle(self):
        texts = []
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
                for g in TLE_GROUPS:
                    async with s.get(CELESTRAK.format(group=g)) as r:
                        r.raise_for_status()
                        texts.append(await r.text())
            text = "\n".join(texts)
            parsed = self._parse_tle(text)
            if len(parsed) < 5:
                raise ValueError("réponse de CelesTrak inattendue")
            self._tle_path().write_text(text, encoding="utf-8")
            self.tle, self.tle_fetched, self.tle_error = parsed, time.time(), ""
            self.track_passes_cache.clear()
            self.tlog("track", "info", f"Éléments orbitaux mis à jour : {len(parsed)} satellites (CelesTrak)")
        except Exception as e:
            self.tle_error = str(e) or type(e).__name__
            self.tlog("track", "info", f"Mise à jour des éléments orbitaux impossible : {self.tle_error}", blocked=True)
        self.broadcast_state()

    async def _tle_loop(self):
        await asyncio.sleep(8)
        while True:
            if ephem and time.time() - self.tle_fetched > TLE_MAX_AGE:
                await self.fetch_tle()
            await asyncio.sleep(1800)

    # ------------------------------------------------------------ cibles
    def all_tle(self):
        d = dict(self.tle)
        for c in self.tcfg.get("custom_tle", []):
            d[c["name"]] = (c["l1"], c["l2"])
        return d

    def targets_public(self):
        out = [{"key": "moon", "name": "Lune", "group": "Astres"},
               {"key": "sun", "name": "Soleil", "group": "Astres"}]
        tle = self.all_tle()
        custom = {c["name"] for c in self.tcfg.get("custom_tle", [])}
        names = sorted(tle, key=lambda n: (not n.startswith("ISS"), n))
        for n in names:
            grp = "Personnalisés" if n in custom else ("Stations spatiales" if n.startswith(("ISS", "CSS", "TIANHE")) else "Satellites")
            out.append({"key": f"sat:{n}", "name": n, "group": grp})
        return out

    def target_name(self, key):
        if key == "moon":
            return "Lune"
        if key == "sun":
            return "Soleil"
        return key[4:] if key.startswith("sat:") else key

    def _observer(self, when=None):
        g = self.cfg.get("grid")
        if not valid_grid(g):
            raise ValueError("Grid de la station non défini")
        lat, lon = grid_to_latlon(g)
        o = ephem.Observer()
        o.lat, o.lon = str(lat), str(lon)
        o.elevation = float(self.tcfg.get("altitude_m") or 0)
        o.pressure = 0          # pas de réfraction : géométrie pure
        o.date = ephem.Date(datetime.fromtimestamp(when or time.time(), timezone.utc).replace(tzinfo=None))
        return o

    def _body(self, key):
        if key == "moon":
            return ephem.Moon()
        if key == "sun":
            return ephem.Sun()
        if key.startswith("sat:"):
            name = key[4:]
            tle = self.all_tle().get(name)
            if not tle:
                raise ValueError(f"Satellite inconnu ou éléments orbitaux absents : {name}")
            return ephem.readtle(name, tle[0], tle[1])
        raise ValueError(f"Cible inconnue : {key}")

    def target_position(self, key, when=None):
        o = self._observer(when)
        b = self._body(key)
        b.compute(o)
        az = math.degrees(float(b.az)) % 360
        el = math.degrees(float(b.alt))
        rng = None
        if key.startswith("sat:"):
            rng = float(b.range) / 1000.0
        elif key == "moon":
            rng = float(b.earth_distance) * 149597870.7
        return {"az": round(az, 1), "el": round(el, 1), "range_km": round(rng) if rng else None}

    # ------------------------------------------------------------ passages
    def passes(self, key, hours=48, min_el=0.0, limit=12):
        """Prochains passages au-dessus de l'horizon."""
        now = time.time()
        cached = self.track_passes_cache.get((key, hours, min_el, limit))
        if cached and now - cached[0] < 60:
            return cached[1]
        out = []
        o = self._observer(now)
        b = self._body(key)
        end = ephem.Date(o.date + hours * ephem.hour)
        # Passage déjà en cours : on recule le départ jusqu'au lever
        b.compute(o)
        if math.degrees(float(b.alt)) > 0:
            o.date = ephem.Date(o.date - (12 * ephem.hour if key in ("moon", "sun") else 20 * ephem.minute))
        guard = 0
        while o.date < end and len(out) < limit and guard < 200:
            guard += 1
            try:
                if key in ("moon", "sun"):
                    rise = o.next_rising(b)
                    o2 = self._observer()
                    o2.date = rise
                    transit = o2.next_transit(b)
                    o2.date = rise
                    setting = o2.next_setting(b)
                    o2.date = transit
                    b.compute(o2)
                    maxel = math.degrees(float(b.alt))
                    rec = (rise, transit, setting, maxel)
                else:
                    tr, azr, tmax, altmax, ts_, azs = o.next_pass(b)
                    if tr is None or ts_ is None:
                        break
                    rec = (tr, tmax, ts_, math.degrees(float(altmax)))
            except (ephem.CircumpolarError, ephem.NeverUpError, ValueError):
                break
            rise, tmax, setting, maxel = rec
            if setting <= o.date:
                o.date = ephem.Date(o.date + ephem.minute)
                continue
            if maxel >= min_el and _ts(setting) > now:
                a = self.target_position(key, _ts(rise))
                z = self.target_position(key, _ts(setting))
                out.append({"key": key, "name": self.target_name(key), "aos": _ts(rise), "tca": _ts(tmax),
                            "los": _ts(setting), "max_el": round(maxel, 1),
                            "aos_az": round(a["az"]), "los_az": round(z["az"])})
            o.date = ephem.Date(setting + ephem.minute)
        self.track_passes_cache[(key, hours, min_el, limit)] = (now, out)
        return out

    def pass_track(self, key, aos, los, step=None):
        """Trajectoire d'un passage (pour la carte du ciel et le choix du retournement)."""
        dur = max(1.0, los - aos)
        step = step or max(5.0, dur / 120)
        pts, t = [], aos
        while t <= los + 0.1:
            p = self.target_position(key, t)
            pts.append([round(p["az"], 1), round(p["el"], 1)])
            t += step
        return pts

    def _needs_flip(self, pts):
        """Le passage traverserait-il la butée du rotor ? (azimut seul : on ne peut rien y faire)"""
        rc = self.cfg["rotor"]
        if not (self.cfg.get("elevation") and int(rc.get("el_range", 180)) >= 180 and self.tcfg.get("flip")):
            return False
        stop = float(rc.get("stop_at", 0))
        rng = float(rc.get("range", 450))

        def crosses(path):
            ts = [(a - stop) % 360 for a, _ in path]
            lo = hi = ts[0]
            for i in range(1, len(ts)):
                d = ((ts[i] - ts[i - 1] + 540) % 360) - 180      # pas angulaire signé
                cur = ts[i - 1] + d
                if cur < 0 or cur > rng:
                    return True
                ts[i] = cur
                lo, hi = min(lo, cur), max(hi, cur)
            return False

        if not crosses(pts):
            return False
        flipped = [[(a + 180) % 360, 180 - e] for a, e in pts]
        return not crosses(flipped)

    # ------------------------------------------------------------ boucle de suivi
    def _track_source(self):
        if self.state.get("mode") == "track":
            return "track"
        if self.state.get("mode") == "schedule" and self.sched_track:
            return "schedule"
        return None

    def _wanted_target(self):
        """Cible à suivre maintenant (sélection manuelle, plage horaire, règle auto ou passage planifié)."""
        src = self._track_source()
        if src == "schedule":
            return self.sched_track
        if src != "track":
            return None
        now = time.time()
        prepos = float(self.tcfg.get("prepos_min", 3)) * 60
        for p in self.tcfg.get("planned", []):
            if p["start"] - prepos <= now <= p["end"]:
                return p["target"]
        for rule in self.tcfg.get("auto", []):
            try:
                for ps in self.passes(rule["target"], hours=3, min_el=float(rule.get("min_el", 0)), limit=2):
                    if ps["aos"] - prepos <= now <= ps["los"]:
                        return rule["target"]
            except Exception:
                continue
        return self.tcfg.get("target") or None

    def track_tick(self):
        if not ephem:
            return
        key = self._wanted_target()
        now = time.time()
        if not key:
            if self.track_active:
                self._track_end("cible abandonnée")
            self.track_now = {}
            return
        try:
            pos = self.target_position(key)
        except Exception as e:
            self.track_now = {"key": key, "name": self.target_name(key), "error": str(e)}
            return
        min_el = max(float(self.tcfg.get("min_el", 0)), 0.0)
        above = pos["el"] >= min_el
        self.track_now = {"key": key, "name": self.target_name(key), **pos, "above": above,
                          "flip": bool(self.track_active and self.track_active.get("flip"))}
        src = self._track_source()

        if above:
            if not self.track_active or self.track_active["key"] != key:
                self._track_begin(key)
            az, el = pos["az"], pos["el"]
            if self.track_active.get("flip"):
                az, el = (az + 180) % 360, 180 - el
            self._track_point(src, key, az, el)
            return

        # Sous l'horizon : prépositionnement avant le lever, sinon fin de passage
        if self.track_active and self.track_active["key"] == key:
            self._track_end("coucher")
        try:
            nxt = self.passes(key, hours=48, min_el=min_el, limit=1)
        except Exception:
            nxt = []
        if nxt:
            self.track_now["next"] = nxt[0]
            prepos = float(self.tcfg.get("prepos_min", 3)) * 60
            if nxt[0]["aos"] - prepos <= now < nxt[0]["aos"]:
                pts = self.pass_track(key, nxt[0]["aos"], nxt[0]["los"])
                flip = self._needs_flip(pts)
                az, el = pts[0]
                if flip:
                    az, el = (az + 180) % 360, 180 - el
                self.track_now["prepos"] = True
                self._track_point(src, key, az, max(el, 0.0), label="prépositionnement")

    def _track_point(self, src, key, az, el, label=None):
        thr = float(self.tcfg.get("threshold", 3))
        last = self.track_last_cmd
        has_el = bool(self.cfg.get("elevation"))
        if last and angdiff(last[0], az) < thr and (not has_el or abs(last[1] - el) < thr):
            return
        el_cmd = max(0.0, min(float(self.cfg["rotor"].get("el_range", 180)), el)) if has_el else None
        if time.time() < getattr(self, "_track_refused_until", 0):
            return
        ok, reason = self.request_move(src, az, el_cmd, label=label or self.target_name(key), quiet=True)
        if ok:
            self.track_last_cmd = (az, el)
        else:
            self._track_refused_until = time.time() + 30   # évite de répéter le refus chaque seconde
            self.tlog("track", "info", f"Suivi de {self.target_name(key)} refusé : {reason}", blocked=True)

    def _track_begin(self, key):
        now = time.time()
        flip, los, max_el = False, None, None
        try:
            ps = self.passes(key, hours=24, min_el=0, limit=1)
            if ps and ps[0]["aos"] <= now + 60:
                los, max_el = ps[0]["los"], ps[0]["max_el"]
                flip = self._needs_flip(self.pass_track(key, max(now, ps[0]["aos"]), los))
        except Exception:
            pass
        self.track_active = {"key": key, "name": self.target_name(key), "flip": flip, "los": los, "start": now}
        self.track_last_cmd = None
        txt = f"🛰 Début du suivi : {self.target_name(key)}"
        if max_el is not None:
            txt += f" (élévation max {max_el:.0f}°, fin {self.fmt_time(los)})"
        if flip:
            txt += " — mode retournement"
        self.tlog("track", "info", txt)
        if self.tcfg.get("notify"):
            self.send_email(f"🛰 Début du suivi : {self.target_name(key)}",
                            f"{txt}\nPosition : azimut {self.track_now.get('az')}°, élévation {self.track_now.get('el')}°.")

    def _track_end(self, why):
        a = self.track_active
        self.track_active = None
        self.track_last_cmd = None
        if not a:
            return
        dur = int((time.time() - a["start"]) / 60)
        self.tlog("track", "info", f"🛰 Fin du suivi : {a['name']} ({why}, {dur} min)")
        if self.tcfg.get("notify"):
            self.send_email(f"🛰 Fin du passage : {a['name']}", f"Suivi terminé ({why}) après {dur} minutes.")
        src = self._track_source()
        if self.tcfg.get("park_after") and src:
            az = self.rest_az()
            el = 0.0 if self.cfg.get("elevation") else None
            self.request_move(src, az, el, label=f"Repos après passage ({round(az)}°)")

    async def _track_loop(self):
        await asyncio.sleep(3)
        last_push = 0
        while True:
            try:
                self.track_tick()
                if time.time() - last_push > 2:
                    last_push = time.time()
                    self.broadcast({"type": "track", "track": self.track_public()})
            except Exception:
                log.exception("Suivi")
            await asyncio.sleep(1)

    # ------------------------------------------------------------ état public
    def _selected_public(self):
        key = self.tcfg.get("target")
        if not (ephem and key):
            return {}
        try:
            pos = self.target_position(key)
            nxt = self.passes(key, hours=48, min_el=0, limit=1)
            return {"key": key, "name": self.target_name(key), **pos, "above": pos["el"] >= 0,
                    "next": nxt[0] if nxt else None}
        except Exception as e:
            return {"key": key, "name": self.target_name(key), "error": str(e)}

    def track_public(self):
        t = self.tcfg
        return {"available": ephem is not None, "now": self.track_now, "active": self.track_active,
                "sel": self._selected_public(),
                "tle_count": len(self.tle), "tle_age_h": round((time.time() - self.tle_fetched) / 3600, 1) if self.tle_fetched else None,
                "tle_error": self.tle_error, "settings": {k: t[k] for k in DEFAULT_TRACKING if k not in ("custom_tle",)},
                "custom_tle": [c["name"] for c in t.get("custom_tle", [])],
                "flip_possible": bool(self.cfg.get("elevation")) and int(self.cfg["rotor"].get("el_range", 180)) >= 180}

    # ------------------------------------------------------------ commandes web
    async def track_cmd(self, cmd, d, who, ws, toast):
        if not cmd.startswith(("track_", "tle_")):
            return False
        if not ephem:
            await toast("Module de calcul « ephem » absent : relance update.sh")
            return True
        t = self.tcfg
        if cmd == "track_select":
            key = d.get("target") or ""
            if key:
                try:
                    self._body(key)
                except ValueError as e:
                    await toast(str(e))
                    return True
            t["target"] = key
            self.track_passes_cache.clear()
            self.save_state()
            if d.get("start") and key:
                self.set_mode("track", who=who)
            self.tlog("web", "info", f"Cible de suivi : {self.target_name(key) if key else 'aucune'}", peer=who)
            self.broadcast_state()
            return True
        if cmd == "track_passes":
            key = d.get("target") or t.get("target")
            try:
                ps = self.passes(key, hours=int(d.get("hours", 48)), min_el=float(d.get("min_el", 0)))
                trk = self.pass_track(key, ps[0]["aos"], ps[0]["los"]) if ps else []
                flip = self._needs_flip(trk) if trk else False
            except Exception as e:
                await toast(str(e))
                return True
            await self._safe_send(ws, {"type": "passes", "target": key, "passes": ps, "track": trk, "flip": flip})
            return True
        if cmd == "track_settings":
            try:
                t.update(threshold=max(0.5, min(30.0, float(d.get("threshold", 3)))),
                         prepos_min=max(0, min(30, int(d.get("prepos_min", 3)))),
                         min_el=max(0.0, min(80.0, float(d.get("min_el", 0)))),
                         flip=bool(d.get("flip")), park_after=bool(d.get("park_after")), notify=bool(d.get("notify")),
                         altitude_m=max(-400, min(9000, int(d.get("altitude_m", 0)))))
            except (TypeError, ValueError):
                await toast("Valeur invalide")
                return True
            self.track_passes_cache.clear()
            self.save_state()
            self.broadcast_state()
            await toast("Options de suivi enregistrées", "ok")
            return True
        if cmd == "track_auto_add":
            key = d.get("target")
            try:
                self._body(key)
                rule = {"target": key, "min_el": max(0.0, min(80.0, float(d.get("min_el", 10))))}
            except (ValueError, TypeError) as e:
                await toast(str(e))
                return True
            t["auto"] = [r for r in t["auto"] if r["target"] != key] + [rule]
            self.save_state()
            self.tlog("web", "info", f"Suivi automatique : {self.target_name(key)} au-dessus de {rule['min_el']:.0f}°", peer=who)
            self.broadcast_state()
            return True
        if cmd == "track_auto_del":
            i = int(d.get("index", -1))
            if 0 <= i < len(t["auto"]):
                t["auto"].pop(i)
                self.save_state()
                self.broadcast_state()
            return True
        if cmd == "track_plan":
            try:
                p = {"target": d["target"], "start": float(d["start"]), "end": float(d["end"])}
                self._body(p["target"])
            except (KeyError, ValueError, TypeError) as e:
                await toast(f"Passage invalide : {e}")
                return True
            t["planned"] = [x for x in t["planned"] if x["end"] > time.time()] + [p]
            self.save_state()
            self.tlog("web", "info", f"Passage planifié : {self.target_name(p['target'])} à {self.fmt_time(p['start'])}", peer=who)
            self.broadcast_state()
            await toast("Passage planifié — il sera suivi en mode 🛰 Suivi", "ok")
            return True
        if cmd == "track_plan_del":
            i = int(d.get("index", -1))
            if 0 <= i < len(t["planned"]):
                t["planned"].pop(i)
                self.save_state()
                self.broadcast_state()
            return True
        if cmd == "tle_refresh":
            await toast("Téléchargement des éléments orbitaux…", "ok")
            await self.fetch_tle()
            return True
        if cmd == "tle_custom_add":
            lines = [ln.strip() for ln in str(d.get("text", "")).splitlines() if ln.strip()]
            if len(lines) == 2:
                lines = [str(d.get("name") or "Perso").strip()] + lines
            if len(lines) != 3 or not lines[1].startswith("1 ") or not lines[2].startswith("2 "):
                await toast("Colle 3 lignes : le nom, puis les lignes 1 et 2 du TLE")
                return True
            try:
                ephem.readtle(lines[0], lines[1], lines[2])
            except Exception as e:
                await toast(f"TLE invalide : {e}")
                return True
            t["custom_tle"] = [c for c in t["custom_tle"] if c["name"] != lines[0]] + \
                              [{"name": lines[0], "l1": lines[1], "l2": lines[2]}]
            self.save_state()
            self.broadcast_state()
            await toast(f"Satellite « {lines[0]} » ajouté", "ok")
            return True
        if cmd == "tle_custom_del":
            name = d.get("name")
            t["custom_tle"] = [c for c in t["custom_tle"] if c["name"] != name]
            self.save_state()
            self.broadcast_state()
            return True
        return False
