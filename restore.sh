#!/usr/bin/env bash
# =====================================================================
#  RotorWeb — restaurer une sauvegarde des réglages / restore a settings backup
#
#      sudo /opt/rotorweb/restore.sh  fichier.rwbackup
#
#  La sauvegarde se crée dans la page web (Réglages ▸ Système ▸ Sauvegarde) ou avec :
#      sudo /opt/rotorweb/restore.sh --create  fichier.rwbackup
#  Les réglages actuels sont gardés à côté (config.json.avant-restauration-…).
# =====================================================================
set -euo pipefail
APP_DIR=/opt/rotorweb; SVC=rotorweb; USR=rotorweb
[[ $EUID -eq 0 ]] || { echo "sudo $0 $*"; exit 1; }
[[ -d "$APP_DIR/venv" ]] || { echo "RotorWeb n'est pas installé / not installed : sudo ./install.sh"; exit 1; }
ACTION=restore
if [[ "${1:-}" == "--create" ]]; then ACTION=create; shift; fi
FILE="${1:-}"
[[ -n "$FILE" ]] || { sed -n '4,9p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
FILE=$(readlink -f "$FILE")

if [[ "$ACTION" == "create" ]]; then
  (cd "$APP_DIR" && "$APP_DIR/venv/bin/python" -m rotorweb.backup create "$FILE" --config "$APP_DIR/config.json" </dev/tty)
  exit $?
fi

[[ -f "$FILE" ]] || { echo "Fichier introuvable / file not found : $FILE"; exit 1; }
WAS=0; systemctl is-active --quiet "$SVC" && WAS=1
set +e
(cd "$APP_DIR" && "$APP_DIR/venv/bin/python" -m rotorweb.backup restore "$FILE" --config "$APP_DIR/config.json" </dev/tty)
RC=$?
set -e
chown "$USR:$USR" "$APP_DIR"/config.json* "$APP_DIR"/state.json* 2>/dev/null || true
chmod 600 "$APP_DIR/config.json"
if [[ $RC -eq 0 ]]; then
  echo "==> Redémarrage de RotorWeb / Restarting RotorWeb"
  systemctl restart "$SVC"; sleep 3
  systemctl is-active --quiet "$SVC" && echo "✔ OK" || echo "⚠ journalctl -u $SVC -n 50 --no-pager"
  DRV=$(python3 -c "import json;print(json.load(open('$APP_DIR/config.json')).get('rotor',{}).get('driver',''))")
  [[ -e /dev/rotor || "$DRV" == "hamlib" || "$DRV" == "gpio" ]] || \
    echo "⚠ /dev/rotor absent : branche le contrôleur puis  sudo $APP_DIR/detect.sh  /  plug the controller then run detect.sh"
elif [[ $WAS -eq 1 ]]; then
  systemctl start "$SVC" 2>/dev/null || true
fi
exit $RC
