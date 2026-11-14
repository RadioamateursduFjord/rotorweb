# -*- coding: utf-8 -*-
"""
RotorWeb — recherche de position : grid, indicatif ou ville.

- Grid (FN46, JN18du) : calcul direct.
- Indicatif : HamQTH et/ou QRZ.com (comptes facultatifs), sinon le préfixe (pays approximatif).
- Ville : géocodage Open-Meteo (gratuit, sans compte).
"""
import logging
import re
import time
import xml.etree.ElementTree as ET

import aiohttp

from rotorweb.geo import bearing_distance, grid_to_latlon, latlon_to_grid, valid_grid

log = logging.getLogger("rotorweb")

HAMQTH = "https://www.hamqth.com/xml.php"
QRZ = "https://xmldata.qrz.com/xml/current/"
GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
CALL_RE = re.compile(r"^(?:[A-Z0-9]{1,4}/)?([A-Z0-9]{1,3}[0-9][A-Z0-9]{0,4}[A-Z])(?:/[A-Z0-9]{1,4})?$")
DEFAULT_LOOKUP = {"source": "both", "hamqth_user": "", "hamqth_pass": "", "qrz_user": "", "qrz_pass": ""}

# Préfixes → (pays, latitude, longitude). Le préfixe le plus long l'emporte.
# Approximation (capitale ou centre du pays) : suffisant pour orienter une antenne directive.
PREFIXES = [
    # Amérique du Nord
    ("VE1", "Canada – Nouvelle-Écosse", 45.0, -63.0), ("VE2", "Canada – Québec", 46.8, -71.2),
    ("VA2", "Canada – Québec", 46.8, -71.2), ("VE3", "Canada – Ontario", 44.0, -79.5),
    ("VA3", "Canada – Ontario", 44.0, -79.5), ("VE4", "Canada – Manitoba", 49.9, -97.1),
    ("VE5", "Canada – Saskatchewan", 52.1, -106.7), ("VE6", "Canada – Alberta", 51.0, -114.1),
    ("VA6", "Canada – Alberta", 51.0, -114.1), ("VE7", "Canada – Colombie-Britannique", 49.3, -123.1),
    ("VA7", "Canada – Colombie-Britannique", 49.3, -123.1), ("VE8", "Canada – Territoires du Nord-Ouest", 62.5, -114.4),
    ("VE9", "Canada – Nouveau-Brunswick", 45.9, -66.6), ("VO1", "Canada – Terre-Neuve", 47.6, -52.7),
    ("VO2", "Canada – Labrador", 53.3, -60.4), ("VY0", "Canada – Nunavut", 63.7, -68.5),
    ("VY1", "Canada – Yukon", 60.7, -135.1), ("VY2", "Canada – Île-du-Prince-Édouard", 46.2, -63.1),
    ("VE", "Canada", 45.4, -75.7), ("VA", "Canada", 45.4, -75.7), ("VO", "Canada – Terre-Neuve", 47.6, -52.7),
    ("VY", "Canada", 60.7, -135.1), ("CY", "Canada", 45.4, -75.7), ("XM", "Canada", 45.4, -75.7),
    ("KL7", "Alaska", 61.2, -149.9), ("AL7", "Alaska", 61.2, -149.9), ("NL7", "Alaska", 61.2, -149.9),
    ("WL7", "Alaska", 61.2, -149.9), ("KH6", "Hawaï", 21.3, -157.8), ("NH6", "Hawaï", 21.3, -157.8),
    ("WH6", "Hawaï", 21.3, -157.8), ("AH6", "Hawaï", 21.3, -157.8), ("KH2", "Guam", 13.5, 144.8),
    ("KP4", "Porto Rico", 18.4, -66.1), ("NP4", "Porto Rico", 18.4, -66.1), ("WP4", "Porto Rico", 18.4, -66.1),
    ("KP2", "Îles Vierges américaines", 18.3, -64.9),
    ("W1", "États-Unis – Nouvelle-Angleterre", 42.4, -71.1), ("W2", "États-Unis – New York / New Jersey", 40.7, -74.0),
    ("W3", "États-Unis – Pennsylvanie / Maryland", 39.9, -76.6), ("W4", "États-Unis – Sud-Est", 33.7, -84.4),
    ("W5", "États-Unis – Texas / Sud", 32.8, -96.8), ("W6", "États-Unis – Californie", 36.8, -119.8),
    ("W7", "États-Unis – Nord-Ouest", 42.0, -116.0), ("W8", "États-Unis – Michigan / Ohio", 41.5, -83.5),
    ("W9", "États-Unis – Illinois / Indiana", 41.9, -87.6), ("W0", "États-Unis – Centre", 40.0, -98.0),
    ("K", "États-Unis", 39.0, -96.0), ("W", "États-Unis", 39.0, -96.0), ("N", "États-Unis", 39.0, -96.0),
    ("AA", "États-Unis", 39.0, -96.0), ("AB", "États-Unis", 39.0, -96.0), ("AC", "États-Unis", 39.0, -96.0),
    ("AD", "États-Unis", 39.0, -96.0), ("AE", "États-Unis", 39.0, -96.0), ("AF", "États-Unis", 39.0, -96.0),
    ("AG", "États-Unis", 39.0, -96.0), ("AI", "États-Unis", 39.0, -96.0), ("AJ", "États-Unis", 39.0, -96.0),
    ("AK", "États-Unis", 39.0, -96.0),
    ("XE", "Mexique", 19.4, -99.1), ("XF", "Mexique", 19.4, -99.1), ("4A", "Mexique", 19.4, -99.1),
    ("6Y", "Jamaïque", 18.0, -76.8), ("CO", "Cuba", 23.1, -82.4), ("CM", "Cuba", 23.1, -82.4), ("T4", "Cuba", 23.1, -82.4),
    ("HI", "République dominicaine", 18.5, -69.9), ("HH", "Haïti", 18.5, -72.3), ("TI", "Costa Rica", 9.9, -84.1),
    ("TG", "Guatemala", 14.6, -90.5), ("YN", "Nicaragua", 12.1, -86.3), ("HR", "Honduras", 14.1, -87.2),
    ("YS", "Salvador", 13.7, -89.2), ("HP", "Panama", 9.0, -79.5), ("V3", "Belize", 17.3, -88.8),
    ("C6", "Bahamas", 25.1, -77.3), ("VP9", "Bermudes", 32.3, -64.8), ("8P", "Barbade", 13.1, -59.6),
    ("9Y", "Trinité-et-Tobago", 10.7, -61.5), ("FG", "Guadeloupe", 16.2, -61.5), ("FM", "Martinique", 14.6, -61.0),
    ("FP", "Saint-Pierre-et-Miquelon", 46.8, -56.2), ("PJ2", "Curaçao", 12.1, -68.9), ("P4", "Aruba", 12.5, -70.0),
    ("J3", "Grenade", 12.1, -61.7), ("J6", "Sainte-Lucie", 14.0, -61.0), ("V2", "Antigua", 17.1, -61.8),
    # Amérique du Sud
    ("PY", "Brésil", -23.5, -46.6), ("PP", "Brésil", -23.5, -46.6), ("PU", "Brésil", -23.5, -46.6),
    ("PT", "Brésil", -15.8, -47.9), ("PR", "Brésil", -8.0, -34.9), ("PS", "Brésil", -5.8, -35.2),
    ("ZP", "Paraguay", -25.3, -57.6), ("CX", "Uruguay", -34.9, -56.2), ("LU", "Argentine", -34.6, -58.4),
    ("LW", "Argentine", -34.6, -58.4), ("AY", "Argentine", -34.6, -58.4), ("L2", "Argentine", -34.6, -58.4),
    ("CE", "Chili", -33.4, -70.6), ("CA", "Chili", -33.4, -70.6), ("XQ", "Chili", -33.4, -70.6),
    ("CE0Y", "Île de Pâques", -27.1, -109.4), ("OA", "Pérou", -12.0, -77.0), ("OC", "Pérou", -12.0, -77.0),
    ("CP", "Bolivie", -16.5, -68.1), ("HC", "Équateur", -0.2, -78.5), ("HC8", "Galápagos", -0.9, -89.6),
    ("HK", "Colombie", 4.7, -74.1), ("5J", "Colombie", 4.7, -74.1), ("YV", "Venezuela", 10.5, -66.9),
    ("YY", "Venezuela", 10.5, -66.9), ("8R", "Guyana", 6.8, -58.2), ("PZ", "Suriname", 5.9, -55.2),
    ("FY", "Guyane", 4.9, -52.3), ("VP8", "Malouines", -51.7, -57.9),
    # Europe
    ("F", "France", 46.6, 2.4), ("TM", "France", 46.6, 2.4), ("TK", "Corse", 42.0, 9.0),
    ("G", "Angleterre", 52.5, -1.5), ("M", "Angleterre", 52.5, -1.5), ("2E", "Angleterre", 52.5, -1.5),
    ("GM", "Écosse", 56.5, -4.2), ("MM", "Écosse", 56.5, -4.2), ("GW", "Pays de Galles", 52.3, -3.6),
    ("MW", "Pays de Galles", 52.3, -3.6), ("GI", "Irlande du Nord", 54.6, -6.6), ("MI", "Irlande du Nord", 54.6, -6.6),
    ("GD", "Île de Man", 54.2, -4.5), ("GJ", "Jersey", 49.2, -2.1), ("GU", "Guernesey", 49.5, -2.6),
    ("EI", "Irlande", 53.3, -7.7), ("EJ", "Irlande", 53.3, -7.7), ("ON", "Belgique", 50.8, 4.4),
    ("OO", "Belgique", 50.8, 4.4), ("OT", "Belgique", 50.8, 4.4), ("PA", "Pays-Bas", 52.2, 5.3),
    ("PB", "Pays-Bas", 52.2, 5.3), ("PD", "Pays-Bas", 52.2, 5.3), ("PE", "Pays-Bas", 52.2, 5.3),
    ("PH", "Pays-Bas", 52.2, 5.3), ("LX", "Luxembourg", 49.6, 6.1), ("DL", "Allemagne", 51.2, 10.4),
    ("DA", "Allemagne", 51.2, 10.4), ("DB", "Allemagne", 51.2, 10.4), ("DC", "Allemagne", 51.2, 10.4),
    ("DD", "Allemagne", 51.2, 10.4), ("DF", "Allemagne", 51.2, 10.4), ("DG", "Allemagne", 51.2, 10.4),
    ("DH", "Allemagne", 51.2, 10.4), ("DJ", "Allemagne", 51.2, 10.4), ("DK", "Allemagne", 51.2, 10.4),
    ("DM", "Allemagne", 51.2, 10.4), ("DO", "Allemagne", 51.2, 10.4), ("DP", "Allemagne", 51.2, 10.4),
    ("HB0", "Liechtenstein", 47.1, 9.5), ("HB", "Suisse", 46.9, 8.2), ("OE", "Autriche", 47.6, 14.1),
    ("I", "Italie", 42.5, 12.5), ("IS0", "Sardaigne", 40.0, 9.0), ("IT9", "Sicile", 37.5, 14.0),
    ("T7", "Saint-Marin", 43.9, 12.4), ("HV", "Vatican", 41.9, 12.5), ("9H", "Malte", 35.9, 14.4),
    ("EA", "Espagne", 40.4, -3.7), ("EB", "Espagne", 40.4, -3.7), ("EC", "Espagne", 40.4, -3.7),
    ("EA6", "Baléares", 39.6, 2.9), ("EA8", "Canaries", 28.3, -15.6), ("EA9", "Ceuta / Melilla", 35.9, -5.3),
    ("C3", "Andorre", 42.5, 1.5), ("CT", "Portugal", 39.4, -8.2), ("CS", "Portugal", 39.4, -8.2),
    ("CU", "Açores", 38.7, -27.2), ("CT3", "Madère", 32.7, -16.9), ("3A", "Monaco", 43.7, 7.4),
    ("OZ", "Danemark", 56.0, 10.0), ("OU", "Danemark", 56.0, 10.0), ("OX", "Groenland", 64.2, -51.7),
    ("OY", "Îles Féroé", 62.0, -6.8), ("LA", "Norvège", 60.5, 8.5), ("LB", "Norvège", 60.5, 8.5),
    ("JW", "Svalbard", 78.2, 15.6), ("JX", "Jan Mayen", 71.0, -8.3), ("SM", "Suède", 59.3, 18.1),
    ("SA", "Suède", 59.3, 18.1), ("SK", "Suède", 59.3, 18.1), ("7S", "Suède", 59.3, 18.1),
    ("OH", "Finlande", 60.2, 24.9), ("OG", "Finlande", 60.2, 24.9), ("OH0", "Åland", 60.1, 19.9),
    ("TF", "Islande", 64.1, -21.9), ("ES", "Estonie", 59.4, 24.8), ("YL", "Lettonie", 56.9, 24.1),
    ("LY", "Lituanie", 54.7, 25.3), ("SP", "Pologne", 52.2, 21.0), ("SQ", "Pologne", 52.2, 21.0),
    ("SN", "Pologne", 52.2, 21.0), ("SO", "Pologne", 52.2, 21.0), ("3Z", "Pologne", 52.2, 21.0),
    ("OK", "Tchéquie", 50.1, 14.4), ("OL", "Tchéquie", 50.1, 14.4), ("OM", "Slovaquie", 48.1, 17.1),
    ("HA", "Hongrie", 47.5, 19.0), ("HG", "Hongrie", 47.5, 19.0), ("S5", "Slovénie", 46.1, 14.5),
    ("9A", "Croatie", 45.8, 16.0), ("E7", "Bosnie-Herzégovine", 43.9, 18.4), ("YU", "Serbie", 44.8, 20.5),
    ("YT", "Serbie", 44.8, 20.5), ("4O", "Monténégro", 42.4, 19.3), ("Z3", "Macédoine du Nord", 42.0, 21.4),
    ("ZA", "Albanie", 41.3, 19.8), ("Z6", "Kosovo", 42.7, 21.2), ("YO", "Roumanie", 44.4, 26.1),
    ("YP", "Roumanie", 44.4, 26.1), ("YQ", "Roumanie", 44.4, 26.1), ("YR", "Roumanie", 44.4, 26.1),
    ("ER", "Moldavie", 47.0, 28.8), ("LZ", "Bulgarie", 42.7, 23.3), ("SV", "Grèce", 37.98, 23.7),
    ("SX", "Grèce", 37.98, 23.7), ("SV9", "Crète", 35.3, 25.1), ("SV5", "Dodécanèse", 36.4, 28.2),
    ("SY", "Mont Athos", 40.2, 24.3), ("5B", "Chypre", 35.2, 33.4), ("C4", "Chypre", 35.2, 33.4),
    ("P3", "Chypre", 35.2, 33.4), ("TA", "Turquie", 39.9, 32.9), ("TC", "Turquie", 39.9, 32.9),
    ("YM", "Turquie", 39.9, 32.9), ("UR", "Ukraine", 50.5, 30.5), ("UT", "Ukraine", 50.5, 30.5),
    ("UX", "Ukraine", 50.5, 30.5), ("US", "Ukraine", 50.5, 30.5), ("UY", "Ukraine", 50.5, 30.5),
    ("EM", "Ukraine", 50.5, 30.5), ("EO", "Ukraine", 50.5, 30.5), ("EW", "Biélorussie", 53.9, 27.6),
    ("EU", "Biélorussie", 53.9, 27.6), ("UA2", "Kaliningrad", 54.7, 20.5), ("RA2", "Kaliningrad", 54.7, 20.5),
    ("R", "Russie (Europe)", 55.8, 37.6), ("UA", "Russie (Europe)", 55.8, 37.6), ("U", "Russie (Europe)", 55.8, 37.6),
    ("UA9", "Russie (Asie)", 55.0, 73.4), ("RA9", "Russie (Asie)", 55.0, 73.4), ("R9", "Russie (Asie)", 55.0, 73.4),
    ("UA0", "Russie (Asie)", 52.3, 104.3), ("RA0", "Russie (Asie)", 52.3, 104.3), ("R0", "Russie (Asie)", 52.3, 104.3),
    ("UA8", "Russie (Asie)", 55.0, 82.9), ("UN", "Kazakhstan", 51.2, 71.4), ("UP", "Kazakhstan", 51.2, 71.4),
    ("4L", "Géorgie", 41.7, 44.8), ("EK", "Arménie", 40.2, 44.5), ("4K", "Azerbaïdjan", 40.4, 49.9),
    # Afrique
    ("CN", "Maroc", 34.0, -6.8), ("7X", "Algérie", 36.8, 3.1), ("3V", "Tunisie", 36.8, 10.2),
    ("5A", "Libye", 32.9, 13.2), ("SU", "Égypte", 30.0, 31.2), ("ST", "Soudan", 15.5, 32.5),
    ("ET", "Éthiopie", 9.0, 38.7), ("5Z", "Kenya", -1.3, 36.8), ("5H", "Tanzanie", -6.8, 39.3),
    ("5X", "Ouganda", 0.3, 32.6), ("9X", "Rwanda", -1.9, 30.1), ("9J", "Zambie", -15.4, 28.3),
    ("Z2", "Zimbabwe", -17.8, 31.0), ("C9", "Mozambique", -25.9, 32.6), ("7Q", "Malawi", -14.0, 33.8),
    ("A2", "Botswana", -24.7, 25.9), ("V5", "Namibie", -22.6, 17.1), ("ZS", "Afrique du Sud", -26.2, 28.0),
    ("ZR", "Afrique du Sud", -26.2, 28.0), ("ZU", "Afrique du Sud", -26.2, 28.0), ("ZS8", "Îles du Prince-Édouard", -46.9, 37.8),
    ("3DA", "Eswatini", -26.3, 31.1), ("7P", "Lesotho", -29.3, 27.5), ("5R", "Madagascar", -18.9, 47.5),
    ("3B8", "Maurice", -20.2, 57.5), ("FR", "La Réunion", -20.9, 55.5), ("FH", "Mayotte", -12.8, 45.2),
    ("D6", "Comores", -11.7, 43.3), ("S7", "Seychelles", -4.6, 55.5), ("6W", "Sénégal", 14.7, -17.4),
    ("C5", "Gambie", 13.5, -16.6), ("J5", "Guinée-Bissau", 11.9, -15.6), ("3X", "Guinée", 9.5, -13.7),
    ("9L", "Sierra Leone", 8.5, -13.2), ("EL", "Liberia", 6.3, -10.8), ("TU", "Côte d'Ivoire", 5.3, -4.0),
    ("9G", "Ghana", 5.6, -0.2), ("5V", "Togo", 6.1, 1.2), ("TY", "Bénin", 6.5, 2.6), ("5N", "Nigeria", 9.1, 7.5),
    ("TJ", "Cameroun", 3.9, 11.5), ("TR", "Gabon", 0.4, 9.5), ("TN", "Congo", -4.3, 15.3),
    ("9Q", "RD Congo", -4.3, 15.3), ("D2", "Angola", -8.8, 13.2), ("TT", "Tchad", 12.1, 15.0),
    ("5U", "Niger", 13.5, 2.1), ("TZ", "Mali", 12.6, -8.0), ("XT", "Burkina Faso", 12.4, -1.5),
    ("5T", "Mauritanie", 18.1, -15.9), ("D4", "Cap-Vert", 14.9, -23.5), ("S9", "Sao Tomé", 0.3, 6.7),
    ("3C", "Guinée équatoriale", 3.8, 8.8), ("TL", "Centrafrique", 4.4, 18.6), ("J2", "Djibouti", 11.6, 43.1),
    ("6O", "Somalie", 2.0, 45.3), ("E3", "Érythrée", 15.3, 38.9), ("ZD7", "Sainte-Hélène", -15.9, -5.7),
    ("ZD8", "Ascension", -7.9, -14.4), ("ZD9", "Tristan da Cunha", -37.1, -12.3),
    # Asie / Moyen-Orient
    ("4X", "Israël", 31.8, 35.2), ("4Z", "Israël", 31.8, 35.2), ("E4", "Palestine", 31.9, 35.2),
    ("JY", "Jordanie", 31.9, 35.9), ("OD", "Liban", 33.9, 35.5), ("YK", "Syrie", 33.5, 36.3),
    ("YI", "Irak", 33.3, 44.4), ("EP", "Iran", 35.7, 51.4), ("HZ", "Arabie saoudite", 24.7, 46.7),
    ("7Z", "Arabie saoudite", 24.7, 46.7), ("A4", "Oman", 23.6, 58.4), ("A6", "Émirats arabes unis", 24.5, 54.4),
    ("A7", "Qatar", 25.3, 51.5), ("A9", "Bahreïn", 26.2, 50.6), ("9K", "Koweït", 29.4, 48.0),
    ("7O", "Yémen", 15.4, 44.2), ("YA", "Afghanistan", 34.5, 69.2), ("AP", "Pakistan", 33.7, 73.1),
    ("VU", "Inde", 28.6, 77.2), ("AT", "Inde", 28.6, 77.2), ("VU4", "Andaman", 11.7, 92.7),
    ("VU7", "Lakshadweep", 10.6, 72.6), ("4S", "Sri Lanka", 6.9, 79.9), ("8Q", "Maldives", 4.2, 73.5),
    ("9N", "Népal", 27.7, 85.3), ("A5", "Bhoutan", 27.5, 89.6), ("S2", "Bangladesh", 23.8, 90.4),
    ("XZ", "Myanmar", 16.8, 96.2), ("HS", "Thaïlande", 13.8, 100.5), ("E2", "Thaïlande", 13.8, 100.5),
    ("XW", "Laos", 18.0, 102.6), ("XU", "Cambodge", 11.6, 104.9), ("3W", "Vietnam", 21.0, 105.8),
    ("XV", "Vietnam", 21.0, 105.8), ("9M2", "Malaisie (ouest)", 3.1, 101.7), ("9M6", "Malaisie (est)", 5.98, 116.1),
    ("9M8", "Malaisie (est)", 1.6, 110.3), ("9W", "Malaisie", 3.1, 101.7), ("9V", "Singapour", 1.35, 103.8),
    ("YB", "Indonésie", -6.2, 106.8), ("YC", "Indonésie", -6.2, 106.8), ("YD", "Indonésie", -6.2, 106.8),
    ("YE", "Indonésie", -6.2, 106.8), ("YF", "Indonésie", -6.2, 106.8), ("YG", "Indonésie", -6.2, 106.8),
    ("YH", "Indonésie", -6.2, 106.8), ("V8", "Brunei", 4.9, 114.9), ("DU", "Philippines", 14.6, 121.0),
    ("DV", "Philippines", 14.6, 121.0), ("DW", "Philippines", 14.6, 121.0), ("DX", "Philippines", 14.6, 121.0),
    ("4F", "Philippines", 14.6, 121.0), ("4W", "Timor oriental", -8.6, 125.6),
    ("BY", "Chine", 39.9, 116.4), ("BA", "Chine", 39.9, 116.4), ("BD", "Chine", 39.9, 116.4),
    ("BG", "Chine", 39.9, 116.4), ("BH", "Chine", 39.9, 116.4), ("BI", "Chine", 39.9, 116.4),
    ("B", "Chine", 39.9, 116.4), ("BV", "Taïwan", 25.0, 121.5), ("BX", "Taïwan", 25.0, 121.5),
    ("BU", "Taïwan", 25.0, 121.5), ("BM", "Taïwan", 25.0, 121.5), ("BN", "Taïwan", 25.0, 121.5),
    ("BO", "Taïwan", 25.0, 121.5), ("BP", "Taïwan", 25.0, 121.5), ("BQ", "Taïwan", 25.0, 121.5),
    ("VR", "Hong Kong", 22.3, 114.2), ("XX9", "Macao", 22.2, 113.5), ("JT", "Mongolie", 47.9, 106.9),
    ("HL", "Corée du Sud", 37.6, 127.0), ("DS", "Corée du Sud", 37.6, 127.0), ("DT", "Corée du Sud", 37.6, 127.0),
    ("6K", "Corée du Sud", 37.6, 127.0), ("6L", "Corée du Sud", 37.6, 127.0), ("P5", "Corée du Nord", 39.0, 125.8),
    ("JA", "Japon", 35.7, 139.7), ("JE", "Japon", 35.7, 139.7), ("JF", "Japon", 35.7, 139.7),
    ("JG", "Japon", 35.7, 139.7), ("JH", "Japon", 35.7, 139.7), ("JI", "Japon", 35.7, 139.7),
    ("JJ", "Japon", 35.7, 139.7), ("JK", "Japon", 35.7, 139.7), ("JL", "Japon", 35.7, 139.7),
    ("JM", "Japon", 35.7, 139.7), ("JN", "Japon", 35.7, 139.7), ("JO", "Japon", 35.7, 139.7),
    ("JP", "Japon", 35.7, 139.7), ("JQ", "Japon", 35.7, 139.7), ("JR", "Japon", 35.7, 139.7),
    ("JS", "Japon", 35.7, 139.7), ("7J", "Japon", 35.7, 139.7), ("7K", "Japon", 35.7, 139.7),
    ("7L", "Japon", 35.7, 139.7), ("7M", "Japon", 35.7, 139.7), ("7N", "Japon", 35.7, 139.7),
    ("8J", "Japon", 35.7, 139.7), ("JA6", "Japon – Kyushu", 33.6, 130.4), ("JA8", "Japon – Hokkaido", 43.1, 141.4),
    ("JD1", "Ogasawara", 27.1, 142.2), ("UK", "Ouzbékistan", 41.3, 69.2), ("EX", "Kirghizistan", 42.9, 74.6),
    ("EY", "Tadjikistan", 38.6, 68.8), ("EZ", "Turkménistan", 37.9, 58.4),
    # Océanie
    ("VK", "Australie", -33.9, 151.2), ("AX", "Australie", -33.9, 151.2), ("VK2", "Australie – NSW", -33.9, 151.2),
    ("VK3", "Australie – Victoria", -37.8, 145.0), ("VK4", "Australie – Queensland", -27.5, 153.0),
    ("VK5", "Australie – Sud", -34.9, 138.6), ("VK6", "Australie – Ouest", -31.95, 115.9),
    ("VK7", "Tasmanie", -42.9, 147.3), ("VK8", "Australie – Nord", -12.5, 130.8), ("VK9", "Îles australiennes", -29.0, 168.0),
    ("ZL", "Nouvelle-Zélande", -36.8, 174.8), ("ZM", "Nouvelle-Zélande", -36.8, 174.8),
    ("ZL7", "Îles Chatham", -43.95, -176.5), ("FK", "Nouvelle-Calédonie", -22.3, 166.5),
    ("FO", "Polynésie française", -17.5, -149.6), ("FW", "Wallis-et-Futuna", -13.3, -176.2),
    ("YJ", "Vanuatu", -17.7, 168.3), ("3D2", "Fidji", -18.1, 178.4), ("5W", "Samoa", -13.8, -171.8),
    ("A3", "Tonga", -21.1, -175.2), ("H4", "Îles Salomon", -9.4, 160.0), ("P2", "Papouasie-Nouvelle-Guinée", -9.4, 147.2),
    ("T2", "Tuvalu", -8.5, 179.2), ("T3", "Kiribati", 1.4, 173.0), ("V7", "Îles Marshall", 7.1, 171.4),
    ("V6", "Micronésie", 6.9, 158.2), ("T8", "Palaos", 7.3, 134.5), ("KH8", "Samoa américaines", -14.3, -170.7),
    ("E5", "Îles Cook", -21.2, -159.8), ("ZK3", "Tokelau", -9.2, -171.8), ("C2", "Nauru", -0.5, 166.9),
    ("VP6", "Pitcairn", -25.1, -130.1),
    # Antarctique
    ("KC4", "Antarctique", -77.8, 166.7), ("VP8", "Malouines / Antarctique", -51.7, -57.9),
]
_PREFIX_SORTED = sorted(PREFIXES, key=lambda p: -len(p[0]))


