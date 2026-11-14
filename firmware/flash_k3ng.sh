#!/usr/bin/env bash
# =====================================================================
#  RotorWeb — compilation et flash du firmware K3NG depuis le Raspberry Pi
#  Utilisation :  sudo /opt/rotorweb/firmware/flash_k3ng.sh
#
#  IMPORTANT : le K3NG doit être configuré pour TON matériel
#  (broches des relais, potentiomètre/capteur de position, calibration).
#  Ce script ouvre les fichiers de configuration pour que tu les ajustes.
# =====================================================================
set -euo pipefail
BUILD=/opt/rotorweb/k3ng-build
REPO=https://github.com/k3ng/k3ng_rotator_controller.git
SVC=rotorweb
G='\033[1;32m'; Y='\033[1;33m'; R='\033[1;31m'; B='\033[1;36m'; N='\033[0m'
ask(){ local p="$1" d="${2:-}" a; read -r -p "$(echo -e "${B}?${N} $p ${d:+[$d]} : ")" a </dev/tty; echo "${a:-$d}"; }
yesno(){ local p="$1" d="${2:-n}" a; read -r -p "$(echo -e "${B}?${N} $p (o/n) [$d] : ")" a </dev/tty; a="${a:-$d}"; [[ "$a" =~ ^[oOyY] ]]; }
[[ $EUID -eq 0 ]] || { echo "Lance avec sudo"; exit 1; }

echo -e "${B}==> Outils : git et arduino-cli${N}"
apt-get install -y -qq git curl >/dev/null
if ! command -v arduino-cli >/dev/null; then
  curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR=/usr/local/bin sh
fi
arduino-cli core update-index >/dev/null
arduino-cli core install arduino:avr >/dev/null
echo -e "${G}✔ arduino-cli prêt${N}"

echo -e "${B}==> Code source K3NG${N}"
if [[ -d "$BUILD/.git" ]]; then
  if yesno "Une copie existe déjà (avec tes réglages). Garder tes réglages (ne pas télécharger à nouveau) ?" "o"; then :; else
    rm -rf "$BUILD"; git clone -q --depth 1 "$REPO" "$BUILD"; fi
else
  git clone -q --depth 1 "$REPO" "$BUILD"
fi
SKETCH="$BUILD/k3ng_rotator_controller"
[[ -f "$SKETCH/k3ng_rotator_controller.ino" ]] || { echo -e "${R}Sketch introuvable dans $SKETCH${N}"; exit 1; }

# Mode Yaesu GS-232 obligatoire pour RotorWeb
FEAT="$SKETCH/rotator_features.h"
if ! grep -qE '^\s*#define\s+FEATURE_YAESU_EMULATION' "$FEAT"; then
  sed -i -E 's|^\s*//\s*(#define\s+FEATURE_YAESU_EMULATION)|\1|' "$FEAT"
fi
sed -i -E 's|^\s*(#define\s+FEATURE_EASYCOM_EMULATION)|// \1|' "$FEAT"
grep -qE '^\s*#define\s+FEATURE_YAESU_EMULATION' "$FEAT" \
  && echo -e "${G}✔ Émulation Yaesu GS-232 activée${N}" \
  || echo -e "${Y}⚠ Vérifie à la main que FEATURE_YAESU_EMULATION est activé dans rotator_features.h${N}"

echo
echo -e "${Y}Configuration de ton matériel :${N}"
echo "  rotator_features.h : fonctions (élévation, écran, etc.)"
echo "  rotator_pins.h     : broches des relais et du capteur de position"
echo "  rotator_settings.h : calibration, vitesse série, limites"
if yesno "Ouvrir ces fichiers maintenant dans l'éditeur nano ?" "o"; then
  for f in rotator_features.h rotator_pins.h rotator_settings.h; do
    echo "   → $f  (Ctrl+O pour enregistrer, Ctrl+X pour quitter)"; sleep 1
    nano "$SKETCH/$f" </dev/tty >/dev/tty
  done
fi

echo -e "${B}==> Type d'Arduino${N}"
echo "  1) Arduino Mega 2560 (recommandé pour K3NG)"
echo "  2) Arduino Nano (ATmega328)"
echo "  3) Arduino Nano (ancien bootloader — clones CH340)"
echo "  4) Arduino Uno"
case "$(ask "Choix" "1")" in
  2) FQBN=arduino:avr:nano:cpu=atmega328 ;;
  3) FQBN=arduino:avr:nano:cpu=atmega328old ;;
  4) FQBN=arduino:avr:uno ;;
  *) FQBN=arduino:avr:mega:cpu=atmega2560 ;;
esac

echo -e "${B}==> Compilation (${FQBN})${N}"
if ! arduino-cli compile --fqbn "$FQBN" "$SKETCH"; then
  echo -e "${R}✖ Échec de compilation.${N}"
  echo "  - Sur Nano/Uno, la mémoire est limitée : désactive des fonctions dans rotator_features.h"
  echo "  - Une bibliothèque manque ? installe-la :  arduino-cli lib install \"Nom\""
  exit 1
fi
echo -e "${G}✔ Compilation réussie${N}"

PORT=/dev/rotor; [[ -e $PORT ]] || PORT=$(ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null | head -1 || true)
PORT=$(ask "Port de l'Arduino" "$PORT")
yesno "Téléverser maintenant sur $PORT ?" "o" || exit 0

systemctl stop "$SVC" 2>/dev/null || true   # libère le port série
if arduino-cli upload --fqbn "$FQBN" -p "$PORT" "$SKETCH"; then
  echo -e "${G}✔ Firmware K3NG flashé${N}"
else
  echo -e "${R}✖ Échec du téléversement (mauvais type d'Arduino ? essaie l'option « ancien bootloader »)${N}"
fi
systemctl start "$SVC" 2>/dev/null || true
