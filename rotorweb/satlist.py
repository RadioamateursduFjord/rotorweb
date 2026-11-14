# -*- coding: utf-8 -*-
"""
RotorWeb — liste des prochains passages de tous les satellites utilisables.

- Fréquences, modes et site web des satellites : base SatNOGS (db.satnogs.org),
  téléchargée une fois par jour et gardée sur disque (satnogs.json).
- Filtre par bande (on coche les bandes de la station), élévation minimale,
  zones interdites du rotor.
- Alertes facultatives avant un bon passage (courriel et/ou Home Assistant).

Mélangé (mixin) dans la classe Controller de server.py, après TrackingMixin.
"""
import asyncio
import json
import logging
import re
import time

import aiohttp

log = logging.getLogger("rotorweb")

SATNOGS_SATS = "https://db.satnogs.org/api/satellites/?format=json"
SATNOGS_TX = "https://db.satnogs.org/api/transmitters/?format=json"
SATNOGS_PAGE = "https://db.satnogs.org/satellite/{sat_id}"
SATNOGS_MAX_AGE = 24 * 3600
BANDS = [  # (clé, nom, bas Hz, haut Hz)
    ("10m", "10 m", 28.0e6, 29.7e6), ("6m", "6 m", 50.0e6, 54.0e6), ("2m", "2 m", 144.0e6, 148.0e6),
    ("70cm", "70 cm", 420.0e6, 450.0e6), ("23cm", "23 cm", 1240e6, 1300e6), ("13cm", "13 cm", 2300e6, 2450e6),
    ("9cm", "9 cm", 3300e6, 3500e6), ("5cm", "5 cm", 5650e6, 5925e6), ("3cm", "3 cm", 10.0e9, 10.5e9),
]
DEFAULT_SATLIST = {"bands": ["2m", "70cm"], "need_uplink": False, "hours": 24, "min_el": 10.0,
                   "hide_nogo": False,
                   "alerts": {"enabled": False, "minutes": 10, "min_el": 30.0, "email": True, "ha": True}}
CTCSS_RE = re.compile(r"(?:ctcss|tone|pl)?\s*(\d{2,3}(?:[.,]\d)?)\s*hz", re.I)


def band_of(hz):
    if not hz:
        return None
    for key, _, lo, hi in BANDS:
        if lo <= hz <= hi:
            return key
    return None


def mhz(hz):
    return f"{hz / 1e6:.3f}" if hz else None


def norad_of(l1):
    try:
        return int(l1[2:7])
    except (TypeError, ValueError):
        return None