def classify(q):
    q = (q or "").strip()
    u = q.upper().replace(" ", "")
    if valid_grid(u):
        return "grid", u
    if CALL_RE.match(u) and any(c.isdigit() for c in u) and len(u) <= 14:
        return "call", u
    return "city", q


def base_call(call):
    """VE2/F4ABC/P → F4ABC ; F4ABC/VE2 → VE2 sert de préfixe."""
    parts = call.upper().split("/")
    if len(parts) == 1:
        return parts[0], parts[0]
    main = max(parts, key=len)
    pfx = main
    for p in parts:
        if p != main and len(p) >= 2 and not p.isdigit() and p not in ("P", "M", "MM", "AM", "QRP", "A"):
            pfx = p  # préfixe de pays explicite (F4ABC/VE2 ou VE2/F4ABC)
    return main, pfx


def prefix_lookup(call):
    _, pfx = base_call(call)
    for p, country, lat, lon in _PREFIX_SORTED:
        if pfx.startswith(p):
            return {"label": country, "lat": lat, "lon": lon, "source": "prefix", "approx": True}
    return None


class Lookup:
    def __init__(self, ctrl):
        self.ctrl = ctrl
        self.hamqth_sid = (None, 0.0)
        self.qrz_key = (None, 0.0)
        self.cache = {}

    def cfg(self):
        c = self.ctrl.cfg.setdefault("lookup", {})
        for k, v in DEFAULT_LOOKUP.items():
            c.setdefault(k, v)
        return c

    def public(self):
        c = self.cfg()
        return {"source": c["source"], "hamqth_user": c["hamqth_user"], "qrz_user": c["qrz_user"],
                "hamqth_has_pass": bool(c["hamqth_pass"]), "qrz_has_pass": bool(c["qrz_pass"])}

    # ---------------------------------------------------------------- services
    async def _hamqth(self, s, call):
        c = self.cfg()
        if not (c["hamqth_user"] and c["hamqth_pass"]):
            return None
        sid, t = self.hamqth_sid
        if not sid or time.time() - t > 3000:
            async with s.get(HAMQTH, params={"u": c["hamqth_user"], "p": c["hamqth_pass"]}) as r:
                root = ET.fromstring(await r.text())
            sid = _find(root, "session_id")
            if not sid:
                raise ValueError("HamQTH : " + (_find(root, "error") or "connexion refusée"))
            self.hamqth_sid = (sid, time.time())
        async with s.get(HAMQTH, params={"id": sid, "callsign": call, "prg": "RotorWeb"}) as r:
            root = ET.fromstring(await r.text())
        err = _find(root, "error")
        if err:
            if "session" in err.lower():
                self.hamqth_sid = (None, 0)
            if "not found" in err.lower():
                return None
            raise ValueError(f"HamQTH : {err}")
        return _record(root, call, "HamQTH", ("grid",), ("latitude",), ("longitude",),
                       ("adr_city", "qth"), ("country",), ("nick", "adr_name"))

    async def _qrz(self, s, call):
        c = self.cfg()
        if not (c["qrz_user"] and c["qrz_pass"]):
            return None
        key, t = self.qrz_key
        if not key or time.time() - t > 3000:
            async with s.get(QRZ, params={"username": c["qrz_user"], "password": c["qrz_pass"], "agent": "RotorWeb"}) as r:
                root = ET.fromstring(await r.text())
            key = _find(root, "Key")
            if not key:
                raise ValueError("QRZ : " + (_find(root, "Error") or "connexion refusée"))
            self.qrz_key = (key, time.time())
        async with s.get(QRZ, params={"s": key, "callsign": call}) as r:
            root = ET.fromstring(await r.text())
        err = _find(root, "Error")
        if err and not _find(root, "call"):
            if "session" in err.lower() or "invalid" in err.lower() and "key" in err.lower():
                self.qrz_key = (None, 0)
            if "not found" in err.lower():
                return None
            raise ValueError(f"QRZ : {err}")
        return _record(root, call, "QRZ", ("grid",), ("lat",), ("lon",), ("addr2",), ("country",), ("fname",))

    async def _city(self, s, q, lang):
        async with s.get(GEOCODE, params={"name": q, "count": 6, "language": lang, "format": "json"}) as r:
            r.raise_for_status()
            data = await r.json()
        out = []
        for it in data.get("results") or []:
            parts = [it.get("name"), it.get("admin1"), it.get("country")]
            label = ", ".join(dict.fromkeys(p for p in parts if p))
            out.append({"label": label, "lat": float(it["latitude"]), "lon": float(it["longitude"]),
                        "source": "Open-Meteo"})
        return out

    # ---------------------------------------------------------------- recherche
    async def search(self, q, lang="fr"):
        kind, val = classify(q)
        home = self.ctrl.cfg.get("grid")
        notes = []
        results = []
        if kind == "grid":
            lat, lon = grid_to_latlon(val)
            results = [{"label": val, "lat": lat, "lon": lon, "source": "grid", "grid": val}]
        else:
            ck = (kind, val.upper(), lang)
            hit = self.cache.get(ck)
            if hit and time.time() - hit[0] < 3600:
                results = hit[1]
            else:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as s:
                    if kind == "call":
                        main, _ = base_call(val)
                        order = {"hamqth": ["hamqth"], "qrz": ["qrz"], "both": ["hamqth", "qrz"],
                                 "qrz_first": ["qrz", "hamqth"], "prefix": []}.get(self.cfg()["source"], ["hamqth", "qrz"])
                        for svc in order:
                            try:
                                r = await (self._hamqth(s, main) if svc == "hamqth" else self._qrz(s, main))
                            except Exception as e:
                                notes.append(str(e) or type(e).__name__)
                                continue
                            if r:
                                results = [r]
                                break
                        if not results:
                            p = prefix_lookup(val)
                            if p:
                                p["label"] = f"{val} — {p['label']}"
                                results = [p]
                    else:
                        try:
                            results = await self._city(s, val, lang)
                        except Exception as e:
                            notes.append(f"Open-Meteo : {e or type(e).__name__}")
                if results:
                    self.cache[ck] = (time.time(), results)
        for r in results:
            if not r.get("grid"):
                r["grid"] = latlon_to_grid(r["lat"], r["lon"])
            if valid_grid(home):
                hl, ho = grid_to_latlon(home)
                b, d = bearing_distance(hl, ho, r["lat"], r["lon"])
                r["sp"], r["lp"], r["km"] = round(b) % 360, round(b + 180) % 360, round(d)
        return {"type": "lookup", "q": q, "kind": kind, "results": results, "notes": notes,
                "no_home": not valid_grid(home)}


def _find(root, tag):
    for el in root.iter():
        if el.tag.split("}")[-1] == tag and (el.text or "").strip():
            return el.text.strip()
    return None


def _record(root, call, source, grid_tags, lat_tags, lon_tags, city_tags, country_tags, name_tags):
    def first(tags):
        for t in tags:
            v = _find(root, t)
            if v:
                return v
        return None
    grid = (first(grid_tags) or "").upper()
    lat, lon = first(lat_tags), first(lon_tags)
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        lat = lon = None
    if lat is None and valid_grid(grid):
        lat, lon = grid_to_latlon(grid)
    if lat is None:
        return None
    where = ", ".join(x for x in (first(city_tags), first(country_tags)) if x)
    return {"label": f"{call}" + (f" — {where}" if where else ""), "lat": lat, "lon": lon,
            "grid": grid if valid_grid(grid) else None, "source": source}
