# RotorWeb — Journal des versions / Changelog

Depuis la v2.0 : Réglages ▸ Système → **Mettre à jour** dans la page. Sinon : `sudo ./update.sh` depuis le dossier de la nouvelle version (voir **MISE-A-JOUR-RotorWeb-…-FR.pdf**).
Since v2.0: Settings ▸ System → **Update** in the page. Otherwise: `sudo ./update.sh` from the new version's folder (see **UPDATE-RotorWeb-…-EN.pdf**).

---

## v2.0 — 2026-11-14

> Mise à jour possible directement depuis la **v1.6** : `update.sh` fait aussi les adaptations de la v1.7 (voir plus bas).

### Nouveautés
- **Mises à jour en ligne** : RotorWeb vérifie chaque jour s'il existe une nouvelle version sur GitHub (`RadioamateursduFjord/rotorweb`), et sur demande avec **🔄 Vérifier les mises à jour** (Réglages ▸ Système).
  - Avertissement : bandeau dans la page, **courriel** et **Home Assistant** (entité de mise à jour, événement `mise_a_jour`).
  - **⬆ Mettre à jour**, avec confirmation, pour tous les utilisateurs (aussi depuis Home Assistant). Jamais automatique.
  - **Signature vérifiée** avant l'installation (Ed25519) : une version modifiée ou corrompue est refusée.
  - L'antenne va au repos, l'avancement s'affiche, la page se recharge sur la nouvelle version.
  - **Retour automatique** à l'ancienne version si la nouvelle ne démarre pas.
  - Source modifiable (autre dépôt GitHub, ou adresse d'un miroir).
- **Sauvegarde des réglages** : Réglages ▸ Système → **💾 Télécharger la sauvegarde**. Un fichier `.rwbackup` contient tout (réglages, contrôleur, calibration, profils, horaires, préréglages, courriels, Home Assistant, comptes), **chiffré par mot de passe** (AES-256).
- **Restauration** : dans la page (aperçu du contenu puis confirmation), pendant une réinstallation avec `install.sh` (question au début : les questions déjà réglées sont sautées), ou en terminal : `sudo /opt/rotorweb/restore.sh fichier.rwbackup`. Les réglages actuels sont gardés à côté.
- **`tools/release.sh`** (pour l'éditeur) : prépare, signe et publie une version sur GitHub en une commande.
- L'installateur garde le modèle Hamlib dans la configuration (utile pour une restauration).

### Corrections
- `update.sh --rollback` prend la copie de sécurité la plus récente (et non la dernière par ordre alphabétique).

---

## v1.7 — 2026-11-14

### Nouveautés
- **Tableau de bord à modules** (page Opération) : bouton **✎ Personnaliser** pour choisir les modules affichés, leur ordre et leur taille (pleine largeur, demi, tiers). Une disposition **par utilisateur et par appareil** : une pour l'ordinateur, une pour le cellulaire. La boussole, le choix du mode et l'arrêt d'urgence restent toujours affichés.
  - Modules : Contrôle, Pointer vers…, Préréglages, Dernier DX WSJT-X, Prochains passages, Trafic, Vent, Horaire en cours, État du contrôleur, Raspberry Pi.
  - **Trafic en trois versions** : dernière ligne, compacte (5 à 10 lignes) ou complète avec défilement.
- **Pointer vers un indicatif ou une ville** : la case accepte un grid (FN46), un indicatif (VE2XYZ, JA1ABC, F4ABC/P) ou une ville (Tokyo, Lima).
  - Indicatifs : **HamQTH** et/ou **QRZ.com** (comptes facultatifs, au choix ou l'un après l'autre), sinon le **préfixe** (pays, sans Internet).
  - Villes : géocodage **Open-Meteo** (gratuit) ; s'il y a plusieurs villes du même nom, on choisit dans une liste.
  - Réglages ▸ **Recherche d'indicatifs**.
- **Passages satellites** (nouvelle page) : tous les satellites **utilisables selon tes bandes** (10 m à 3 cm), sur **12, 24 ou 48 h**, avec **fréquences de montée et de descente, mode et tonalité** (base **SatNOGS**, mise à jour chaque jour), élévation minimale, option « montée aussi dans mes bandes », masquage des passages dans une zone interdite.
  - **Fiche du satellite** : tous ses émetteurs, lien vers la **page web du groupe** et la fiche SatNOGS (nouvel onglet).
  - Boutons **Suivre** et **Planifier** sur chaque passage.
  - **Alertes** facultatives avant un bon passage : délai et élévation réglables, par courriel et/ou Home Assistant.
- **Changer de contrôleur après l'installation** : assistant dans Réglages ▸ **Contrôleur** et en terminal (`sudo /opt/rotorweb/detect.sh`) : liste des ports USB, **détection automatique du modèle** (demandes de position seulement, aucun mouvement), choix manuel possible, garder ou remettre à zéro la course et la calibration, test.
  - **Profils de rotor** (ex. « Rotor HF », « Rotor satellite ») : enregistrer, charger, supprimer.
  - Copie automatique de l'ancienne configuration (profil « ↩ Précédent » et fichier `config.json.bak-…`).
- **Boutons Éteindre / Redémarrer le Raspberry Pi** et **Redémarrer RotorWeb** (Réglages ▸ Système et module du tableau de bord), avec confirmation ; l'antenne peut aller au repos avant l'arrêt.
- **Anglais** : langue de l'interface **au choix de chaque utilisateur** (Réglages ▸ Compte), page de connexion bilingue ; **langue de la station** pour les courriels et Home Assistant (Réglages ▸ Station). Installateur, `update.sh`, `detect.sh` et guides PDF en français et en anglais.
- **Home Assistant** : capteurs « Prochain bon passage satellite » et « Heure du prochain bon passage », événement `passage_sat`, noms des entités dans la langue de la station. **Carte boussole 1.7** : liste des prochains passages (option `passes`), textes français ou anglais selon la langue de HA.
- **`update.sh`** : copie de sécurité automatique et retour en arrière (`sudo /opt/rotorweb/update.sh --rollback`).
- Chaque version contient désormais `update.sh`, ce **CHANGELOG** et le guide PDF de mise à jour.

### Retiré
- **Mode Automatique (suivi WSJT-X)** : le rotor tournait à chaque nouvelle station. Il reste un module **Dernier DX WSJT-X** (indicatif, grid, azimut) avec un bouton **Pointer** à toucher au besoin. Une station en mode Automatique repasse en Manuel à la mise à jour.

### Corrections
- Port web **80** (ou 443) : le service n'avait pas le droit de l'ouvrir (« permission denied »). Corrigé à l'installation et par `update.sh`.
- Le bouton 🛰 Suivi de la page Opération ne changeait pas de mode.
- Le numéro de version de l'installateur est lu directement dans le code (il restait à v1.2).

---

## v1.6
- Suivi des **satellites, de l'ISS, de la Lune et du Soleil** (PyEphem, orbites CelesTrak) pour rotors azimut et azimut + élévation : carte du ciel, prochains passages, prépositionnement, retournement (flip), repos après le passage, passages planifiés, suivi automatique, plages horaires « Suivi ».
- Correctif : numéro de version de l'installateur.

## v1.5
- **Menus et sous-pages** : la page Opération pour l'utilisation courante, les réglages dans des pages séparées (Station, Contrôleur, Course, Calibration, Sécurité, Courriels, Home Assistant, Application mobile, Compte).

## v1.4
- **8 types de contrôleurs** : Yaesu GS-232A/B (K3NG), Easycomm II, SPID Rot2Prog, Hy-Gain DCU-1, Hamlib rotctld, bidouilles Arduino et GPIO du Raspberry Pi.
- **Course du rotor** (butée, amplitude, chemin), **zones interdites**, **décalage d'antenne**, **calibration** guidée, **détection de blocage**.

## v1.3
- Intégration **Home Assistant** (MQTT, découverte automatique), **carte boussole**, notifications, anémomètre via HA.
- Guide d'installation et d'utilisation en PDF dans le paquet.

## v1.2
- **Horaires** en heure locale (régions, grid, azimut), modes Manuel / Automatique / Horaire, position de repos.
- **Courriels Gmail** de confirmation.
- **Protection contre le vent** (Open-Meteo), repos dans l'axe du vent, contournement temporaire.

## v1.1
- **Comptes** (utilisateur + mot de passe), **version mobile** et **application installable** ; indicatif de la station configurable.

## v1.0
- Contrôle d'un rotor K3NG (GS-232) par page web, pointage par **grid**, **port COM virtuel** (TCP) et rotctld pour le PC, suivi WSJT-X, **arrêt d'urgence**, interrupteur **En opération**, blocage du port virtuel, **console de trafic**, script d'installation.

---
---

## v2.0 — 2026-11-14 (English)

> Can be updated directly from **v1.6**: `update.sh` also applies the v1.7 changes.

### New
- **Online updates**: RotorWeb checks every day for a new version on GitHub (`RadioamateursduFjord/rotorweb`), and on demand with **🔄 Check for updates** (Settings ▸ System).
  - Notice: banner in the page, **email** and **Home Assistant** (update entity, `mise_a_jour` event).
  - **⬆ Update**, with confirmation, for every user (also from Home Assistant). Never automatic.
  - **Signature checked** before installing (Ed25519): a modified or corrupted version is refused.
  - The antenna goes to rest, progress is shown, the page reloads on the new version.
  - **Automatic return** to the old version if the new one does not start.
  - Changeable source (another GitHub repository, or a mirror address).
- **Settings backup**: Settings ▸ System → **💾 Download the backup**. A `.rwbackup` file holds everything (settings, controller, calibration, profiles, schedules, presets, emails, Home Assistant, accounts), **password-encrypted** (AES-256).
- **Restore**: in the page (content preview then confirmation), during a reinstallation with `install.sh` (question at the start: already-set questions are skipped), or in a terminal: `sudo /opt/rotorweb/restore.sh file.rwbackup`. The current settings are kept aside.
- **`tools/release.sh`** (for the publisher): prepares, signs and publishes a version on GitHub in one command.
- The installer keeps the Hamlib model in the configuration (useful for a restore).

### Fixes
- `update.sh --rollback` takes the most recent backup (not the last one in alphabetical order).

## v1.7 — 2026-11-14 (English)

### New
- **Modular dashboard** (Operation page): **✎ Customize** button to choose the shown modules, their order and size (full, half, third width). One layout **per user and per device**: one for the computer, one for the phone. The compass, the mode selector and the emergency stop are always shown.
  - Modules: Control, Point to…, Presets, Last WSJT-X DX, Next passes, Traffic, Wind, Current schedule, Controller status, Raspberry Pi.
  - **Traffic in three versions**: last line, compact (5 to 10 lines) or full with scrolling.
- **Point to a callsign or a city**: the box accepts a grid (FN46), a callsign (VE2XYZ, JA1ABC, F4ABC/P) or a city (Tokyo, Lima).
  - Callsigns: **HamQTH** and/or **QRZ.com** (optional accounts, either one or one after the other), otherwise the **prefix** (country, no Internet needed).
  - Cities: **Open-Meteo** geocoding (free); if several cities share the name, pick from a list.
  - Settings ▸ **Callsign lookup**.
- **Satellite passes** (new page): every satellite **usable in your bands** (10 m to 3 cm), over **12, 24 or 48 h**, with **uplink and downlink frequencies, mode and tone** (**SatNOGS** database, refreshed daily), minimum elevation, “uplink also in my bands” option, hide passes through a no-go zone.
  - **Satellite sheet**: all its transmitters, link to the **group web page** and the SatNOGS page (new tab).
  - **Track** and **Schedule** buttons on every pass.
  - Optional **alerts** before a good pass: adjustable lead time and elevation, by email and/or Home Assistant.
- **Change the controller after installation**: wizard in Settings ▸ **Controller** and in a terminal (`sudo /opt/rotorweb/detect.sh`): USB port list, **automatic model detection** (position queries only, no movement), manual choice, keep or reset the travel and calibration, test.
  - **Rotor profiles** (e.g. “HF rotor”, “Satellite rotor”): save, load, delete.
  - Automatic copy of the old configuration (“↩ Previous” profile and `config.json.bak-…` file).
- **Shut down / Reboot the Raspberry Pi** and **Restart RotorWeb** buttons (Settings ▸ System and dashboard module), with confirmation; the antenna can go to rest before shutdown.
- **English**: interface language **chosen by each user** (Settings ▸ Account), bilingual login page; **station language** for emails and Home Assistant (Settings ▸ Station). Installer, `update.sh`, `detect.sh` and PDF guides in French and English.
- **Home Assistant**: “Next good satellite pass” and “Time of the next good pass” sensors, `passage_sat` event, entity names in the station language. **Compass card 1.7**: next passes list (`passes` option), French or English texts following the HA language.
- **`update.sh`**: automatic backup and rollback (`sudo /opt/rotorweb/update.sh --rollback`).
- Every release now ships `update.sh`, this **CHANGELOG** and the PDF update guide.

### Removed
- **Automatic mode (WSJT-X following)**: the rotor turned for every new station. A **Last WSJT-X DX** module remains (call, grid, azimuth) with a **Point** button to tap when needed. A station in Automatic mode goes back to Manual during the update.

### Fixes
- Web port **80** (or 443): the service was not allowed to open it (“permission denied”). Fixed in the installer and by `update.sh`.
- The 🛰 Tracking button of the Operation page did not change the mode.
- The installer version number is read from the code (it was stuck at v1.2).

## Earlier versions
v1.6 satellite/Moon/Sun tracking · v1.5 menus and sub-pages · v1.4 8 controller types, travel, calibration · v1.3 Home Assistant · v1.2 schedules, Gmail emails, wind protection · v1.1 accounts, mobile app · v1.0 first release.
