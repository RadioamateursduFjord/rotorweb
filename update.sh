#!/usr/bin/env bash
# =====================================================================
#  RotorWeb — mise à jour / update
#  Garde la configuration, les comptes, les horaires, les préréglages et la calibration.
#  Keeps the configuration, accounts, schedules, presets and calibration.
#
#  Utilisation / Usage : décompresse la nouvelle version dans un dossier, puis / unzip the new version, then
#      cd rotorweb-vX.X && sudo ./update.sh
#  Voir / See : CHANGELOG.md et le guide MISE-A-JOUR / UPDATE (PDF)
# =====================================================================
set -euo pipefail
APP_DIR=/opt/rotorweb; SVC=rotorweb; USR=rotorweb
HELPER=/usr/local/sbin/rotorweb-helper; SUDOERS=/etc/sudoers.d/rotorweb; PUBDIR=/usr/local/share/rotorweb
NONINT=${RW_NONINTERACTIVE:-0}      # 1 = lancé par la mise à jour en ligne (aucune question)
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LNG=$(python3 -c "import json;print(json.load(open('$APP_DIR/config.json')).get('lang','fr'))" 2>/dev/null || echo fr)
t(){ if [[ "$LNG" == en ]]; then echo "$2"; else echo "$1"; fi; }
G='\033[1;32m'; Y='\033[1;33m'; B='\033[1;36m'; N='\033[0m'
step(){ echo -e "${B}==> $*${N}"; }
ok(){ echo -e "${G}✔ $*${N}"; }
warn(){ echo -e "${Y}⚠ $*${N}"; }

[[ $EUID -eq 0 ]] || { echo "$(t "Lance avec sudo" "Run with sudo") :  sudo ./update.sh"; exit 1; }
[[ -d "$APP_DIR" ]] || { echo "$(t "RotorWeb n'est pas installé. Lance d'abord : sudo ./install.sh" "RotorWeb is not installed. First run: sudo ./install.sh")"; exit 1; }

# Retour à la version précédente / roll back :  sudo /opt/rotorweb/update.sh --rollback
if [[ "${1:-}" == "--rollback" ]]; then
  BAK=$(ls -1dt /opt/rotorweb-backup-* 2>/dev/null | head -n 1 || true)
  [[ -n "$BAK" ]] || { warn "$(t "Aucune copie de sécurité trouvée dans /opt" "No backup found in /opt")"; exit 1; }
  step "$(t "Retour à" "Rolling back to") $BAK"
  systemctl stop "$SVC" || true
  rm -rf "$APP_DIR/rotorweb"
  cp -a "$BAK/rotorweb" "$APP_DIR/"
  cp -a "$BAK"/*.json "$APP_DIR/" 2>/dev/null || true
  cp -a "$BAK"/*.sh "$BAK/requirements.txt" "$APP_DIR/" 2>/dev/null || true
  "$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt" || true
  chown -R "$USR:$USR" "$APP_DIR"
  systemctl start "$SVC"; sleep 3
  systemctl is-active --quiet "$SVC" && ok "$(t "Ancienne version rétablie" "Old version restored") ($(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$APP_DIR/rotorweb/server.py"))" \
    || warn "journalctl -u $SVC -n 50 --no-pager"
  exit 0
fi
[[ "$SRC_DIR" == "$APP_DIR" ]] && { echo "$(t "Lance update.sh depuis le dossier de la NOUVELLE version, pas depuis" "Run update.sh from the folder of the NEW version, not from") $APP_DIR"; exit 1; }

NEW_V=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$SRC_DIR/rotorweb/server.py" 2>/dev/null)
OLD_V=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$APP_DIR/rotorweb/server.py" 2>/dev/null)
step "$(t "Mise à jour RotorWeb" "Updating RotorWeb") v${OLD_V:-?} → v${NEW_V:-?}"

# Copie de sécurité pour revenir en arrière / backup to roll back
BAK="/opt/rotorweb-backup-v${OLD_V:-old}-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BAK"
cp -a "$APP_DIR/rotorweb" "$BAK/" 2>/dev/null || true
cp -a "$APP_DIR"/*.json "$APP_DIR"/*.sh "$APP_DIR/requirements.txt" "$BAK/" 2>/dev/null || true
ls -1dt /opt/rotorweb-backup-* 2>/dev/null | tail -n +4 | xargs -r rm -rf     # garde les 3 plus récentes
ok "$(t "Copie de l'ancienne version" "Copy of the old version") : $BAK"

step "$(t "Arrêt du service" "Stopping the service")"
systemctl stop "$SVC" || true

step "$(t "Copie des nouveaux fichiers (config.json et state.json conservés)" "Copying the new files (config.json and state.json kept)")"
rm -rf "$APP_DIR/rotorweb"
cp -r "$SRC_DIR/rotorweb" "$APP_DIR/"
cp -r "$SRC_DIR/firmware" "$APP_DIR/" 2>/dev/null || true
cp -r "$SRC_DIR/homeassistant" "$APP_DIR/" 2>/dev/null || true
rm -f "$APP_DIR"/GUIDE-*.pdf "$APP_DIR"/UPDATE-*.pdf "$APP_DIR"/MISE-A-JOUR-*.pdf
cp "$SRC_DIR"/*.pdf "$APP_DIR/" 2>/dev/null || true
for f in requirements.txt update.sh uninstall.sh users.sh detect.sh restore.sh README.md README.en.md CHANGELOG.md; do cp "$SRC_DIR/$f" "$APP_DIR/" 2>/dev/null || true; done
chmod +x "$APP_DIR"/*.sh "$APP_DIR"/firmware/*.sh 2>/dev/null || true

if ! grep -q "include-system-site-packages = true" "$APP_DIR/venv/pyvenv.cfg" 2>/dev/null; then
  step "$(t "Recréation de l'environnement Python" "Re-creating the Python environment")"
  rm -rf "$APP_DIR/venv"
  python3 -m venv --system-site-packages "$APP_DIR/venv"
  "$APP_DIR/venv/bin/pip" install -q --upgrade pip
fi
apt-get install -y -qq python3-ephem sudo openssl unzip >/dev/null 2>&1 || true
step "$(t "Dépendances Python" "Python packages")"
"$APP_DIR/venv/bin/pip" install -q --upgrade -r "$APP_DIR/requirements.txt"

# ---- Migrations ------------------------------------------------------
# v2.1 : nouveaux visuels seulement (logo, icônes, couvertures des guides) — rien à migrer.
#        Les migrations ci-dessous restent toutes rejouables : on peut passer de 1.6 ou 2.0 directement à 2.1.
# v1.7 / v2.0 : actions système (arrêt / redémarrage du Pi, mises à jour en ligne vérifiées)
install -o root -g root -m 755 "$SRC_DIR/system/rotorweb-helper" "$HELPER"
install -d -o root -g root -m 755 "$PUBDIR"
install -o root -g root -m 644 "$SRC_DIR/rotorweb/release.pub" "$PUBDIR/release.pub"
chown root:root "$HELPER"; chmod 755 "$HELPER"
echo "$USR ALL=(root) NOPASSWD: $HELPER" > "$SUDOERS.tmp"; chmod 440 "$SUDOERS.tmp"
if visudo -cf "$SUDOERS.tmp" >/dev/null 2>&1; then mv "$SUDOERS.tmp" "$SUDOERS"; ok "$(t "Boutons Éteindre / Redémarrer le Pi activés" "Shut down / Reboot Pi buttons enabled")"
else rm -f "$SUDOERS.tmp"; warn "$(t "sudoers invalide : boutons d'arrêt du Pi désactivés" "invalid sudoers: Pi power buttons disabled")"; fi

# v1.6.1 → v1.7 : port web < 1024 permis ; CapabilityBoundingSet retiré (il empêchait sudo)
UNIT=/etc/systemd/system/$SVC.service
if [[ -f $UNIT ]]; then
  sed -i '/^CapabilityBoundingSet=/d' "$UNIT"
  grep -q '^AmbientCapabilities=CAP_NET_BIND_SERVICE' "$UNIT" || sed -i 's/^RestartSec=.*/&\nAmbientCapabilities=CAP_NET_BIND_SERVICE/' "$UNIT"
  systemctl daemon-reload
