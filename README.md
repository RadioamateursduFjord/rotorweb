![RotorWeb — Contrôle d'antenne radioamateur via le web](logo/banniere-github-1280x640.jpg)

# RotorWeb v2.1 — Guide d'installation et d'utilisation

Contrôle de rotor d'antenne par page web sur Raspberry Pi : K3NG / Yaesu GS-232, Easycomm, SPID Rot2Prog, Hy-Gain DCU-1, Hamlib, ou montage maison (Arduino, GPIO).

> 📘 Ce guide existe en PDF : **GUIDE-RotorWeb-v2.1-FR.pdf** (English: **GUIDE-RotorWeb-v2.1-EN.pdf**).
> 🔄 Mise à jour d'une version précédente : **MISE-A-JOUR-RotorWeb-v2.1-FR.pdf** et **CHANGELOG.md**.

```
 PC (PowerSDR, WSJT-X, GridTracker, Gpredict…)              Téléphone / PC
        │  COM virtuel (TCP 4001) · rotctld (4533) · UDP WSJT-X    │ navigateur ou app
        └──────────────────────────┬───────────────────────────────┘
                 Raspberry Pi — RotorWeb (seul maître du port série)
                                   │ USB
                         Contrôleur (K3NG…) ──► Rotor
```

## 1. Nouveautés
**v2.1**
- **Nouvelle identité visuelle** : logo « Azimut » (icône de l'app, favicon, page de connexion, menu, carte Home Assistant), pictogrammes du menu redessinés, couvertures des guides PDF.

**v2.0**
- **Mises à jour en ligne** depuis la page : « Une nouvelle version est disponible — Mettre à jour », signature vérifiée, retour automatique si problème.
- **Sauvegarde chiffrée** de tous les réglages, téléchargeable, et **restauration** (page, réinstallation, terminal).

**v1.7**
- **Tableau de bord à modules**, personnalisable par utilisateur, séparément pour l'ordinateur et le cellulaire.
- **Pointer vers un indicatif ou une ville** (HamQTH, QRZ, préfixe, Open-Meteo), en plus du grid.
- **Passages satellites** : tous les satellites utilisables selon tes bandes, avec fréquences (SatNOGS), fiche et lien vers la page du groupe, alertes.
- **Changer de contrôleur** après l'installation (détection automatique), **profils de rotor**.
- **Éteindre / redémarrer le Raspberry Pi** depuis la page.
- **Français ou anglais** au choix de chaque utilisateur.
- Le **mode Automatique (WSJT-X) est retiré** ; il reste le module « Dernier DX WSJT-X » avec un bouton Pointer.

Détails : `CHANGELOG.md`.

## 2. Installation
1. Copie le dossier `rotorweb-v2.1` sur le Raspberry Pi (clé USB, `scp`…). Raspberry Pi OS Bookworm ou plus récent conseillé.
2. Branche le contrôleur du rotor en USB.
3. Lance :
   ```bash
   cd rotorweb-v2.1
   sudo ./install.sh
   ```
4. Choisis la **langue** (Français / English). **Réinstallation ?** Donne le chemin de ta sauvegarde `.rwbackup` et son mot de passe : tout est restauré et les questions déjà réglées sont sautées. Sinon choisis le contrôleur : **d) Détecter automatiquement** (par défaut) ou un modèle de la liste, ou **s) Simulation** si tu n'as pas encore le matériel.
5. Réponds aux questions : indicatif, grid de la station, fuseau horaire, port de la page web (**80** = adresse sans numéro), élévation, premier compte de connexion.
6. Ouvre l'adresse affichée à la fin, par ex. `http://192.168.1.50:8080`.

Le script donne au contrôleur le nom fixe `/dev/rotor`, crée le service qui démarre au boot et active les boutons d'arrêt du Pi.

**Déjà installé ?** N'utilise pas `install.sh` : depuis la v2.0, la mise à jour se fait dans la page (section 14). Pour passer de la v1.6 ou v1.7 à la v2.1 : `sudo ./update.sh` une dernière fois à la main (voir le guide de mise à jour).

