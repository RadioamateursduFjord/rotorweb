# -*- coding: utf-8 -*-
"""
RotorWeb — mises à jour en ligne (GitHub Releases).

Chaque version publiée (tools/release.sh) contient trois fichiers :
  rotorweb-vX.Y.zip      le paquet
  release.json           version, date, nouveautés, nom et SHA-256 du zip
  release.json.sig       signature Ed25519 de release.json (clé privée gardée par l'éditeur)

Le Raspberry Pi vérifie la signature avec la clé publique release.pub AVANT d'installer
quoi que ce soit. L'installation elle-même est faite par /usr/local/sbin/rotorweb-helper
(root), qui revérifie tout avec sa propre copie de la clé, lance update.sh hors du service
et revient automatiquement à l'ancienne version si la nouvelle ne démarre pas.

Mélangé (mixin) dans la classe Controller de server.py.
"""
import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import aiohttp

log = logging.getLogger("rotorweb")

DEFAULT_REPO = "RadioamateursduFjord/rotorweb"
GITHUB_LATEST = "https://api.github.com/repos/{repo}/releases/latest"
PUBKEY = Path(os.environ.get("ROTORWEB_RELEASE_PUB") or Path(__file__).resolve().parent / "release.pub")   # variable : tests seulement
DEFAULT_UPDATE = {"repo": DEFAULT_REPO, "url": "", "check_hours": 24}


def vtuple(v):
    """« 1.10 » > « 1.9 » : comparaison numérique."""
    return tuple(int(x) for x in re.findall(r"\d+", str(v or "0"))[:4]) or (0,)


def verify_signature(data: bytes, sig: bytes, pubkey=PUBKEY):
    """Vérifie une signature Ed25519. Avec la bibliothèque cryptography si présente, sinon openssl (≥ 3.0)."""
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        key = load_pem_public_key(Path(pubkey).read_bytes())
        try:
            key.verify(sig, data)
            return True
        except Exception:
            return False
    except ImportError:
        pass
    with tempfile.TemporaryDirectory() as d:
        fd, fs = Path(d) / "data", Path(d) / "sig"
        fd.write_bytes(data)
        fs.write_bytes(sig)
        r = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(pubkey), "-rawin",
                            "-in", str(fd), "-sigfile", str(fs)], capture_output=True, text=True)
        return r.returncode == 0 and "Success" in (r.stdout + r.stderr)


