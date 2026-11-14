# Câblage des contrôleurs « bidouille »

Deux montages au choix : **Arduino** (croquis RotorWeb DIY) ou **GPIO du Raspberry Pi** (relais + ADS1115).
Dans les deux cas, RotorWeb lit la position par une **tension** (potentiomètre du rotor ou sortie
de position du boîtier de commande) et commande le moteur par **deux relais** (horaire / anti-horaire).

> ⚠ **Sécurité**
> - Garde les **fins de course matériels** du rotor ou du boîtier : RotorWeb ajoute des limites logicielles,
>   mais elles ne remplacent pas une butée électrique.
> - Les relais commutent le **moteur** (souvent 24–30 V alternatif sur les Yaesu / Hy-Gain) : utilise des
>   relais prévus pour cette tension et ce courant, et isole bien les contacts.
> - **Mesure toujours** la tension de position au voltmètre avant de la brancher sur un Arduino (5 V max)
>   ou un ADS1115 alimenté en 3,3 V (3,3 V max). Certains boîtiers donnent bien plus que prévu.
> - Ne jamais activer les deux relais d'un même axe en même temps : le croquis et RotorWeb l'empêchent,
>   et imposent un **temps mort de 0,5 s** avant de changer de sens.

---

## 1. Version Arduino (Nano, Uno ou Mega)

| Arduino | Vers | Rôle |
|---|---|---|
| D4 | IN1 du module relais | Rotation horaire (droite) |
| D5 | IN2 du module relais | Rotation anti-horaire (gauche) |
| D6 | IN3 (option) | Élévation haut |
| D7 | IN4 (option) | Élévation bas |
| A0 | Curseur du potentiomètre / sortie de position | Position azimut (0–5 V) |
| A1 (option) | Sortie de position élévation | Position élévation (0–5 V) |
| 5V / GND | VCC / GND du module relais | Alimentation des relais |
| GND | Masse du boîtier de commande | Masse commune de la mesure |

Les broches se changent en haut du croquis `rotorweb_diy/rotorweb_diy.ino`.
Le téléversement se fait depuis le Raspberry Pi : `sudo /opt/rotorweb/firmware/flash_diy.sh`.

**Sécurité du croquis :** si le Raspberry Pi ne lui parle plus pendant 2 secondes, l'Arduino coupe tous les relais.

---

## 2. Version GPIO du Raspberry Pi (sans Arduino)

Le Raspberry Pi n'a pas d'entrée analogique : un module **ADS1115** (convertisseur 16 bits, I2C) lit la tension.

| Raspberry Pi (broche physique) | Vers | Rôle |
|---|---|---|
| GPIO17 (11) | IN1 du module relais | Rotation horaire |
| GPIO27 (13) | IN2 du module relais | Rotation anti-horaire |
| GPIO22 (15) | IN3 (option) | Élévation haut |
| GPIO23 (16) | IN4 (option) | Élévation bas |
| 3,3 V (1) | VDD de l'ADS1115 | Alimentation ADS1115 |
| GND (6) | GND de l'ADS1115 et du module relais | Masse |
| GPIO2 / SDA (3) | SDA de l'ADS1115 | Bus I2C |
| GPIO3 / SCL (5) | SCL de l'ADS1115 | Bus I2C |
| 5 V (2) | VCC du module relais | Alimentation des relais |
| — | A0 de l'ADS1115 | Tension de position azimut (**3,3 V max**) |
| — | A1 de l'ADS1115 (option) | Tension de position élévation |

- Choisis un module relais **compatible 3,3 V** (entrée optocouplée) : beaucoup de modules 5 V ne
  s'enclenchent pas de façon fiable avec les 3,3 V des GPIO.
- L'ADS1115 est alimenté en **3,3 V** : une tension de position plus haute (ex. 4,5 V) doit passer par un
  **diviseur** (ex. 10 kΩ en série + 15 kΩ vers la masse → ×0,6). La calibration absorbe le facteur.
- L'installateur active le bus I2C ; `i2cdetect -y 1` doit montrer `48`.
- Si RotorWeb s'arrête, les broches GPIO sont libérées et la plupart des modules relais retombent au repos.
  Pour une sécurité maximale, préfère la version Arduino (chien de garde matériel).

---

## 3. Brancher un rotor Yaesu sans l'ouvrir : la prise « External Control »

Les boîtiers de commande Yaesu ont une prise de commande externe : on y récupère la **tension de position**
et deux **contacts de rotation** (relier une broche à la masse fait tourner le rotor). Les relais du montage
servent alors de simples interrupteurs secs : un contact entre « droite » et la masse, l'autre entre « gauche »
et la masse.

**G-800DXA / G-1000DXA / G-2800DXA (mini-DIN 6 broches)**

| Broche | Signal |
|---|---|
| 4 | Tension de position : 2 à 4,5 V pour 0 à 450° |
| 5 | Masse commune |
| 2 | Gauche (anti-horaire) : relier à la masse pour tourner |
| 1 | Droite (horaire) : relier à la masse pour tourner — **à vérifier dans le manuel** |
| 3 | Commande de vitesse (non utilisée) |

**G-5500 / G-5400B / G-5600B (DIN 8 broches)**

| Broche | Signal |
|---|---|
| 6 | Tension de position azimut |
| 1 | Tension de position élévation |
| 2 | Droite (horaire) : relier à la broche 8 |
| 4 | Gauche (anti-horaire) : relier à la broche 8 |
| 3 | Haut : relier à la broche 8 |
| 5 | Bas : relier à la broche 8 |
| 8 | Masse commune |
| 7 | Tension d'alimentation (non utilisée) |

Des utilisateurs signalent sur certains G-5500 des tensions bien plus hautes que celles du manuel :
**mesure avant de brancher**, et ajoute un diviseur si besoin.

Pour un **rotor Hy-Gain / CDE** (HAM-IV, T2X…) ou un montage maison, on peut aussi lire directement le
potentiomètre du rotor (souvent 500 Ω) alimenté par une tension stable de 5 V (Arduino) ou 3,3 V (ADS1115),
en remplaçant le boîtier d'origine. Ce montage touche au câblage du rotor : à réserver aux bricoleurs à l'aise
avec le schéma de leur rotor.

---

## 4. Calibration (dans la page RotorWeb, Réglages ▸ Calibration)

1. Mets RotorWeb **En opération**.
2. Maintiens **Gauche** jusqu'à la butée gauche → **Enregistrer** (étape 1).
3. Maintiens **Droite** jusqu'à la butée droite → **Enregistrer** (étape 2).
4. Facultatif : pointe l'antenne sur des repères connus (Nord, une tour…) et ajoute des points.
   Plusieurs points corrigent un potentiomètre qui n'est pas parfaitement linéaire.
5. Règle l'**arrêt anticipé** (inertie : le rotor continue un peu après la coupure) et le
   **décalage de l'antenne** si elle n'est pas alignée avec le rotor.