## 3. Comptes et langue
```bash
sudo /opt/rotorweb/users.sh list            # voir les comptes
sudo /opt/rotorweb/users.sh add julie       # ajouter un compte
sudo /opt/rotorweb/users.sh passwd julie    # changer un mot de passe
sudo /opt/rotorweb/users.sh del julie       # supprimer un compte
```
- Une session reste ouverte 30 jours ; 5 essais ratés bloquent 2 minutes.
- **Langue de l'interface** : Réglages ▸ **Compte** → Français ou English. Chaque utilisateur a la sienne. La page de connexion a un lien English / Français.
- **Langue de la station** (courriels, noms des entités Home Assistant) : Réglages ▸ **Station**.

## 4. La page Opération (tableau de bord)
Toujours affichés : le **choix du mode**, la **boussole** (clic pour pointer, Aller, Gauche/Droite en maintenant, STOP, Repos) et le bouton rouge **ARRÊT D'URGENCE** en haut de toutes les pages (ou touche Échap).

**✎ Personnaliser** choisit les autres modules, leur ordre (↑ ↓) et leur taille (pleine largeur, demi, tiers). La disposition est gardée **pour ton compte et pour le type d'appareil** : une pour l'ordinateur, une autre pour le cellulaire (ex. seulement la boussole et le trafic sur le téléphone). « Par défaut » remet la disposition d'origine.

| Module | Contenu |
|---|---|
| Contrôle | Interrupteur **En opération** et résumé (mode, plage, vent, suivi, DX) |
| Pointer vers… | Grid, indicatif ou ville → cap court et long chemin, distance, historique |
| Préréglages | Positions nommées |
| Dernier DX WSJT-X | Indicatif, grid, cap de la station sélectionnée dans WSJT-X, bouton **Pointer** |
| Prochains passages | Les 6 prochains passages satellites de tes bandes, bouton Suivre |
| Trafic | Trois versions : **dernière ligne**, **compacte** (5 à 10 lignes), **complète** (défilement) |
| Vent | Vent, rafales, direction, état du verrou |
| Horaire en cours | Plage active ou prochaine plage |
| Contrôleur | Connexion, modèle, profil, port |
| Raspberry Pi | Redémarrer RotorWeb, redémarrer ou éteindre le Pi |

Sur le cellulaire : barre du bas (Opération, Horaires, Trafic, Menu), azimut et arrêt d'urgence toujours visibles.

**Installer comme une app** : iPhone → Partager ⬆ → « Sur l'écran d'accueil ». Android → menu ⋮ → « Ajouter à l'écran d'accueil » ; pour une vraie app plein écran, Chrome exige HTTPS (ex. Tailscale : `sudo tailscale cert NOM.ts.net`, puis `https_cert` et `https_key` dans `config.json`).

## 5. Pointer vers un grid, un indicatif ou une ville
Tape dans la case **Pointer vers…** puis Entrée (ou 🔎) :
- **Grid** (FN46, JN18du) : calcul immédiat, sans Internet.
- **Indicatif** (VE2XYZ, JA1ABC, F4ABC/P, VE2/F4ABC) : position de la station sur **HamQTH** ou **QRZ.com** si un compte est configuré, sinon le **préfixe** donne le pays (approximatif pour les grands pays).
- **Ville** (Tokyo, Lima, Rimouski) : géocodage **Open-Meteo** ; s'il y a plusieurs villes du même nom, touche la bonne dans la liste.

Puis **Pointer court** ou **Pointer long**. Le résultat garde le grid dans l'historique.

**Réglages ▸ Recherche d'indicatifs** : source (HamQTH puis QRZ, QRZ puis HamQTH, un seul, ou préfixe seulement) et identifiants. HamQTH est gratuit (compte sur hamqth.com) ; QRZ.com demande un abonnement XML pour la position.

