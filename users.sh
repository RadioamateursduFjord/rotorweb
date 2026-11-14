#!/usr/bin/env bash
# RotorWeb — gestion des comptes de la page web
#   sudo /opt/rotorweb/users.sh list
#   sudo /opt/rotorweb/users.sh add NOM       (crée un compte)
#   sudo /opt/rotorweb/users.sh passwd NOM    (change le mot de passe)
#   sudo /opt/rotorweb/users.sh del NOM       (supprime un compte)
APP_DIR=/opt/rotorweb
[[ $EUID -eq 0 ]] || { echo "Lance avec sudo :  sudo $0 $*"; exit 1; }
[[ $# -ge 1 ]] || { sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
cd "$APP_DIR" || exit 1
"$APP_DIR/venv/bin/python" -m rotorweb.auth "$@" --config "$APP_DIR/config.json"
rc=$?
chown rotorweb:rotorweb "$APP_DIR/config.json" 2>/dev/null; chmod 600 "$APP_DIR/config.json"
exit $rc
