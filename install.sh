#!/usr/bin/env bash
# =====================================================================
#  RotorWeb — Installation sur Raspberry Pi / Installation on a Raspberry Pi
#  Utilisation / Usage :  sudo ./install.sh
# =====================================================================
set -euo pipefail

APP_DIR=/opt/rotorweb
SVC=rotorweb
USR=rotorweb
UDEV_RULE=/etc/udev/rules.d/99-rotorweb.rules
HELPER=/usr/local/sbin/rotorweb-helper
SUDOERS=/etc/sudoers.d/rotorweb
PUBDIR=/usr/local/share/rotorweb
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RW_VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$SRC_DIR/rotorweb/server.py" 2>/dev/null); RW_VERSION=${RW_VERSION:-?}   # version lue dans le code

G='\033[1;32m'; Y='\033[1;33m'; R='\033[1;31m'; B='\033[1;36m'; N='\033[0m'
LNG=fr
t(){ if [[ "$LNG" == en ]]; then echo "$2"; else echo "$1"; fi; }      # t "français" "english"
step(){ echo -e "\n${B}==> $*${N}"; }
ok(){ echo -e "${G}✔ $*${N}"; }
warn(){ echo -e "${Y}⚠ $*${N}"; }
die(){ echo -e "${R}✖ $*${N}"; exit 1; }
ask(){ local p="$1" d="${2:-}" a; read -r -p "$(echo -e "${B}?${N} $p ${d:+[$d]} : ")" a </dev/tty; echo "${a:-$d}"; }
yesno(){ local p="$1" d="${2:-n}" a yn; yn=$(t "o/n" "y/n"); read -r -p "$(echo -e "${B}?${N} $p ($yn) [$d] : ")" a </dev/tty; a="${a:-$d}"; [[ "$a" =~ ^[oOyY] ]]; }

[[ $EUID -eq 0 ]] || die "Lance le script avec sudo / Run with sudo :  sudo ./install.sh"

clear || true
echo -e "${G}"
echo "  ____       _              __        __   _     "
echo " |  _ \ ___ | |_ ___  _ __  \ \      / /__| |__  "
echo " | |_) / _ \| __/ _ \| '__|  \ \ /\ / / _ \ '_ \ "
echo " |  _ < (_) | || (_) | |      \ V  V /  __/ |_) |"
echo " |_| \_\___/ \__\___/|_|       \_/\_/ \___|_.__/  v$RW_VERSION"
echo -e "${N}"
# Langue de l'installation (et langue par défaut de la station)
if [[ -f "$APP_DIR/config.json" ]]; then
  OLD_LNG=$(python3 -c "import json;print(json.load(open('$APP_DIR/config.json')).get('lang','fr'))" 2>/dev/null || echo fr)
else OLD_LNG=fr; fi
echo "   1) Français"
echo "   2) English"
read -r -p "$(echo -e "${B}?${N} Langue / Language [$([[ $OLD_LNG == en ]] && echo 2 || echo 1)] : ")" a </dev/tty
case "${a:-$([[ $OLD_LNG == en ]] && echo 2 || echo 1)}" in 2|e|E|en) LNG=en ;; *) LNG=fr ;; esac
echo
echo "  $(t "Contrôle de rotor par page web : K3NG, GS-232, Rot2Prog, DCU-1, Hamlib, bidouilles" \
           "Web rotor control: K3NG, GS-232, Rot2Prog, DCU-1, Hamlib, DIY builds")"
echo
# Réinstallation à partir d'une sauvegarde (.rwbackup créée dans Réglages ▸ Système ▸ Sauvegarde)
RESTORE_FILE=""; RESTORED=0
echo "  $(t "Réinstallation ? Tu peux restaurer une sauvegarde des réglages (fichier .rwbackup)." "Reinstalling? You can restore a settings backup (.rwbackup file).")"
while true; do
  RESTORE_FILE=$(ask "$(t "Chemin du fichier .rwbackup (Entrée = nouvelle installation)" "Path of the .rwbackup file (Enter = new installation)")" "")
  [[ -z "$RESTORE_FILE" ]] && break
  RESTORE_FILE=$(readlink -f "${RESTORE_FILE/#\~/$HOME}" 2>/dev/null || echo "$RESTORE_FILE")
  [[ -f "$RESTORE_FILE" ]] && break
  warn "$(t "Fichier introuvable" "File not found") : $RESTORE_FILE"
done

