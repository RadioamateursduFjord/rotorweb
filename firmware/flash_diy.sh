#!/usr/bin/env bash
# =====================================================================
#  RotorWeb — compile et téléverse le croquis « RotorWeb DIY » sur un Arduino
#  Utilisation :  sudo /opt/rotorweb/firmware/flash_diy.sh
# =====================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKETCH="$HERE/rotorweb_diy"
SVC=rotorweb
G='\033[1;32m'; Y='\033[1;33m'; R='\033[1;31m'; B='\033[1;36m'; N='\033[0m'
ask(){ local p="$1" d="${2:-}" a; read -r -p "$(echo -e "${B}?${N} $p ${d:+[$d]} : ")" a </dev/tty; echo "${a:-$d}"; }
yesno(){ local p="$1" d="${2:-n}" a; read -r -p "$(echo -e "${B}?${N} $p (o/n) [$d] : ")" a </dev/tty; a="${a:-$d}"; [[ "$a" =~ ^[oOyY] ]]; }
[[ $EUID -eq 0 ]] || { echo "Lance avec sudo"; exit 1; }
[[ -f "$SKETCH/rotorweb_diy.ino" ]] || { echo -e "${R}Croquis introuvable : $SKETCH${N}"; exit 1; }

echo -e "${B}==> Outils : arduino-cli${N}"
apt-get install -y -qq curl >/dev/null
if ! command -v arduino-cli >/dev/null; then
  curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR=/usr/local/bin sh
fi
arduino-cli core update-index >/dev/null
arduino-cli core install arduino:avr >/dev/null
echo -e "${G}✔ arduino-cli prêt${N}"

echo
echo -e "${Y}Avant de compiler, vérifie en haut du croquis :${N}"
echo "  - les broches des relais (PIN_CW, PIN_CCW, PIN_UP, PIN_DOWN)"
echo "  - l'entrée du potentiomètre (POT_AZ, POT_EL)"
echo "  - RELAY_ACTIVE_LOW (true pour la plupart des modules relais)"
if yesno "Ouvrir le croquis dans l'éditeur nano ?" "o"; then
  nano "$SKETCH/rotorweb_diy.ino" </dev/tty >/dev/tty
fi

echo -e "${B}==> Type d'Arduino${N}"
echo "  1) Arduino Nano (ATmega328)"
echo "  2) Arduino Nano (ancien bootloader — clones CH340)"
echo "  3) Arduino Uno"
echo "  4) Arduino Mega 2560"
case "$(ask "Choix" "1")" in
  2) FQBN=arduino:avr:nano:cpu=atmega328old ;;
  3) FQBN=arduino:avr:uno ;;
  4) FQBN=arduino:avr:mega:cpu=atmega2560 ;;
  *) FQBN=arduino:avr:nano:cpu=atmega328 ;;
esac

echo -e "${B}==> Compilation (${FQBN})${N}"
arduino-cli compile --fqbn "$FQBN" "$SKETCH" || { echo -e "${R}✖ Échec de compilation${N}"; exit 1; }
echo -e "${G}✔ Compilation réussie${N}"

PORT=/dev/rotor; [[ -e $PORT ]] || PORT=$(ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null | head -1 || true)
PORT=$(ask "Port de l'Arduino" "$PORT")
yesno "Téléverser maintenant sur $PORT ?" "o" || exit 0

systemctl stop "$SVC" 2>/dev/null || true
if arduino-cli upload --fqbn "$FQBN" -p "$PORT" "$SKETCH"; then
  echo -e "${G}✔ Croquis RotorWeb DIY téléversé${N}"
  echo "  Dans la page RotorWeb : onglet Réglage → pilote « Bidouille : Arduino RotorWeb », puis la calibration."
else
  echo -e "${R}✖ Échec du téléversement (essaie l'option « ancien bootloader » pour les clones)${N}"
fi
systemctl start "$SVC" 2>/dev/null || true