fi

# v1.7 : langue de la station, mode Automatique (WSJT-X) retiré → Manuel
LNG="$LNG" APP_DIR="$APP_DIR" python3 - <<'PY'
import json, os
d = os.environ["APP_DIR"]
p = os.path.join(d, "config.json")
cfg = json.load(open(p))
cfg.setdefault("lang", os.environ.get("LNG", "fr"))
json.dump(cfg, open(p, "w"), indent=2, ensure_ascii=False)
sp = os.path.join(d, "state.json")
if os.path.exists(sp):
    st = json.load(open(sp))
    if st.get("mode") == "auto":
        st["mode"] = "manual"
        print("  → mode Automatique (WSJT-X) retiré : la station repasse en mode Manuel")
    json.dump(st, open(sp, "w"), indent=2, ensure_ascii=False)
PY
chown -R "$USR:$USR" "$APP_DIR"
chmod 600 "$APP_DIR/config.json"

step "$(t "Redémarrage" "Restarting")"
systemctl start "$SVC"
sleep 3
if systemctl is-active --quiet "$SVC"; then ok "$(t "RotorWeb mis à jour et redémarré" "RotorWeb updated and restarted") (v${NEW_V})"
else warn "$(t "Problème au démarrage" "Startup problem") : journalctl -u $SVC -n 50 --no-pager"
     echo "   $(t "Pour revenir à l'ancienne version" "To roll back to the old version") : sudo $APP_DIR/update.sh --rollback  ($(t "ou voir le guide" "or see the guide"))"; fi
NB=$(python3 -c "import json;print(len(json.load(open('$APP_DIR/config.json')).get('users',{})))")
if [[ "$NB" -eq 0 && "$NONINT" != "1" ]]; then
  echo
  warn "$(t "La page web demande un compte. Crée-en un maintenant :" "The web page needs an account. Create one now:")"
  read -r -p "  $(t "Nom d'utilisateur" "User name") : " U </dev/tty
  "$APP_DIR/users.sh" add "$U"
fi
echo
echo "  $(t "Nouveautés" "What's new") : $APP_DIR/CHANGELOG.md"
echo "  $(t "Dans le navigateur ou l'app du cellulaire, recharge la page (tire vers le bas) si l'ancienne version reste affichée." \
           "In the browser or the phone app, reload the page (pull down) if the old version is still shown.")"