## 6. Modes
| Mode | Qui fait bouger le rotor |
|---|---|
| ✋ Manuel | Toi (page, préréglages, grid) et le PC (COM virtuel, rotctld), Home Assistant |
| 🕒 Horaire | Les plages programmées (+ les commandes manuelles) |
| 🛰 Suivi | La cible choisie, les passages planifiés et les suivis automatiques (+ les commandes manuelles) |

Une **commande manuelle** en mode Horaire ou Suivi **repasse en mode Manuel**. L'**arrêt d'urgence**, « **En opération** » et le **verrou vent** ont toujours la priorité.

WSJT-X ne fait plus tourner le rotor tout seul (v1.7) : le module **Dernier DX WSJT-X** affiche la station sélectionnée et le bouton **Pointer** l'oriente quand tu en as besoin.

## 7. Passages satellites
Page **Passages satellites** (menu ☰) :
- **Mes bandes** : coche les bandes de la station (10 m, 6 m, 2 m, 70 cm, 23 cm, 13 cm, 9 cm, 5 cm, 3 cm). Seuls les satellites qui ont un émetteur radioamateur actif dans ces bandes sont listés.
- **12, 24 ou 48 heures**, **élévation minimale**, **Montée aussi dans mes bandes** (pour faire des contacts, pas seulement écouter), **masquer les passages dans une zone interdite**.
- Pour chaque passage : jour, lever, satellite, élévation max, coucher, durée, azimuts, **fréquences** (↓ descente, ↑ montée, mode, tonalité CTCSS, « inversé » pour les transpondeurs linéaires), boutons **Suivre** et **Planifier**.
- Touche le **nom du satellite** : fiche avec tous ses émetteurs, liens vers la **page web du groupe** et la **fiche SatNOGS** (nouvel onglet).
- **Alertes avant un bon passage** : minutes avant le lever, élévation max minimale, par courriel et/ou Home Assistant.

Données : orbites **CelesTrak** et fréquences **SatNOGS**, téléchargées une fois par jour (bouton « Mettre à jour les fréquences et les orbites »). Le Raspberry Pi doit avoir Internet. Vérifie toujours une fréquence avant d'émettre.

## 8. Suivi d'une cible (Lune, Soleil, ISS, satellite)
Page **Suivi (cible)** et mode **🛰 Suivi** : position en direct, carte du ciel, passages, « Suivre maintenant », planification, suivi automatique au-dessus d'une élévation, satellites ajoutés à la main (3 lignes TLE). Options : seuil de déplacement, prépositionnement, retournement (flip, élévation 0–180°), repos après le passage, notifications. Fonctionne aussi avec un rotor azimut seulement.

