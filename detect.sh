#!/usr/bin/env bash
# =====================================================================
#  RotorWeb — changer / redétecter le contrôleur du rotor
#  Change / re-detect the rotor controller
#
#      sudo /opt/rotorweb/detect.sh
#
#  Même assistant que Réglages ▸ Contrôleur dans la page web, utile si la page ne répond plus.
#  Same wizard as Settings ▸ Controller in the web page, handy if the page does not answer.
#  L'ancienne configuration est copiée (config.json.bak-…) et gardée dans le profil « ↩ Précédent ».
# =====================================================================
set -euo pipefail
APP_DIR=/opt/rotorweb; SVC=rotorweb; USR=rotorweb
[[ $EUID -eq 0 ]] || { echo "sudo $0"; exit 1; }
[[ -d "$APP_DIR/venv" ]] || { echo "RotorWeb n'est pas installé / RotorWeb is not installed : sudo ./install.sh"; exit 1; }

WAS_ACTIVE=0
if systemctl is-active --quiet "$SVC"; then
  WAS_ACTIVE=1
  echo "==> Arrêt de RotorWeb pendant la détection / Stopping RotorWeb during detection"
  systemctl stop "$SVC"
fi
systemctl stop rotorweb-rotctld 2>/dev/null || true     # libère le port série si Hamlib l'utilisait

set +e
(cd "$APP_DIR" && "$APP_DIR/venv/bin/python" -m rotorweb.detect --config "$APP_DIR/config.json" "$@" </dev/tty)
RC=$?
set -e
chown "$USR:$USR" "$APP_DIR"/config.json* 2>/dev/null || true
chmod 600 "$APP_DIR/config.json"

DRV=$(python3 -c "import json;print(json.load(open('$APP_DIR/config.json')).get('rotor',{}).get('driver',''))" 2>/dev/null || true)
[[ "$DRV" == "hamlib" ]] && systemctl start rotorweb-rotctld 2>/dev/null || true
if [[ $WAS_ACTIVE -eq 1 || $RC -eq 0 ]]; then
  echo "==> Redémarrage de RotorWeb / Restarting RotorWeb"
  systemctl start "$SVC"
  sleep 3
  systemctl is-active --quiet "$SVC" && echo "✔ OK" || echo "⚠ journalctl -u $SVC -n 50 --no-pager"
fi
if grep -q -- "--simulate" /etc/systemd/system/$SVC.service 2>/dev/null && [[ $RC -eq 0 ]]; then
  echo
  echo "⚠ Le service tourne encore en mode SIMULATION. Pour utiliser le vrai contrôleur / The service still runs in SIMULATION mode. To use the real controller:"
  echo "    sudo sed -i 's/ --simulate//' /etc/systemd/system/$SVC.service && sudo systemctl daemon-reload && sudo systemctl restart $SVC"
fi
exit $RC
