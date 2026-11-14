# RotorWeb — Guide de mise à jour vers la v2.0

Ce guide explique comment passer de la **v1.6** (ou de la v1.7) à la **v2.0** sans perdre tes réglages, et comment mettre à jour chaque partie. Les nouveautés sont décrites dans **CHANGELOG.md** (v1.7 et v2.0).

**C'est la dernière mise à jour à faire à la main** : à partir de la v2.0, les versions suivantes s'installent depuis la page web (section 9).

**Ce qui est conservé** : configuration (`config.json`), comptes, horaires, préréglages, position de repos, calibration, course, zones interdites, réglages des courriels et de Home Assistant.

## 1. Avant de commencer
- Note la version actuelle : elle est affichée en bas du menu de la page web (« RotorWeb v1.6 »), ou :
  ```bash
  grep '^VERSION' /opt/rotorweb/rotorweb/server.py
  ```
- Mets la station **Hors opération** (interrupteur de la page Opération) pendant la mise à jour.
- Le Raspberry Pi doit avoir Internet (téléchargement des modules Python).

## 2. Mettre à jour RotorWeb sur le Raspberry Pi
1. Copie le fichier `rotorweb-v2.0.zip` sur le Raspberry Pi (clé USB, `scp`, etc.), par exemple dans ton dossier personnel.
2. Décompresse-le et entre dans le **nouveau** dossier :
   ```bash
   cd ~
   unzip -o rotorweb-v2.0.zip
   cd rotorweb-v2.0
   ```
3. Lance la mise à jour :
   ```bash
   sudo ./update.sh
   ```
4. Le script affiche `Mise à jour RotorWeb v1.6 → v2.0`, fait une **copie de sécurité** de l'ancienne version (`/opt/rotorweb-backup-v1.6-…`), installe les fichiers, fait les adaptations nécessaires et redémarre le service. Il doit finir par « ✔ RotorWeb mis à jour et redémarré (v2.0) ».

⚠ Lance toujours `update.sh` depuis le dossier de la **nouvelle** version, pas depuis `/opt/rotorweb`.
⚠ N'utilise pas `install.sh` pour une mise à jour : il repose toutes les questions.

### Ce que `update.sh` adapte automatiquement (v1.6 → v2.0)
- Ajoute le droit d'utiliser le **port 80 ou 443** (corrige l'erreur « permission denied »).
- Installe la commande système des boutons **Éteindre / Redémarrer le Raspberry Pi** et des **mises à jour en ligne** (`/usr/local/sbin/rotorweb-helper`, avec une règle `sudo` limitée à ce seul script).
- Installe la **clé publique** qui vérifie la signature des mises à jour (`/usr/local/share/rotorweb/release.pub`).
- Installe `openssl` et `unzip` s'ils manquent.
- Ajoute la **langue de la station** (celle de l'installation, modifiable dans Réglages ▸ Station).
- Si la station était en **mode Automatique (WSJT-X)**, qui n'existe plus, elle repasse en **Manuel**.

## 3. Vérifier
1. Dans la page web, le bas du menu affiche **RotorWeb v2.0**.
2. Si l'ancienne page reste affichée : recharge-la (**Ctrl+F5** sur ordinateur ; sur le cellulaire, ferme et rouvre l'app ou tire la page vers le bas).
3. La console de trafic affiche « RotorWeb 2.0 démarré ».
4. Réglages ▸ Système ▸ Mises à jour → **🔄 Vérifier les mises à jour** : doit afficher « RotorWeb est à jour » (ou une version plus récente si elle existe).
5. **Fais une sauvegarde** : Réglages ▸ Système ▸ Sauvegarde des réglages → **💾 Télécharger la sauvegarde** (garde le fichier et son mot de passe hors du Pi).
6. Remets la station **En opération**.

En cas de problème :
```bash
sudo systemctl status rotorweb
journalctl -u rotorweb -n 50 --no-pager
```

## 4. Revenir à la version précédente
Si la nouvelle version pose problème :
```bash
sudo /opt/rotorweb/update.sh --rollback
```
Le script remet la dernière copie de sécurité (programme et réglages tels qu'ils étaient avant la mise à jour) et redémarre le service. Les 3 dernières copies sont gardées dans `/opt/rotorweb-backup-…`.

## 5. Application installée sur le cellulaire
L'app (écran d'accueil) se met à jour toute seule au prochain lancement. Si l'ancienne version reste :
- **Android** : ferme l'app (glisser dans les apps récentes), rouvre-la ; sinon Chrome → ⋮ → Paramètres → Paramètres des sites → l'adresse du Pi → Effacer et réinitialiser.
- **iPhone** : ferme l'app et rouvre-la ; sinon supprime l'icône et rajoute-la (Partager ⬆ → Sur l'écran d'accueil).