# ---------------------------------------------------------------
step "1/8 $(t "Installation des dépendances système" "Installing system packages")"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip udev sudo openssl unzip >/dev/null
apt-get install -y -qq python3-ephem >/dev/null 2>&1 || true   # calculs satellites / Lune (sinon installé par pip)
ok "Python $(python3 -V | cut -d' ' -f2) $(t "prêt" "ready")"

# ---------------------------------------------------------------
step "2/8 $(t "Utilisateur de service" "Service user")"
if ! id "$USR" &>/dev/null; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$USR"
fi
usermod -aG dialout "$USR"
ok "$(t "Utilisateur « $USR » (accès au port série via le groupe dialout)" "User “$USR” (serial port access through the dialout group)")"

# ---------------------------------------------------------------
step "3/8 $(t "Copie des fichiers et environnement Python" "Copying files and Python environment")"
systemctl stop "$SVC" 2>/dev/null || true
mkdir -p "$APP_DIR"
rm -rf "$APP_DIR/rotorweb"
cp -r "$SRC_DIR/rotorweb" "$APP_DIR/"
cp "$SRC_DIR/requirements.txt" "$APP_DIR/"
cp -r "$SRC_DIR/firmware" "$APP_DIR/" 2>/dev/null || true
cp -r "$SRC_DIR/homeassistant" "$APP_DIR/" 2>/dev/null || true
rm -f "$APP_DIR"/GUIDE-*.pdf "$APP_DIR"/UPDATE-*.pdf "$APP_DIR"/MISE-A-JOUR-*.pdf
cp "$SRC_DIR"/*.pdf "$APP_DIR/" 2>/dev/null || true
for f in update.sh uninstall.sh users.sh detect.sh restore.sh README.md README.en.md CHANGELOG.md; do cp "$SRC_DIR/$f" "$APP_DIR/" 2>/dev/null || true; done
chmod +x "$APP_DIR"/*.sh
# --system-site-packages : donne accès à gpiozero / lgpio / smbus2 installés par apt (bidouille GPIO)
rm -rf "$APP_DIR/venv"
python3 -m venv --system-site-packages "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
ok "$(t "Installé dans" "Installed in") $APP_DIR"

# Actions système permises depuis la page web (arrêt / redémarrage du Pi, mises à jour signées) — fichiers de root
install -o root -g root -m 755 "$SRC_DIR/system/rotorweb-helper" "$HELPER"
install -d -o root -g root -m 755 "$PUBDIR"
install -o root -g root -m 644 "$SRC_DIR/rotorweb/release.pub" "$PUBDIR/release.pub"
chown root:root "$HELPER"; chmod 755 "$HELPER"
echo "$USR ALL=(root) NOPASSWD: $HELPER" > "$SUDOERS.tmp"
chmod 440 "$SUDOERS.tmp"
if visudo -cf "$SUDOERS.tmp" >/dev/null 2>&1; then mv "$SUDOERS.tmp" "$SUDOERS"; ok "$(t "Boutons Éteindre / Redémarrer le Pi activés" "Shut down / Reboot Pi buttons enabled")"
else rm -f "$SUDOERS.tmp"; warn "$(t "sudoers invalide : boutons d'arrêt du Pi désactivés" "invalid sudoers: Pi power buttons disabled")"; fi

# Restauration de la sauvegarde (le mot de passe de la sauvegarde est demandé)
if [[ -n "$RESTORE_FILE" ]]; then
  step "$(t "Restauration de la sauvegarde" "Restoring the backup")"
  while true; do
    if (cd "$APP_DIR" && "$APP_DIR/venv/bin/python" -m rotorweb.backup restore "$RESTORE_FILE" --config "$APP_DIR/config.json" --yes </dev/tty); then
      RESTORED=1; ok "$(t "Réglages, comptes, horaires et calibration restaurés" "Settings, accounts, schedules and calibration restored")"; break
    fi
    yesno "$(t "Réessayer le mot de passe ?" "Try the password again?")" "$(t o y)" || { warn "$(t "Nouvelle installation sans sauvegarde" "New installation without backup")"; break; }
  done
fi

# ---------------------------------------------------------------
step "4/8 $(t "Contrôleur du rotor" "Rotor controller")"
SIMULATE=0
SERIAL_PORT=/dev/rotor
DRIVER=gs232b
DRV_BAUD=0
DETECTED_BAUD=0
TCP_PORT=4534
HL_MODEL=""
echo "   $(t "Quel contrôleur pilote le rotor ?" "Which controller drives the rotor?")"
echo "   d) $(t "Détecter automatiquement (branche le contrôleur en USB)" "Detect automatically (plug the controller into USB)")   [$(t "défaut" "default")]"
echo "   1) K3NG / Yaesu GS-232B ($(t "et compatibles : ERC…" "and compatibles: ERC…"))"
echo "   2) Yaesu GS-232A ($(t "ancien" "older"))"
echo "   3) Easycomm II (SatNOGS, $(t "montages Arduino" "Arduino builds"))"
echo "   4) SPID Rot2Prog (MD-01/02/03)"
echo "   5) Hy-Gain DCU-1 / DCU-2 / RT-21 / Rotor-EZ"
echo "   6) $(t "Autre modèle via Hamlib (rotctld)" "Other model through Hamlib (rotctld)")"
echo "   7) $(t "Bidouille : Arduino avec le croquis RotorWeb (potentiomètre + relais)" "DIY: Arduino with the RotorWeb sketch (potentiometer + relays)")"
echo "   8) $(t "Bidouille : relais sur les GPIO du Raspberry Pi + module ADS1115" "DIY: relays on the Raspberry Pi GPIO + ADS1115 module")"
echo "   s) $(t "Simulation (aucun matériel)" "Simulation (no hardware)")"
if [[ $RESTORED -eq 1 ]]; then
  CHOICE=$(python3 -c "import json;print(json.load(open('$APP_DIR/config.json')).get('rotor',{}).get('driver','gs232b'))")
  ok "$(t "Contrôleur de la sauvegarde" "Controller from the backup") : $CHOICE"
  case "$CHOICE" in gs232b) CHOICE=1;; gs232a) CHOICE=2;; easycomm) CHOICE=3;; rot2prog) CHOICE=4;; dcu1) CHOICE=5;; hamlib) CHOICE=6;; arduino) CHOICE=7;; gpio) CHOICE=8;; *) CHOICE=1;; esac
  RST_HL=$(python3 -c "import json;r=json.load(open('$APP_DIR/config.json')).get('rotor',{});print(r.get('hamlib_model',''),r.get('hamlib_speed',0))")
else
CHOICE=$(ask "$(t "Choix" "Choice")" "d")
fi
case "$CHOICE" in
  1) DRIVER=gs232b ;;
  2) DRIVER=gs232a ;;
  3) DRIVER=easycomm ;;
  4) DRIVER=rot2prog ;;
  5) DRIVER=dcu1 ;;
  6) DRIVER=hamlib ;;
  7) DRIVER=arduino ;;
  8) DRIVER=gpio ;;
  s|S) SIMULATE=1 ;;
  *) DRIVER=detect ;;
esac

pick_serial() {
  mapfile -t PORTS < <(ls /dev/serial/by-id/* 2>/dev/null || true)
  if [[ ${#PORTS[@]} -eq 0 ]]; then
    warn "$(t "Aucun port USB série détecté." "No USB serial port found.")"
    a=$(ask "$(t "Branche le contrôleur puis Entrée pour réessayer, ou « s » pour la simulation" "Plug the controller then Enter to retry, or “s” for simulation")" "")
    if [[ "$a" =~ ^[sS] ]]; then SIMULATE=1; return; fi
    sleep 2; mapfile -t PORTS < <(ls /dev/serial/by-id/* 2>/dev/null || true)
    [[ ${#PORTS[@]} -eq 0 ]] && { warn "$(t "Toujours rien : installation en mode SIMULATION (modifiable plus tard)." "Still nothing: installing in SIMULATION mode (can be changed later).")"; SIMULATE=1; return; }
  fi
  echo "   $(t "Ports série trouvés :" "Serial ports found:")"
  for i in "${!PORTS[@]}"; do echo "   $((i+1))) $(basename "${PORTS[$i]}")  →  $(readlink -f "${PORTS[$i]}")"; done
  n=1; [[ ${#PORTS[@]} -gt 1 ]] && n=$(ask "$(t "Lequel est le contrôleur du rotor ?" "Which one is the rotor controller?")" "1")
  CHOSEN="${PORTS[$((n-1))]}"
  DEV=$(readlink -f "$CHOSEN")
  VID=$(udevadm info -q property -n "$DEV" | sed -n 's/^ID_VENDOR_ID=//p')
  PID=$(udevadm info -q property -n "$DEV" | sed -n 's/^ID_MODEL_ID=//p')
  SER=$(udevadm info -q property -n "$DEV" | sed -n 's/^ID_SERIAL_SHORT=//p')
  RULE="SUBSYSTEM==\"tty\", ATTRS{idVendor}==\"$VID\", ATTRS{idProduct}==\"$PID\""
  [[ -n "$SER" ]] && RULE+=", ATTRS{serial}==\"$SER\""
  RULE+=", SYMLINK+=\"rotor\", GROUP=\"dialout\", MODE=\"0660\""
  echo "# RotorWeb : nom fixe /dev/rotor pour le contrôleur du rotor" > "$UDEV_RULE"
  echo "$RULE" >> "$UDEV_RULE"
  udevadm control --reload-rules && udevadm trigger
  sleep 2
  if [[ -e /dev/rotor ]]; then ok "$(t "Contrôleur accessible sous le nom fixe /dev/rotor" "Controller reachable under the fixed name /dev/rotor")"
  else warn "$(t "Le lien /dev/rotor n'est pas apparu : j'utilise" "The /dev/rotor link did not appear: using") $CHOSEN"; SERIAL_PORT="$CHOSEN"; fi
}

if [[ $SIMULATE -eq 0 && "$DRIVER" == "detect" ]]; then
  pick_serial
  if [[ $SIMULATE -eq 0 ]]; then
    echo "   $(t "Détection du modèle (demandes de position seulement, aucun mouvement)…" "Detecting the model (position queries only, no movement)…")"
    RES=$(cd "$APP_DIR" && "$APP_DIR/venv/bin/python" - "$SERIAL_PORT" <<'PY' 2>/dev/null || true
import sys
from rotorweb.detect import probe_port
r = probe_port(sys.argv[1], progress=lambda i, n, k, b: print(f"     … {k} @ {b}", file=sys.stderr))
if not r:
    r = probe_port(sys.argv[1], full=True, progress=lambda i, n, k, b: print(f"     … {k} @ {b}", file=sys.stderr))
print(f"{r[0]['driver']} {r[0]['baud']}" if r else "")
PY
)
    if [[ -n "$RES" ]]; then
      DRIVER=${RES% *}; DETECTED_BAUD=${RES#* }
      ok "$(t "Détecté" "Detected") : $DRIVER @ $DETECTED_BAUD"
    else
      warn "$(t "Aucun contrôleur reconnu. Choisis le modèle (1 à 8) :" "No controller recognized. Pick the model (1 to 8):")"
      case "$(ask "$(t "Choix" "Choice")" "1")" in
        2) DRIVER=gs232a ;; 3) DRIVER=easycomm ;; 4) DRIVER=rot2prog ;; 5) DRIVER=dcu1 ;; 6) DRIVER=hamlib ;;
        7) DRIVER=arduino ;; 8) DRIVER=gpio ;; *) DRIVER=gs232b ;;
      esac
    fi
  fi
  [[ $SIMULATE -eq 1 ]] && DRIVER=gs232b
  DID_PICK=1
else
  DID_PICK=0
fi

if [[ $SIMULATE -eq 0 ]]; then
  case "$DRIVER" in
    gs232a|gs232b|easycomm|rot2prog|dcu1|arduino) [[ $DID_PICK -eq 1 ]] || pick_serial ;;
    hamlib)
      apt-get install -y -qq libhamlib-utils >/dev/null || apt-get install -y -qq hamlib-utils >/dev/null || true
      command -v rotctld >/dev/null || { warn "$(t "rotctld introuvable : installe le paquet libhamlib-utils" "rotctld not found: install the libhamlib-utils package")"; }
      echo "   $(t "Cherche ton modèle dans la liste de Hamlib (ex. « yaesu », « prosistel », « m2 »)." "Look up your model in the Hamlib list (e.g. “yaesu”, “prosistel”, “m2”).")"
      if [[ $RESTORED -eq 1 && -n "${RST_HL%% *}" ]]; then HL_MODEL=${RST_HL%% *}; HL_BAUD=${RST_HL##* }; fi
      while [[ -z "$HL_MODEL" ]]; do
        q=$(ask "$(t "Mot à chercher (Entrée pour passer)" "Search word (Enter to skip)")" "")
        [[ -z "$q" ]] && break
        rotctld -l 2>/dev/null | grep -i "$q" | head -20 || true
      done
      while ! [[ "$HL_MODEL" =~ ^[0-9]+$ ]]; do
        HL_MODEL=$(ask "$(t "Numéro du modèle Hamlib (1re colonne)" "Hamlib model number (1st column)")" "")
        [[ "$HL_MODEL" =~ ^[0-9]+$ ]] && break
        warn "$(t "Entre un numéro, ex. 603" "Enter a number, e.g. 603")"
      done
      [[ $DID_PICK -eq 1 ]] || pick_serial
      [[ -n "${HL_BAUD:-}" ]] || HL_BAUD=$(ask "$(t "Vitesse série du contrôleur (0 = défaut de Hamlib)" "Controller serial speed (0 = Hamlib default)")" "0")
      HL_DEV="$SERIAL_PORT"; [[ -e /dev/rotor ]] && HL_DEV=/dev/rotor
      SPEED_OPT=""; [[ "$HL_BAUD" != "0" ]] && SPEED_OPT=" -s $HL_BAUD"
      cat > /etc/systemd/system/rotorweb-rotctld.service <<EOF
[Unit]
Description=Hamlib rotctld pour RotorWeb
After=network.target

[Service]
User=$USR
SupplementaryGroups=dialout
ExecStart=/usr/bin/rotctld -m $HL_MODEL -r $HL_DEV$SPEED_OPT -T 127.0.0.1 -t $TCP_PORT
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
      systemctl daemon-reload
      systemctl enable --now rotorweb-rotctld >/dev/null 2>&1 && ok "rotctld ($(t "modèle" "model") $HL_MODEL) $(t "démarré sur le port" "started on port") $TCP_PORT" \
        || warn "$(t "rotctld n'a pas démarré" "rotctld did not start") : journalctl -u rotorweb-rotctld -n 30"
      ;;
    gpio)
      apt-get install -y -qq python3-gpiozero python3-lgpio python3-smbus2 i2c-tools >/dev/null || \
        apt-get install -y -qq python3-gpiozero python3-smbus i2c-tools >/dev/null || true
      command -v raspi-config >/dev/null && raspi-config nonint do_i2c 0 && ok "$(t "Bus I2C activé" "I2C bus enabled")"
      for g in gpio i2c; do getent group $g >/dev/null && usermod -aG $g "$USR"; done
      echo "   $(t "Numéros GPIO (numérotation BCM) des relais :" "GPIO numbers (BCM numbering) of the relays:")"
      if [[ $RESTORED -eq 1 ]]; then ok "$(t "Réglages GPIO de la sauvegarde" "GPIO settings from the backup")"; else
      G_CW=$(ask "$(t "Relais rotation horaire" "Clockwise relay")" "17")
      G_CCW=$(ask "$(t "Relais rotation anti-horaire" "Counter-clockwise relay")" "27")
      G_UP=$(ask "$(t "Relais élévation haut (si élévation)" "Elevation up relay (if elevation)")" "22")
      G_DOWN=$(ask "$(t "Relais élévation bas (si élévation)" "Elevation down relay (if elevation)")" "23")
      G_LOW=true; yesno "$(t "Tes relais s'activent-ils au niveau BAS (la plupart des modules) ?" "Are your relays active LOW (most modules)?")" "$(t o y)" || G_LOW=false
      if command -v i2cdetect >/dev/null; then
        echo "   $(t "Modules I2C détectés (l'ADS1115 apparaît normalement en 48) :" "I2C modules found (the ADS1115 normally shows at 48):")"
        i2cdetect -y 1 2>/dev/null | sed 's/^/     /' || true
      fi
      G_ADS=$(ask "$(t "Adresse I2C de l'ADS1115 (hex)" "ADS1115 I2C address (hex)")" "48")
      fi
      ;;
  esac
fi
[[ $SIMULATE -eq 1 && "$DRIVER" == "detect" ]] && DRIVER=gs232b
[[ $SIMULATE -eq 1 ]] && ok "$(t "Mode simulation : pilote $DRIVER simulé" "Simulation mode: simulated $DRIVER driver")"

# ---------------------------------------------------------------
step "5/8 Configuration"
CFG="$APP_DIR/config.json"
case "$DRIVER" in
  gs232a|gs232b|easycomm) DEF_BAUD=9600 ;; rot2prog) DEF_BAUD=600 ;; dcu1) DEF_BAUD=4800 ;; arduino) DEF_BAUD=115200 ;; *) DEF_BAUD=0 ;;
esac
[[ "$DETECTED_BAUD" != "0" ]] && DEF_BAUD=$DETECTED_BAUD
BAUD=$DEF_BAUD
KEEP=0
if [[ $RESTORED -eq 1 ]]; then KEEP=1
elif [[ -f "$CFG" ]] && yesno "$(t "Une configuration existe déjà. La garder ?" "A configuration already exists. Keep it?")" "$(t o y)"; then KEEP=1; fi

if [[ $KEEP -eq 0 ]]; then
  CALL=$(ask "$(t "Indicatif de la station (affiché en haut de la page, optionnel)" "Station callsign (shown at the top of the page, optional)")" ""); CALL=${CALL^^}
  while true; do
    GRID=$(ask "$(t "Grid de la station (6 caractères conseillé, ex. FN48ji)" "Station grid (6 characters advised, e.g. FN48ji)")" ""); GRID=${GRID^^}
    [[ "$GRID" =~ ^[A-R]{2}[0-9]{2}([A-X]{2}([0-9]{2})?)?$ ]] && break
    warn "$(t "Grid invalide, recommence (ex. FN48 ou FN48JI)" "Invalid grid, try again (e.g. FN48 or FN48JI)")"
  done
  SYS_TZ=$(timedatectl show -p Timezone --value 2>/dev/null || true)
  [[ -z "$SYS_TZ" || "$SYS_TZ" == "Etc/UTC" || "$SYS_TZ" == "UTC" || "$SYS_TZ" == "Europe/London" ]] && SYS_TZ="America/Toronto"
  while true; do
    TZN=$(ask "$(t "Fuseau horaire pour les horaires (Québec = America/Toronto)" "Time zone for schedules (e.g. America/Toronto)")" "$SYS_TZ")
    [[ -f "/usr/share/zoneinfo/$TZN" ]] && break
    warn "$(t "Fuseau inconnu, ex. America/Toronto, America/Halifax, America/Vancouver" "Unknown time zone, e.g. America/Toronto, America/Halifax, America/Vancouver")"
  done
  WEB_PORT=$(ask "$(t "Port de la page web (80 = sans numéro dans l'adresse)" "Web page port (80 = no number in the address)")" "8080")
  GS_PORT=$(ask "$(t "Port TCP du COM virtuel (GS-232)" "Virtual COM TCP port (GS-232)")" "4001")
  [[ "$DEF_BAUD" != "0" && "$DRIVER" != "arduino" ]] && BAUD=$(ask "$(t "Vitesse série du contrôleur" "Controller serial speed")" "$DEF_BAUD")
  EL=false; yesno "$(t "Ton rotor a-t-il l'élévation (azimut + élévation) ?" "Does your rotor have elevation (azimuth + elevation)?")" "n" && EL=true
  START_OP=false
  yesno "$(t "Mettre « En opération » automatiquement au démarrage du RPi ? (non = plus sécuritaire)" "Turn “Operating” on automatically when the Pi starts? (no = safer)")" "n" && START_OP=true

  CALL="$CALL" GRID="$GRID" WEB_PORT="$WEB_PORT" GS_PORT="$GS_PORT" BAUD="$BAUD" EL="$EL" LNG="$LNG" \
  START_OP="$START_OP" SERIAL_PORT="$SERIAL_PORT" CFG="$CFG" TZN="$TZN" python3 - <<'PY'
import json, os, secrets
cfg = {}
if os.path.exists(os.environ["CFG"]):
    try: cfg = json.load(open(os.environ["CFG"]))
    except Exception: cfg = {}
cfg.update({
  "callsign": os.environ["CALL"], "grid": os.environ["GRID"],
  "serial_port": os.environ["SERIAL_PORT"], "baud": int(os.environ["BAUD"]),
  "web_port": int(os.environ["WEB_PORT"]), "gs232_port": int(os.environ["GS_PORT"]),
  "elevation": os.environ["EL"] == "true",
  "start_operating": os.environ["START_OP"] == "true",
  "timezone": os.environ["TZN"], "lang": os.environ["LNG"],
})

cfg.setdefault("secret", secrets.token_hex(16))
cfg.setdefault("users", {})
cfg.pop("password", None)
json.dump(cfg, open(os.environ["CFG"], "w"), indent=2, ensure_ascii=False)
PY
  ok "$(t "Configuration enregistrée dans" "Configuration saved in") $CFG"
fi

# Le contrôleur choisi à l'étape 4 est toujours appliqué (même si la configuration est conservée)
SERIAL_PORT="$SERIAL_PORT" CFG="$CFG" DRIVER="$DRIVER" BAUD="$BAUD" TCP_PORT="$TCP_PORT" LNG="$LNG" RESTORED="$RESTORED" \
HL_MODEL="${HL_MODEL:-}" HL_BAUD="${HL_BAUD:-0}" \
G_CW="${G_CW:-17}" G_CCW="${G_CCW:-27}" G_UP="${G_UP:-22}" G_DOWN="${G_DOWN:-23}" G_LOW="${G_LOW:-true}" G_ADS="${G_ADS:-48}" \
python3 - <<'PY'
import json, os
p = os.environ["CFG"]
cfg = json.load(open(p))
cfg.setdefault("lang", os.environ["LNG"])
rotor = cfg.get("rotor") or {}
if os.environ["RESTORED"] == "1":
    # sauvegarde restaurée : on garde son contrôleur, seul le port détecté sur ce Pi est mis à jour
    if rotor.get("driver") not in ("hamlib", "gpio"):
        rotor["serial_port"] = os.environ["SERIAL_PORT"]
    cfg["rotor"] = rotor
    json.dump(cfg, open(p, "w"), indent=2, ensure_ascii=False)
    raise SystemExit(0)
old = rotor.get("driver")
if old:   # garde l'ancienne configuration dans un profil pour revenir en arrière
    cfg.setdefault("rotor_profiles", {})["↩ Précédent"] = {**rotor, "elevation": cfg.get("elevation", False)}
rotor.update({"driver": os.environ["DRIVER"], "serial_port": os.environ["SERIAL_PORT"],
              "baud": int(os.environ["BAUD"]), "tcp_host": "127.0.0.1", "tcp_port": int(os.environ["TCP_PORT"])})
if os.environ["DRIVER"] == "hamlib" and os.environ.get("HL_MODEL"):
    rotor.update(hamlib_model=os.environ["HL_MODEL"], hamlib_speed=int(os.environ.get("HL_BAUD") or 0))
if os.environ["DRIVER"] == "gpio":
    rotor["gpio"] = {"cw": int(os.environ["G_CW"]), "ccw": int(os.environ["G_CCW"]), "up": int(os.environ["G_UP"]),
                     "down": int(os.environ["G_DOWN"]), "active_low": os.environ["G_LOW"] == "true",
                     "ads_address": int(os.environ["G_ADS"], 16), "ads_ch_az": 0, "ads_ch_el": 1}
if old and old != rotor["driver"]:
    rotor["cal_az"], rotor["cal_el"] = [], []   # autre matériel : ancienne calibration invalide
cfg["rotor"] = rotor
json.dump(cfg, open(p, "w"), indent=2, ensure_ascii=False)
PY
ok "$(t "Contrôleur" "Controller") : $DRIVER"

# ---------------------------------------------------------------
step "6/8 $(t "Compte de connexion" "Login account")"
NB_USERS=$(python3 -c "import json;print(len(json.load(open('$CFG')).get('users',{})))")
if [[ "$NB_USERS" -gt 0 ]]; then
  ok "$NB_USERS $(t "compte(s) déjà existant(s) — gestion" "existing account(s) — manage with") :  sudo $APP_DIR/users.sh list"
else
  echo "   $(t "La page web demande un nom d'utilisateur et un mot de passe." "The web page asks for a user name and a password.")"
  while true; do
    U=$(ask "$(t "Nom d'utilisateur (minuscules, ex. marc)" "User name (lowercase, e.g. marc)")" ""); U=${U,,}
    [[ "$U" =~ ^[a-z0-9_.-]{2,32}$ ]] || { warn "$(t "Nom invalide (2 à 32 caractères : a-z 0-9 _ . -)" "Invalid name (2 to 32 characters: a-z 0-9 _ . -)")"; continue; }
    (cd "$APP_DIR" && "$APP_DIR/venv/bin/python" -m rotorweb.auth add "$U" --config "$CFG" </dev/tty) && break
  done
fi
chown -R "$USR:$USR" "$APP_DIR"
chmod 600 "$CFG"

# ---------------------------------------------------------------
step "7/8 $(t "Service de démarrage automatique" "Auto-start service")"
EXTRA=""; [[ $SIMULATE -eq 1 ]] && EXTRA=" --simulate"
GROUPS_LINE="dialout"
for g in gpio i2c; do getent group $g >/dev/null && GROUPS_LINE+=" $g"; done
cat > /etc/systemd/system/$SVC.service <<EOF
[Unit]
Description=RotorWeb - controle du rotor
After=network-online.target
Wants=network-online.target

[Service]
User=$USR
Group=$USR
SupplementaryGroups=$GROUPS_LINE
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python -m rotorweb.server --config $APP_DIR/config.json$EXTRA
Restart=always
RestartSec=3
# Permet d'utiliser un port web < 1024 (80, 443) sans être root
AmbientCapabilities=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now "$SVC" >/dev/null 2>&1
sleep 3
if systemctl is-active --quiet "$SVC"; then ok "$(t "Service RotorWeb démarré" "RotorWeb service started")"
else warn "$(t "Le service n'a pas démarré. Diagnostic" "The service did not start. Diagnosis") :  journalctl -u $SVC -n 50"; fi

# ---------------------------------------------------------------
step "8/8 $(t "Firmware (optionnel)" "Firmware (optional)")"
CUR_DRV=$(python3 -c "import json;print(json.load(open('$CFG')).get('rotor',{}).get('driver','gs232b'))")
if [[ "$CUR_DRV" == "arduino" ]]; then
  if yesno "$(t "Téléverser maintenant le croquis RotorWeb DIY sur l'Arduino ?" "Upload the RotorWeb DIY sketch to the Arduino now?")" "$(t o y)"; then
    bash "$APP_DIR/firmware/flash_diy.sh" || warn "$(t "Le téléversement n'a pas réussi" "The upload failed") : sudo $APP_DIR/firmware/flash_diy.sh"
  fi
elif [[ "$CUR_DRV" == "gs232b" || "$CUR_DRV" == "gs232a" ]]; then
  if yesno "$(t "Compiler et flasher le firmware K3NG sur l'Arduino maintenant ?" "Build and flash the K3NG firmware to the Arduino now?")" "n"; then
    bash "$APP_DIR/firmware/flash_k3ng.sh" || warn "$(t "Le flash n'a pas réussi" "Flashing failed") : sudo $APP_DIR/firmware/flash_k3ng.sh"
  fi
else
  ok "$(t "Rien à flasher pour ce contrôleur" "Nothing to flash for this controller")"
fi
if [[ "$CUR_DRV" == "arduino" || "$CUR_DRV" == "gpio" ]]; then
  echo -e "  ${Y}$(t "Bidouille : fais la calibration dans la page (Réglages ▸ Calibration) avant le premier pointage." "DIY: run the calibration in the page (Settings ▸ Calibration) before the first pointing.")${N}"
fi

# ---------------------------------------------------------------
IP=$(hostname -I | awk '{print $1}')
WP=$(python3 -c "import json;print(json.load(open('$CFG'))['web_port'])")
GP=$(python3 -c "import json;print(json.load(open('$CFG'))['gs232_port'])")
URL="http://$IP:$WP"; [[ "$WP" == "80" ]] && URL="http://$IP"
echo
echo -e "${G}=====================================================${N}"
echo -e "${G}  RotorWeb v$RW_VERSION — $(t "Installation terminée !" "Installation complete!")${N}"
echo -e "${G}=====================================================${N}"
echo -e "  $(t "Page web         " "Web page         ") :  ${B}$URL${N}"
echo -e "  $(t "COM virtuel (PC) " "Virtual COM (PC) ") :  TCP ${B}$IP:$GP${N}  (Yaesu GS-232B, 9600)"
echo -e "  rotctld (Hamlib)  :  TCP ${B}$IP:4533${N}"
echo -e "  WSJT-X            :  UDP Server = ${B}224.0.0.1${N} port ${B}2237${N}"
echo -e "  $(t "Courriels Gmail  " "Gmail emails     ") :  $(t "à configurer dans la page (Réglages ▸ Courriels)" "set up in the page (Settings ▸ Emails)")"
echo -e "  Home Assistant    :  $(t "à configurer dans la page (Réglages ▸ Home Assistant), voir homeassistant/LISEZMOI-HA.md" "set up in the page (Settings ▸ Home Assistant), see homeassistant/LISEZMOI-HA.md")"
[[ $SIMULATE -eq 1 ]] && echo -e "  ${Y}$(t "Mode SIMULATION actif (aucun rotor réel). Pour brancher le vrai contrôleur" "SIMULATION mode active (no real rotor). To use the real controller") : sudo $APP_DIR/detect.sh${N}"
echo
echo "  $(t "Comptes          " "Accounts         ") :  sudo $APP_DIR/users.sh list | add NOM | passwd NOM | del NOM"
echo "  $(t "Changer de rotor " "Change the rotor ") :  sudo $APP_DIR/detect.sh   $(t "(ou Réglages ▸ Contrôleur dans la page)" "(or Settings ▸ Controller in the page)")"
echo "  $(t "Mise à jour      " "Update           ") :  $(t "dans la page : Réglages ▸ Système ▸ Mises à jour" "in the page: Settings ▸ System ▸ Updates")"
echo "  $(t "Sauvegarde       " "Backup           ") :  $(t "dans la page : Réglages ▸ Système ▸ Sauvegarde, ou" "in the page: Settings ▸ System ▸ Backup, or") sudo $APP_DIR/restore.sh --create FICHIER.rwbackup"
echo "  $(t "Désinstaller     " "Uninstall        ") :  sudo $APP_DIR/uninstall.sh"
echo "  $(t "Journal          " "Log              ") :  journalctl -u $SVC -f   ($(t "q pour quitter" "q to quit"))"
echo
