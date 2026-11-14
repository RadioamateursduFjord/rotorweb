#!/usr/bin/env bash
# RotorWeb — désinstallation
set -euo pipefail
APP_DIR=/opt/rotorweb; SVC=rotorweb; USR=rotorweb
[[ $EUID -eq 0 ]] || { echo "Lance avec sudo :  sudo ./uninstall.sh"; exit 1; }
read -r -p "Désinstaller RotorWeb ? (o/n) [n] : " a </dev/tty
[[ "${a:-n}" =~ ^[oOyY] ]] || exit 0

systemctl disable --now "$SVC" 2>/dev/null || true
systemctl disable --now rotorweb-rotctld 2>/dev/null || true
rm -f /etc/systemd/system/$SVC.service /etc/systemd/system/rotorweb-rotctld.service
systemctl daemon-reload
rm -f /etc/udev/rules.d/99-rotorweb.rules /usr/local/sbin/rotorweb-helper /etc/sudoers.d/rotorweb; rm -rf /usr/local/share/rotorweb /var/lib/rotorweb-update
udevadm control --reload-rules 2>/dev/null || true

read -r -p "Supprimer aussi la configuration et les préréglages ($APP_DIR) ? (o/n) [n] : " b </dev/tty
if [[ "${b:-n}" =~ ^[oOyY] ]]; then
  rm -rf "$APP_DIR" /opt/rotorweb-backup-*
  userdel "$USR" 2>/dev/null || true
  echo "✔ RotorWeb entièrement supprimé"
else
  echo "✔ Service supprimé. Configuration conservée dans $APP_DIR"
fi
