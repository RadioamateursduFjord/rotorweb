# RotorWeb dans Home Assistant

## 1. Préparer MQTT dans Home Assistant
1. **Paramètres → Modules complémentaires → Boutique** : installe **Mosquitto broker**, démarre-le.
2. **Paramètres → Personnes → Utilisateurs** : crée un utilisateur `rotorweb` avec un mot de passe
   (il sert seulement à MQTT ; tu peux cocher « Autoriser la connexion uniquement à partir du réseau local »).
3. **Paramètres → Appareils et services** : l'intégration **MQTT** est proposée ; accepte-la.

## 2. Brancher RotorWeb
Dans la page RotorWeb → menu ☰ → **Réglages ▸ Home Assistant** :
- Activer l'intégration
- Broker : l'adresse IP de Home Assistant, port 1883
- Utilisateur / mot de passe : ceux de l'étape 1.2
- **Enregistrer et connecter** → « ✔ Connecté »

L'appareil **RotorWeb (indicatif)** apparaît dans Paramètres → Appareils et services → MQTT,
avec 26 entités (27 avec l'élévation).
Les noms des entités suivent la **langue de la station** (Réglages ▸ Station : français ou anglais).

## 3. Installer la carte boussole
1. Télécharge `rotorweb-compass-card.js` (ce dossier, ou depuis la page RotorWeb → Réglages ▸ Home Assistant).
2. Copie-le dans le dossier `/config/www/` de Home Assistant
   (module « File editor » ou « Samba share » ; crée le dossier `www` s'il n'existe pas).
3. **Paramètres → Tableaux de bord → ⋮ → Ressources → Ajouter une ressource** :
   URL `/local/rotorweb-compass-card.js`, type **Module JavaScript**.
   (Pas de menu Ressources ? Active le « Mode avancé » dans ton profil utilisateur.)
4. Recharge la page (Ctrl+F5), puis ajoute une carte → **RotorWeb — Boussole**,
   ou en YAML : `type: custom:rotorweb-compass-card`

Options : `title`, `node` (si plusieurs RotorWeb), `compass_only: true` (version compacte), `passes: 4` (nombre de prochains passages satellites affichés, `0` = aucun).
La carte s'affiche en français ou en anglais selon la langue de ton profil Home Assistant.

## 4. Tableau de bord et automatisations
- `dashboard.yaml` : une vue Rotor complète (boussole, état, historique, journal).
- `automations.yaml` : notifications sur le téléphone, alertes prioritaires, K3NG débranché,
  hors opération en quittant la maison, l'anémomètre pour plus tard, et (v1.7) l'avertissement avant un passage satellite.

Remplace `rotorweb_ve2abc` par le nom de ton appareil dans ces fichiers.

## Nouveau en v1.7
- **Prochain bon passage satellite** (capteur texte) et **Heure du prochain bon passage** (horodatage) ;
  la liste des prochains passages est dans l'attribut `passes` (la carte boussole l'affiche).
- Événement **passage_sat** dans l'entité Notifications quand les alertes de passage sont actives.
- Le mode **Automatique (WSJT-X)** est retiré : le sélecteur Mode propose Manuel, Horaire et Suivi.
  Si une de tes automatisations choisissait « Automatique », change-la.
- Après la mise à jour, recopie `rotorweb-compass-card.js` dans `/config/www/` puis Ctrl+F5.