class SatListMixin:
    # ------------------------------------------------------------ init
    def satlist_init(self):
        self.satnogs = {"sats": {}, "tx": {}}      # norad → satellite / liste d'émetteurs
        self.satnogs_fetched = 0.0
        self.satnogs_error = ""
        self.satpasses = {"t": 0.0, "sig": None, "list": [], "busy": False}
        self.sat_alerted = {}
        self._load_satnogs_cache()

    def satlist_start(self):
        asyncio.create_task(self._satnogs_loop())
        asyncio.create_task(self._satalert_loop())

    @property
    def scfg(self):
        s = self.state.setdefault("satlist", {})
        for k, v in DEFAULT_SATLIST.items():
            if isinstance(v, dict):
                s[k] = {**v, **(s.get(k) or {})}
            else:
                s.setdefault(k, list(v) if isinstance(v, list) else v)
        return s

    # ------------------------------------------------------------ SatNOGS
    def _satnogs_path(self):
        return self.config_path.with_name("satnogs.json")

    def _index_satnogs(self, sats, txs):
        out_s, out_t = {}, {}
        for s in sats or []:
            n = s.get("norad_cat_id")
            if n:
                out_s[int(n)] = {"name": s.get("name"), "sat_id": s.get("sat_id"), "website": s.get("website") or "",
                                 "status": s.get("status"), "names": s.get("names") or "",
                                 "image": s.get("image") or ""}
        for t in txs or []:
            n = t.get("norad_cat_id")
            alive = t.get("alive", True) and t.get("status", "active") == "active"
            if not n or not alive:
                continue
            if t.get("service") not in (None, "", "Amateur"):
                continue
            desc = t.get("description") or ""
            m = CTCSS_RE.search(desc)
            out_t.setdefault(int(n), []).append({
                "desc": desc[:120], "type": t.get("type") or "", "mode": t.get("mode") or "",
                "up_mode": t.get("uplink_mode") or "",
                "down": t.get("downlink_low"), "down_hi": t.get("downlink_high"),
                "up": t.get("uplink_low"), "up_hi": t.get("uplink_high"), "invert": bool(t.get("invert")),
                "ctcss": m.group(1).replace(",", ".") if m and float(m.group(1).replace(",", ".")) < 260 else None,
            })
        return out_s, out_t

    def _load_satnogs_cache(self):
        p = self._satnogs_path()
        if p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                s, t = self._index_satnogs(d.get("satellites"), d.get("transmitters"))
                self.satnogs = {"sats": s, "tx": t}
                self.satnogs_fetched = p.stat().st_mtime
            except Exception as e:
                self.satnogs_error = str(e)

    async def fetch_satnogs(self):
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
                async with s.get(SATNOGS_SATS) as r:
                    r.raise_for_status()
                    sats = await r.json(content_type=None)
                async with s.get(SATNOGS_TX) as r:
                    r.raise_for_status()
                    txs = await r.json(content_type=None)
            si, ti = self._index_satnogs(sats, txs)
            if len(ti) < 10:
                raise ValueError("réponse de SatNOGS inattendue")
            self._satnogs_path().write_text(json.dumps({"satellites": sats, "transmitters": txs}), encoding="utf-8")
            self.satnogs, self.satnogs_fetched, self.satnogs_error = {"sats": si, "tx": ti}, time.time(), ""
            self.satpasses["t"] = 0
            self.tlog("track", "info", f"Fréquences des satellites mises à jour : {len(ti)} satellites (SatNOGS)")
        except Exception as e:
            self.satnogs_error = str(e) or type(e).__name__
            self.tlog("track", "info", f"Mise à jour SatNOGS impossible : {self.satnogs_error}", blocked=True)
        self.broadcast_state()

    async def _satnogs_loop(self):
        await asyncio.sleep(20)
        while True:
            if time.time() - self.satnogs_fetched > SATNOGS_MAX_AGE:
                await self.fetch_satnogs()
            await asyncio.sleep(1800)

    # ------------------------------------------------------------ satellites utilisables
    def sat_catalog(self):
        """[(clé, nom, norad)] de tous les satellites connus (TLE CelesTrak + personnalisés)."""
        out = []
        for name, (l1, _l2) in self.all_tle().items():
            out.append((f"sat:{name}", name, norad_of(l1)))
        return out

    def _tx_summary(self, txs, bands):
        """Émetteurs dans les bandes cochées, les transpondeurs/relais d'abord."""
        def rank(t):
            return (0 if t["up"] else 1, 0 if "FM" in (t["mode"] or "") else 1)
        sel = []
        for t in sorted(txs, key=rank):
            bd = band_of(t["down"])
            if bd in bands:
                sel.append(t)
        return sel

    def usable(self, norad):
        """None = pas de données SatNOGS ; [] = aucune fréquence dans les bandes ; sinon émetteurs utiles."""
        if not self.satnogs["tx"]:
            return None
        txs = self.satnogs["tx"].get(norad or -1)
        if not txs:
            return []
        c = self.scfg
        bands = set(c["bands"])
        sel = self._tx_summary(txs, bands)
        if c.get("need_uplink"):
            sel = [t for t in sel if t["up"] and band_of(t["up"]) in bands]
        return sel

    @staticmethod
    def fmt_tx(t):
        if not t:
            return ""
        s = f"↓{mhz(t['down'])}"
        if t.get("mode"):
            s += f" {t['mode']}"
        if t.get("up"):
            s += f" · ↑{mhz(t['up'])}"
            if t.get("up_mode") and t["up_mode"] != t.get("mode"):
                s += f" {t['up_mode']}"
        if t.get("ctcss"):
            s += f" · {t['ctcss']} Hz"
        if t.get("invert"):
            s += " · inversé"
        return s

    # ------------------------------------------------------------ calcul des passages
    def _in_nogo(self, az):
        for zone in self.cfg["rotor"].get("no_go") or []:
            a, b = float(zone[0]) % 360, float(zone[1]) % 360
            if (a <= az <= b) if a <= b else (az >= a or az <= b):
                return True
        return False

    def compute_all_passes(self):
        c = self.scfg
        hours = max(1, min(48, int(c.get("hours", 24))))
        min_el = float(c.get("min_el", 10))
        out = []
        no_data = not self.satnogs["tx"]
        has_nogo = bool(self.cfg["rotor"].get("no_go"))
        for key, name, norad in self.sat_catalog():
            txs = self.usable(norad)
            if txs is not None and not txs:
                continue
            try:
                ps = self.passes(key, hours=hours, min_el=min_el, limit=40)
            except Exception:
                continue
            sat = self.satnogs["sats"].get(norad or -1, {})
            for p in ps:
                nogo = False
                if has_nogo:
                    step = max(10.0, (p["los"] - p["aos"]) / 12)
                    t = p["aos"]
                    while t <= p["los"]:
                        if self._in_nogo(self.target_position(key, t)["az"]):
                            nogo = True
                            break
                        t += step
                if nogo and c.get("hide_nogo"):
                    continue
                out.append({**p, "norad": norad, "nogo": nogo, "freq": self.fmt_tx(txs[0]) if txs else "",
                            "nfreq": len(txs or []), "display": sat.get("name") or name})
        out.sort(key=lambda p: p["aos"])
        return out, no_data

    def _satpass_sig(self):
        c = self.scfg
        return json.dumps([c["bands"], c["need_uplink"], c["hours"], c["min_el"], c["hide_nogo"], self.cfg.get("grid"),
                           self.cfg["rotor"].get("no_go"), len(self.tle), self.tle_fetched, self.satnogs_fetched,
                           len(self.tcfg.get("custom_tle", []))])

    async def refresh_satpasses(self, force=False):
        sp = self.satpasses
        sig = self._satpass_sig()
        if sp["busy"] or (not force and sig == sp["sig"] and time.time() - sp["t"] < 600):
            return sp
        sp["busy"] = True
        try:
            lst, no_data = await self.loop.run_in_executor(None, self.compute_all_passes)
            sp.update(t=time.time(), sig=sig, list=lst, no_data=no_data, error="")
        except Exception as e:
            sp.update(t=time.time(), sig=sig, list=[], error=str(e))
        finally:
            sp["busy"] = False
        return sp

    def satpasses_public(self, limit=200):
        now = time.time()
        sp = self.satpasses
        return {"type": "satpasses", "passes": [p for p in sp["list"] if p["los"] > now][:limit],
                "computed": sp["t"], "no_data": sp.get("no_data", False), "error": sp.get("error", ""),
                "settings": self.scfg}

    def next_good_pass(self):
        now = time.time()
        a = self.scfg["alerts"]
        thr = float(a.get("min_el", 30)) if a.get("enabled") else float(self.scfg.get("min_el", 10))
        for p in self.satpasses["list"]:
            if p["los"] > now and p["max_el"] >= thr:
                return p
        return None

    # ------------------------------------------------------------ alertes
    async def _satalert_loop(self):
        await asyncio.sleep(30)
        while True:
            try:
                a = self.scfg["alerts"]
                need = a.get("enabled") or (self.ha and self.ha.connected)
                if need and self.cfg.get("grid"):
                    await self.refresh_satpasses()
                    if a.get("enabled"):
                        self._check_sat_alerts()
                    if self.ha:
                        self.ha.sync()
            except Exception:
                log.exception("Alertes satellites")
            await asyncio.sleep(30)

    def _check_sat_alerts(self):
        a = self.scfg["alerts"]
        now = time.time()
        lead = max(1, int(a.get("minutes", 10))) * 60
        for k in [k for k, t in self.sat_alerted.items() if t < now - 86400]:
            self.sat_alerted.pop(k, None)
        for p in self.satpasses["list"]:
            if p["max_el"] < float(a.get("min_el", 30)):
                continue
            k = f"{p['key']}@{int(p['aos'])}"
            if k in self.sat_alerted or not (p["aos"] - lead <= now < p["aos"]):
                continue
            self.sat_alerted[k] = now
            mins = max(0, round((p["aos"] - now) / 60))
            subj = f"🛰 Passage dans {mins} min : {p['display']} (max {p['max_el']:.0f}°)"
            body = (f"{p['display']} se lève à {self.fmt_time(p['aos'])} (azimut {p['aos_az']}°), "
                    f"élévation maximale {p['max_el']:.0f}° à {self.fmt_time(p['tca'])}, "
                    f"coucher à {self.fmt_time(p['los'])} (azimut {p['los_az']}°).")
            if p.get("freq"):
                body += f"\nFréquences : {p['freq']}"
            self.tlog("track", "info", subj)
            self.send_email(subj, body, email=bool(a.get("email")), ha=bool(a.get("ha")), kind="passage_sat")

    # ------------------------------------------------------------ fiche d'un satellite
    def sat_info(self, key):
        name = key[4:] if key.startswith("sat:") else key
        tle = self.all_tle().get(name)
        norad = norad_of(tle[0]) if tle else None
        sat = self.satnogs["sats"].get(norad or -1, {})
        txs = self.satnogs["tx"].get(norad or -1, [])
        bands = set(self.scfg["bands"])
        tx_out = []
        for t in sorted(txs, key=lambda t: (band_of(t["down"]) not in bands, t["down"] or 0)):
            tx_out.append({**t, "down_mhz": mhz(t["down"]), "up_mhz": mhz(t["up"]),
                           "down_band": band_of(t["down"]), "up_band": band_of(t["up"]),
                           "in_bands": band_of(t["down"]) in bands})
        return {"type": "satinfo", "key": key, "name": sat.get("name") or name, "tle_name": name, "norad": norad,
                "other_names": sat.get("names") or "", "website": sat.get("website") or "",
                "satnogs_url": SATNOGS_PAGE.format(sat_id=sat["sat_id"]) if sat.get("sat_id") else
                (f"https://db.satnogs.org/search/?q={norad}" if norad else ""),
                "status": sat.get("status") or "", "transmitters": tx_out, "has_data": bool(self.satnogs["tx"])}

    def satlist_public(self):
        return {"bands": [{"key": k, "name": n} for k, n, _, _ in BANDS], "settings": self.scfg,
                "satnogs_count": len(self.satnogs["tx"]), "error": self.satnogs_error,
                "age_h": round((time.time() - self.satnogs_fetched) / 3600, 1) if self.satnogs_fetched else None}

    # ------------------------------------------------------------ commandes web
    async def satlist_cmd(self, cmd, d, who, ws, toast):
        if not cmd.startswith("sat_"):
            return False
        c = self.scfg
        if cmd == "sat_passes":
            if not self.cfg.get("grid"):
                await toast("Définis le grid de la station (Réglages › Station)")
                return True
            sp = await self.refresh_satpasses(force=bool(d.get("force")))
            await self._safe_send(ws, self.satpasses_public())
            return True
        if cmd == "sat_settings":
            try:
                bands = [b for b in d.get("bands", c["bands"]) if b in {x[0] for x in BANDS}]
                c.update(bands=bands, need_uplink=bool(d.get("need_uplink", c["need_uplink"])),
                         hours=int(d.get("hours", c["hours"])) if int(d.get("hours", c["hours"])) in (12, 24, 48) else 24,
                         min_el=max(0.0, min(80.0, float(d.get("min_el", c["min_el"])))),
                         hide_nogo=bool(d.get("hide_nogo", c["hide_nogo"])))
                if isinstance(d.get("alerts"), dict):
                    a = d["alerts"]
                    c["alerts"] = {"enabled": bool(a.get("enabled")), "minutes": max(1, min(120, int(a.get("minutes", 10)))),
                                   "min_el": max(0.0, min(90.0, float(a.get("min_el", 30)))),
                                   "email": bool(a.get("email")), "ha": bool(a.get("ha"))}
            except (TypeError, ValueError):
                await toast("Valeur invalide")
                return True
            self.save_state()
            await self.refresh_satpasses(force=True)
            await self._safe_send(ws, self.satpasses_public())
            self.broadcast_state()
            if d.get("alerts") is not None:
                await toast("Réglages des passages enregistrés", "ok")
            return True
        if cmd == "sat_info":
            await self._safe_send(ws, self.sat_info(str(d.get("key", ""))))
            return True
        if cmd == "sat_refresh":
            await toast("Téléchargement des fréquences (SatNOGS) et des orbites (CelesTrak)…", "ok")
            await self.fetch_satnogs()
            await self.fetch_tle()
            await self.refresh_satpasses(force=True)
            await self._safe_send(ws, self.satpasses_public())
            return True
        return False