## 9. Horaires
Page **Horaires** → **+ Ajouter une plage** : début, fin, jours, direction (région/pays, grid, azimut fixe ou Suivi). Heure locale (fuseau dans Réglages ▸ Station). À la fin d'une plage, l'antenne va au **repos** (azimut fixe ou dans l'axe du vent). Une plage impossible à démarrer envoie une alerte et pointe dès que possible.

## 10. Courriels Gmail
1. Sur le compte Gmail d'envoi, active la **validation en deux étapes**.
2. Crée un **mot de passe d'application** sur myaccount.google.com/apppasswords (16 lettres).
3. Réglages ▸ **Courriels** : adresse, mot de passe d'application, destinataire → **Envoyer un test**.

Courriels : antenne arrivée / non arrivée, plage impossible, verrou vent activé / levé / contourné, rotor immobile, début et fin de suivi, alertes de passage. Ils sont écrits dans la **langue de la station**.

## 11. Protection contre le vent
Vent et rafales lus toutes les 5 minutes sur Open-Meteo (ou un anémomètre via Home Assistant). Au-delà des seuils : repos et verrou de tous les mouvements ; déverrouillage après le calme choisi. **Ignorer le verrou** 15/30/60 minutes pour les commandes manuelles. Open-Meteo est une estimation, pas une mesure sur ton toit : garde des seuils prudents.

## 12. Contrôleur, course et calibration
### Changer de contrôleur ou redétecter (v1.7)
**Réglages ▸ Contrôleur → Changer / redétecter le contrôleur** :
1. Branche le nouveau contrôleur en USB, touche **Chercher les ports USB**, choisis le port.
2. **Détecter le modèle** : RotorWeb essaie les protocoles et vitesses courants (GS-232, Easycomm, Arduino RotorWeb, DCU-1, Rot2Prog). Il envoie **seulement des demandes de position**, jamais de mouvement. « Toutes les vitesses » essaie aussi les vitesses rares (plus long).
3. Vérifie le modèle, la vitesse et l'élévation ; choisis de **garder ou non la course et la calibration**.
4. **Utiliser ce contrôleur** → reconnexion, puis **test** : position lue et petit mouvement avec Gauche/Droite.

L'ancienne configuration est gardée dans le profil **↩ Précédent** (charge-le pour revenir en arrière) et dans un fichier `config.json.bak-…`.

**En terminal** (si la page ne répond plus) : `sudo /opt/rotorweb/detect.sh` — même assistant, en français ou en anglais.

**Profils de rotor** : enregistre la configuration actuelle sous un nom (ex. « Rotor HF »), et passe d'un profil à l'autre en un clic. Un profil garde le contrôleur, la course, la calibration et l'élévation.

### Modèles
| Pilote | Pour | Vitesse par défaut |
|---|---|---|
| Yaesu GS-232B | K3NG, Yaesu GS-232B, ERC et compatibles | 9600 |
| Yaesu GS-232A | Anciens contrôleurs GS-232A | 9600 |
| Easycomm II | SatNOGS, montages Arduino | 9600 |
| SPID Rot2Prog | MD-01/02/03 en mode Rot2Prog | 600 |
| Hy-Gain DCU-1 | DCU-1/2/3, RT-21, Rotor-EZ | 4800 |
| Hamlib rotctld | Une centaine de modèles | — |
| Bidouille Arduino | Croquis `firmware/rotorweb_diy` : potentiomètre + relais | 115200 |
| Bidouille GPIO | Relais sur les GPIO du Pi + ADS1115 | — |

**Course** (butée Nord ou Sud, 360/450/540°, chemin), **zones interdites**, **décalage d'antenne**, **calibration** (assistant pour les bidouilles, commandes O/F pour GS-232), **détection de blocage** : Réglages ▸ Course du rotor et Calibration. Câblage des bidouilles : `firmware/CABLAGE.md`.

## 13. Système : éteindre ou redémarrer le Raspberry Pi
Réglages ▸ **Système** (ou module Raspberry Pi), carte Raspberry Pi : **Redémarrer RotorWeb**, **Redémarrer le Raspberry Pi**, **Éteindre le Raspberry Pi**, avec confirmation. Tous les utilisateurs y ont accès. Option **Repos avant l'arrêt** : si la station est en opération, l'antenne va d'abord au repos.
Après « Éteindre », attends que la DEL verte arrête de clignoter avant de couper le courant ; pour rallumer, débranche et rebranche l'alimentation.

## 14. Mises à jour en ligne (v2.0)
RotorWeb vérifie **une fois par jour** s'il existe une nouvelle version sur GitHub (`RadioamateursduFjord/rotorweb`). Quand il y en a une :
- un bandeau s'affiche en haut de la page : **« Nouvelle version disponible : v2.1 — Voir les nouveautés / Mettre à jour »** ;
- un **courriel** part (si les courriels sont configurés) et Home Assistant affiche la mise à jour (entité « Mise à jour RotorWeb », installable aussi depuis HA).

**Réglages ▸ Système ▸ Mises à jour** : version installée, dernière version, nouveautés, **🔄 Vérifier les mises à jour** et **⬆ Mettre à jour**. Tous les utilisateurs peuvent lancer la mise à jour ; elle demande toujours une confirmation et ne se fait **jamais toute seule**.

Pendant la mise à jour (1 à 3 minutes) :
1. téléchargement de la nouvelle version ;
2. **vérification de la signature** : une version modifiée ou abîmée est refusée, rien n'est installé ;
3. l'antenne va au repos (si en opération), le rotor s'arrête ;
4. installation par `update.sh` (copie de sécurité de l'ancienne version) et redémarrage ;
5. la page se recharge toute seule sur la nouvelle version.

Si la nouvelle version **ne démarre pas**, le Raspberry Pi revient **automatiquement** à l'ancienne et l'indique dans la page et par courriel. Journal détaillé : `/var/log/rotorweb-update.log`.

Le Raspberry Pi doit pouvoir joindre github.com. Sans Internet, rien ne casse : la mise à jour à la main avec `sudo ./update.sh` fonctionne toujours. « Source des mises à jour » permet d'utiliser un autre dépôt ou un miroir.

## 15. Sauvegarde et restauration (v2.0)
**Réglages ▸ Système ▸ Sauvegarde des réglages** : choisis un mot de passe (deux fois) → **💾 Télécharger la sauvegarde**. Le fichier `rotorweb-INDICATIF-date.rwbackup` contient **tout** : réglages, contrôleur, calibration, course, profils, horaires, préréglages, vent, courriels, Home Assistant, recherche d'indicatifs, satellites, comptes, langues et dispositions. Il est **chiffré** (AES-256) : sans le mot de passe, il est illisible et ne peut pas être restauré. La sauvegarde est manuelle : fais-en une après chaque gros changement et garde-la hors du Pi.

**Restaurer** (remplace tous les réglages actuels ; une copie des actuels est gardée sur le Pi) :
- **dans la page** : Restaurer une sauvegarde → fichier + mot de passe → **Ouvrir la sauvegarde** (aperçu du contenu) → **Remplacer les réglages actuels** → RotorWeb redémarre ;
- **à la réinstallation** (nouvelle carte SD, nouveau Pi) : `sudo ./install.sh` demande le fichier au début ;
- **en terminal** : `sudo /opt/rotorweb/restore.sh fichier.rwbackup` (et `sudo /opt/rotorweb/restore.sh --create fichier.rwbackup` pour en créer une).

Les fichiers non inclus : certificats HTTPS et réglages du Raspberry Pi lui-même (réseau, Wi-Fi). Ouvrir une sauvegarde à la main : `openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in fichier.rwbackup | gunzip`.

## 16. Publier une nouvelle version (éditeur)
Sur le VPS (gh connecté, clé `~/.rotorweb-release/rotorweb-signing.key`) :
```bash
unzip rotorweb-vX.Y.zip && cd rotorweb-vX.Y
./tools/release.sh --dry-run     # essai : paquet + signature, rien n'est publié
./tools/release.sh               # publie sur GitHub (phrase de passe de la clé demandée)
```
Le script vérifie le numéro de version et le CHANGELOG, crée le zip, `release.json` et sa signature, pousse le code sur `main` et crée la « Release » vX.Y. Les stations la voient dans les 24 h.

Le dossier `logo/` (sources du logo, couvertures 300 ppp, bannière) va dans le dépôt GitHub mais **pas** dans le zip des stations. L'image d'aperçu du dépôt se téléverse à la main, une seule fois : GitHub ▸ dépôt ▸ **Settings** ▸ **Social preview** ▸ `logo/banniere-github-1280x640.jpg`. Pour regénérer les icônes : `python3 tools/make_logo.py --font space-grotesk-700.woff`.

## 17. Home Assistant
Voir `homeassistant/LISEZMOI-HA.md`. Réglages ▸ **Home Assistant** : broker MQTT, utilisateur, mot de passe. L'appareil RotorWeb apparaît avec 26 entités (27 avec l'élévation), dont en v1.7 **Prochain bon passage satellite**, **Heure du prochain bon passage** et l'événement `passage_sat`. Carte boussole : copier `rotorweb-compass-card.js` dans `/config/www/` (option `passes: 4` pour la liste des passages).

## 18. Configuration du PC
- **Port COM virtuel** : HW VSP3 (ou com0com + com2tcp) → IP du Pi, port **4001** ; dans le logiciel : Yaesu GS-232B, 9600 bauds.
- **rotctld** (Gpredict, Log4OM, PstRotator) : « Hamlib NET rotctl », `IP_du_Pi:4533`.
- **WSJT-X** (module Dernier DX) : Réglages → Comptes rendus → UDP Server **224.0.0.1**, port **2237**, interface réseau cochée, TTL 1. GridTracker : même adresse multicast.

## 19. Fichiers et commandes
| Emplacement | Rôle |
|---|---|
| `/opt/rotorweb/config.json` | Réglages (ports, grid, contrôleur, profils, comptes…) |
| `/opt/rotorweb/state.json` | Préréglages, horaires, dispositions et langue des utilisateurs |
| `/opt/rotorweb/tle.txt`, `satnogs.json` | Orbites et fréquences téléchargées |
| `/opt/rotorweb/config.json.bak-…` | Copies avant un changement de contrôleur |
| `/opt/rotorweb-backup-v…` | Copies avant une mise à jour (les 3 dernières) |
| `/etc/udev/rules.d/99-rotorweb.rules` | Nom fixe `/dev/rotor` |
| `/usr/local/sbin/rotorweb-helper` | Seules actions système permises (arrêt, redémarrage, mise à jour signée) |
| `/usr/local/share/rotorweb/release.pub` | Clé publique qui vérifie les mises à jour |
| `/var/log/rotorweb-update.log` | Journal des mises à jour en ligne |
| `/opt/rotorweb/*.avant-restauration-…` | Réglages d'avant une restauration |

```bash
sudo systemctl status rotorweb                 # état
journalctl -u rotorweb -f                      # journal en direct (q pour quitter)
sudo /opt/rotorweb/detect.sh                   # changer / redétecter le contrôleur
sudo ./update.sh                               # mise à jour (depuis le dossier de la nouvelle version)
sudo /opt/rotorweb/update.sh --rollback        # revenir à la version précédente
sudo /opt/rotorweb/restore.sh fichier.rwbackup # restaurer une sauvegarde
sudo /opt/rotorweb/uninstall.sh                # désinstallation
```

## 20. Dépannage
- **Le service ne démarre pas, « permission denied » sur le port 80** : relance `sudo ./update.sh` (v1.7 donne ce droit au service).
- **« Contrôleur absent »** : `sudo /opt/rotorweb/detect.sh`, ou Réglages ▸ Contrôleur → Changer / redétecter.
- **Position qui ne bouge pas** : coche « RPi ↔ contrôleur » dans la console de trafic pour voir les réponses brutes.
- **Indicatif introuvable** : sans compte HamQTH/QRZ, seul le pays est donné ; vérifie les identifiants dans Réglages ▸ Recherche d'indicatifs.
- **Liste de passages vide** : coche d'autres bandes, baisse l'élévation minimale, ou mets à jour les fréquences et les orbites (Internet requis).
- **Boutons d'arrêt du Pi : « Commande système non installée »** : relance `sudo ./update.sh`.
- **L'ancienne version reste affichée** (navigateur ou app) : recharge la page (Ctrl+F5, ou tire vers le bas sur le cellulaire).
- **Courriel test en échec** : mot de passe d'application de 16 lettres et validation en deux étapes.
- **Home Assistant « Connexion en cours… »** : IP de HA, port 1883, Mosquitto démarré, identifiants MQTT.
- **« Vérification impossible »** : le Pi n'a pas accès à github.com (Internet, pare-feu, DNS).
- **« Signature invalide : version refusée »** : la version publiée n'est pas signée par la bonne clé ; ne pas installer, prévenir l'éditeur.
- **Mise à jour échouée** : RotorWeb est revenu à l'ancienne version ; détails dans `/var/log/rotorweb-update.log`.
- **Mot de passe de sauvegarde oublié** : la sauvegarde ne peut pas être ouverte (c'est le but du chiffrement) ; fais-en une nouvelle.
- **Mot de passe oublié** : `sudo /opt/rotorweb/users.sh passwd NOM`.
- **Accès depuis Internet** : passe par un VPN (Tailscale, WireGuard), pas par une redirection de port.

73 !