class UpdaterMixin:
    # ------------------------------------------------------------ init
    def updater_init(self):
        self.upd = {"checking": False, "last_check": 0.0, "error": "", "latest": None, "busy": False,
                    "step": "", "result": None}

    def updater_start(self):
        asyncio.create_task(self._update_loop())

    @property
    def ucfg(self):
        u = self.cfg.setdefault("update", {})
        for k, v in DEFAULT_UPDATE.items():
            u.setdefault(k, v)
        return u

    def _upd_dir(self):
        return self.config_path.with_name("update")

    # ------------------------------------------------------------ résultat d'une mise à jour précédente
    def _read_update_result(self):
        """Résultat écrit par rotorweb-helper environ 15 s après le redémarrage qui suit une mise à jour."""
        p = self.config_path.with_name("update-result.json")
        if not p.exists():
            return False
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            r = {}
        p.rename(p.with_suffix(".json.seen"))
        r["seen_at"] = time.time()
        self.upd["result"] = r
        return True

    def _announce_result(self):
        r = self.upd.get("result")
        if not r:
            return
        if r.get("ok"):
            self.tlog("system", "info", f"✔ Mise à jour réussie : v{r.get('from', '?')} → v{r.get('to', self.version)}")
            self.send_email(f"✔ RotorWeb mis à jour : v{r.get('to', self.version)}",
                            f"La mise à jour de v{r.get('from', '?')} à v{r.get('to', self.version)} est terminée.",
                            kind="mise_a_jour")
        else:
            self.tlog("system", "info", f"⚠ Mise à jour vers v{r.get('to', '?')} échouée : retour à v{self.version}",
                      blocked=True)
            self.send_email(f"⚠ Mise à jour de RotorWeb échouée (v{r.get('to', '?')})",
                            f"La nouvelle version n'a pas démarré. RotorWeb est revenu automatiquement à v{self.version}.\n"
                            f"Détails : {r.get('detail', '')}", kind="alerte")

    # ------------------------------------------------------------ vérification
    async def _fetch_release(self):
        """Télécharge release.json et sa signature. Retourne (info, base_url des fichiers)."""
        u = self.ucfg
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30),
                                         headers={"User-Agent": f"RotorWeb/{self.version}"}) as s:
            if u.get("url"):
                rel_url = u["url"]
                base = rel_url.rsplit("/", 1)[0]
                assets = None
            else:
                async with s.get(GITHUB_LATEST.format(repo=u.get("repo") or DEFAULT_REPO),
                                 headers={"Accept": "application/vnd.github+json"}) as r:
                    if r.status == 404:
                        raise ValueError("aucune version publiée sur GitHub")
                    r.raise_for_status()
                    gh = await r.json()
                assets = {a["name"]: a["browser_download_url"] for a in gh.get("assets", [])}
                if "release.json" not in assets or "release.json.sig" not in assets:
                    raise ValueError("version GitHub incomplète (release.json absent)")
                rel_url, base = assets["release.json"], None
            async with s.get(rel_url) as r:
                r.raise_for_status()
                data = await r.read()
            sig_url = assets["release.json.sig"] if assets else rel_url + ".sig"
            async with s.get(sig_url) as r:
                r.raise_for_status()
                sig = await r.read()
        if not await self.loop.run_in_executor(None, verify_signature, data, sig):
            raise ValueError("signature invalide : version refusée")
        info = json.loads(data.decode("utf-8"))
        zip_url = (assets or {}).get(info.get("zip")) or f"{base}/{info.get('zip')}"
        return info, data, sig, zip_url

    async def check_updates(self, manual=False):
        if self.upd["checking"]:
            return
        self.upd["checking"] = True
        self.broadcast({"type": "update", "update": self.update_public()})
        try:
            info, data, sig, zip_url = await self._fetch_release()
            info["zip_url"] = zip_url
            self.upd.update(latest=info, error="", last_check=time.time())
            self._latest_raw = (data, sig)
            newer = vtuple(info.get("version")) > vtuple(self.version)
            if newer:
                v = info["version"]
                if self.state.get("update_notified") != v:
                    self.state["update_notified"] = v
                    self.save_state()
                    self.tlog("system", "info", f"⬆ Nouvelle version disponible : v{v}")
                    notes = (info.get("notes") or {}).get(self.cfg.get("lang", "fr")) or (info.get("notes") or {}).get("fr", "")
                    self.send_email(f"⬆ Nouvelle version de RotorWeb disponible : v{v}",
                                    f"Version installée : v{self.version}\nNouvelle version : v{v}\n\n"
                                    f"Pour l'installer : page RotorWeb → Réglages ▸ Système → Mettre à jour.\n\n{notes}",
                                    kind="mise_a_jour")
            elif manual:
                self.tlog("system", "info", f"RotorWeb est à jour (v{self.version})")
        except Exception as e:
            self.upd.update(error=str(e) or type(e).__name__, last_check=time.time())
            if manual:
                self.tlog("system", "info", f"Vérification des mises à jour impossible : {self.upd['error']}", blocked=True)
        finally:
            self.upd["checking"] = False
        self.broadcast({"type": "update", "update": self.update_public()})
        if self.ha:
            self.ha.sync()

    async def _update_loop(self):
        for _ in range(18):                  # 3 minutes : attend le résultat d'une mise à jour
            await asyncio.sleep(10)
            if self._read_update_result():
                self._announce_result()
                self.broadcast({"type": "update", "update": self.update_public()})
                break
        while True:
            hours = max(1.0, float(self.ucfg.get("check_hours") or 24))
            if time.time() - self.upd["last_check"] > hours * 3600:
                await self.check_updates()
            await asyncio.sleep(600)

    def update_available(self):
        lt = self.upd.get("latest")
        return bool(lt and vtuple(lt.get("version")) > vtuple(self.version))

    def update_public(self):
        lt = self.upd.get("latest") or {}
        return {"current": self.version, "latest": lt.get("version"), "date": lt.get("date"),
                "notes": lt.get("notes") or {}, "available": self.update_available(),
                "checking": self.upd["checking"], "busy": self.upd["busy"], "step": self.upd["step"],
                "last_check": self.upd["last_check"], "error": self.upd["error"],
                "repo": self.ucfg.get("repo"), "url": self.ucfg.get("url"),
                "result": self.upd.get("result"),
                "can_install": self.simulate or os.path.exists("/usr/local/sbin/rotorweb-helper")}

    # ------------------------------------------------------------ installation
    def _step(self, step):
        self.upd["step"] = step
        self.broadcast({"type": "update", "update": self.update_public()})

    async def install_update(self, who, toast):
        if self.upd["busy"]:
            await toast("Mise à jour déjà en cours")
            return
        if not self.update_available():
            await toast("Aucune nouvelle version à installer")
            return
        if not self.simulate and not os.path.exists("/usr/local/sbin/rotorweb-helper"):
            await toast("Commande système non installée : relance sudo ./update.sh", "error")
            return
        info = self.upd["latest"]
        self.upd["busy"] = True
        try:
            self.tlog("web", "info", f"⬆ Mise à jour vers v{info['version']} lancée", peer=who)
            # 1. téléchargement
            self._step("download")
            d = self._upd_dir()
            d.mkdir(exist_ok=True)
            for f in d.iterdir():
                if f.is_file():
                    f.unlink()
            data, sig = self._latest_raw
            (d / "release.json").write_bytes(data)
            (d / "release.json.sig").write_bytes(sig)
            zpath = d / info["zip"]
            h = hashlib.sha256()
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300),
                                             headers={"User-Agent": f"RotorWeb/{self.version}"}) as s:
                async with s.get(info["zip_url"]) as r:
                    r.raise_for_status()
                    with open(zpath, "wb") as fh:
                        async for chunk in r.content.iter_chunked(65536):
                            fh.write(chunk)
                            h.update(chunk)
            # 2. vérification
            self._step("verify")
            if h.hexdigest() != info.get("sha256"):
                raise ValueError("le fichier téléchargé ne correspond pas à la signature (SHA-256)")
            # 3. antenne au repos et arrêt
            self._step("park")
            if self.state["operating"] and not self.state["estop"] and self.connected:
                az = self.rest_az()
                ok, _ = self.request_move("system", az, 0 if self.cfg.get("elevation") else None,
                                          label=f"Repos avant mise à jour ({round(az)}°)")
                t0 = time.time()
                while ok and self.target_az is not None and time.time() - t0 < 90:
                    await asyncio.sleep(1)
            self.request_stop("system", why="mise à jour")
            self.save_state()
            self.save_config()
            # 4. installation (hors du service, par le script système)
            self._step("install")
            await asyncio.sleep(1)
            if self.simulate:
                self.tlog("system", "info", f"[SIMULATION] installation de v{info['version']} vérifiée (non exécutée)")
                self.upd["step"] = "simulated"
                return
            r = await self.loop.run_in_executor(None, lambda: subprocess.run(
                ["sudo", "-n", "/usr/local/sbin/rotorweb-helper", "update", str(d)],
                capture_output=True, text=True, timeout=120))
            if r.returncode != 0:
                raise ValueError((r.stderr or r.stdout or "échec du script système").strip()[-300:])
            self.tlog("system", "info", "Installation en cours : RotorWeb va redémarrer…")
        except Exception as e:
            self.upd["error"] = str(e) or type(e).__name__
            self.upd["step"] = "error"
            self.tlog("system", "info", f"⚠ Mise à jour impossible : {self.upd['error']}", blocked=True)
            await toast(f"Mise à jour impossible : {self.upd['error']}", "error")
        finally:
            self.upd["busy"] = False
            self.broadcast({"type": "update", "update": self.update_public()})

    # ------------------------------------------------------------ commandes web
    async def updater_cmd(self, cmd, d, who, ws, toast):
        if cmd == "update_check":
            await self.check_updates(manual=True)
            if self.upd["error"]:
                await toast(f"Vérification impossible : {self.upd['error']}")
            elif not self.update_available():
                await toast(f"RotorWeb est à jour (v{self.version})", "ok")
            return True
        if cmd == "update_install":
            asyncio.create_task(self.install_update(who, toast))
            return True
        if cmd == "update_source":
            u = self.ucfg
            repo = str(d.get("repo", u["repo"])).strip()
            if repo and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
                await toast("Dépôt invalide (forme : compte/depot)")
                return True
            u["repo"] = repo or DEFAULT_REPO
            u["url"] = str(d.get("url", "")).strip()
            self.save_config()
            self.upd["latest"] = None
            await toast("Source des mises à jour enregistrée", "ok")
            self.broadcast({"type": "update", "update": self.update_public()})
            return True
        if cmd == "update_dismiss_result":
            self.upd["result"] = None
            self.broadcast({"type": "update", "update": self.update_public()})
            return True
        return False