Les **dispositions du tableau de bord** et la **langue** sont gardées sur le Raspberry Pi pour ton compte : rien à refaire.

## 6. Home Assistant
1. **Carte boussole** : copie le nouveau `homeassistant/rotorweb-compass-card.js` dans `/config/www/` de Home Assistant (remplace l'ancien), puis recharge le tableau de bord avec **Ctrl+F5**. La console du navigateur affiche `ROTORWEB-COMPASS-CARD v1.7` (la carte n'a pas changé en v2.0).
   Option nouvelle : `passes: 4` (nombre de prochains passages affichés).
2. **Entités** : elles se mettent à jour toutes seules (découverte MQTT). Nouvelles : « Prochain bon passage satellite », « Heure du prochain bon passage » (v1.7) et **« Mise à jour RotorWeb »** (v2.0) : Home Assistant affiche les nouvelles versions et peut les installer.
3. **Mode** : le sélecteur propose maintenant Manuel, Horaire, Suivi. Si une automatisation choisissait « Automatique », modifie-la.
4. **Langue** : les noms des entités suivent la langue de la station. Si tu la changes en anglais, les noms affichés changent, mais les identifiants (`sensor.rotorweb_…`) restent les mêmes.
5. **Nouvelle automatisation** (facultative) : n° 6 de `homeassistant/automations.yaml`, avertissement avant un passage satellite.

## 7. Firmware du contrôleur
Les v1.7 et v2.0 **ne changent pas** les firmwares. Rien à faire pour un K3NG ou un contrôleur du commerce.

Pour les montages maison :
- **Arduino RotorWeb** : seulement si le croquis `firmware/rotorweb_diy` a changé (voir CHANGELOG) :
  ```bash
  sudo /opt/rotorweb/firmware/flash_diy.sh
  ```
- **K3NG** (mise à jour du firmware K3NG lui-même, rarement nécessaire) :
  ```bash
  sudo /opt/rotorweb/firmware/flash_k3ng.sh
  ```
  Avant de flasher, note tes réglages de calibration K3NG.

## 8. Ce qu'il faut faire à la main pour la v2.0
- **Rien d'obligatoire**, mais **fais une sauvegarde** des réglages une fois la mise à jour terminée.
- Facultatif :
  - Réglages ▸ **Recherche d'indicatifs** : ajoute un compte HamQTH (gratuit) et/ou QRZ.com pour la position exacte des stations.
  - Page **Passages satellites** : coche tes bandes et active les alertes si tu les veux.
  - Page Opération → **✎ Personnaliser** : choisis tes modules, sur l'ordinateur et sur le cellulaire.
  - Réglages ▸ **Compte** : langue de l'interface (Français / English).
  - Réglages ▸ **Profils de rotor** : enregistre ta configuration actuelle sous un nom.

## 9. Les prochaines mises à jour (à partir de la v2.0)
Plus besoin de copier de fichier sur le Pi :
1. Un bandeau « Nouvelle version disponible » apparaît dans la page (et un courriel arrive).
2. **Voir les nouveautés**, puis **⬆ Mettre à jour** et confirme.
3. La page affiche l'avancement (téléchargement, vérification de la signature, antenne au repos, installation) puis se recharge toute seule.
4. Si la nouvelle version ne démarre pas, le Pi revient tout seul à l'ancienne.

Le Raspberry Pi doit avoir accès à github.com. Sinon, la méthode à la main de ce guide fonctionne toujours. Après chaque mise à jour, pense à recopier la carte boussole dans Home Assistant si le CHANGELOG le demande.

## 10. Réinstaller à partir d'une sauvegarde
Nouvelle carte SD ou nouveau Raspberry Pi : copie le zip de la version et ta sauvegarde `.rwbackup` sur le Pi, puis `sudo ./install.sh` ; au début, donne le chemin de la sauvegarde et son mot de passe. Tout est restauré, il reste seulement à confirmer le port du contrôleur.

## 11. Changer de contrôleur (sans réinstaller)
Depuis la v1.7, un nouveau contrôleur se branche sans réinstaller :
- page web : Réglages ▸ **Contrôleur → Changer / redétecter le contrôleur** ;
- ou terminal : `sudo /opt/rotorweb/detect.sh`.

L'ancienne configuration reste dans le profil « ↩ Précédent ».

## 12. Récapitulatif des commandes
```bash
cd ~/rotorweb-v2.0 && sudo ./update.sh            # mettre à jour à la main
sudo /opt/rotorweb/update.sh --rollback      # revenir en arrière
sudo /opt/rotorweb/detect.sh                 # changer / redétecter le contrôleur
sudo /opt/rotorweb/restore.sh fichier.rwbackup   # restaurer une sauvegarde
cat /var/log/rotorweb-update.log             # journal des mises à jour en ligne
journalctl -u rotorweb -f                    # journal en direct (q pour quitter)
```

73 !
