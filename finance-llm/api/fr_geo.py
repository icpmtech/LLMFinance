"""Posições de França para o mapa dos contratos (gerado por `_gen_fr_geo.py`).

**Não editar à mão.** Cada entrada é `dict(code={...})` com `lat`, `lon` e `nom`.

- Departamentos: centro de massa do polígono oficial (`gregoiredavid/france-geojson`).
- Regiões: centro de massa dos seus departamentos (mapeamento `geo.api.gouv.fr`).
- Ultramar: coordenadas da prefeitura (não há polígonos metropolitanos para lá).
"""

from __future__ import annotations

from typing import Any, Dict

#: Centro de massa da França metropolitana (usado no nível «país»).
FR_COUNTRY_CENTROID = {"lat": 46.6, "lon": 2.5, "nom": "França"}

#: Departamentos metropolitanos (96) — centro de massa do polígono.
FR_DEPARTMENT_CENTROIDS: Dict[str, Dict[str, Any]] = {

    "01": {"lat": 46.0997, "lon": 5.3487, "nom": "Ain"},
    "02": {"lat": 49.5610, "lon": 3.5592, "nom": "Aisne"},
    "03": {"lat": 46.3936, "lon": 3.1877, "nom": "Allier"},
    "04": {"lat": 44.1062, "lon": 6.2448, "nom": "Alpes-de-Haute-Provence"},
    "05": {"lat": 44.6638, "lon": 6.2650, "nom": "Hautes-Alpes"},
    "06": {"lat": 43.9382, "lon": 7.1163, "nom": "Alpes-Maritimes"},
    "07": {"lat": 44.7527, "lon": 4.4256, "nom": "Ardèche"},
    "08": {"lat": 49.6162, "lon": 4.6407, "nom": "Ardennes"},
    "09": {"lat": 42.9210, "lon": 1.5036, "nom": "Ariège"},
    "10": {"lat": 48.3046, "lon": 4.1614, "nom": "Aube"},
    "11": {"lat": 43.1032, "lon": 2.4137, "nom": "Aude"},
    "12": {"lat": 44.2811, "lon": 2.6785, "nom": "Aveyron"},
    "13": {"lat": 43.5433, "lon": 5.0857, "nom": "Bouches-du-Rhône"},
    "14": {"lat": 49.0998, "lon": -0.3616, "nom": "Calvados"},
    "15": {"lat": 45.0512, "lon": 2.6690, "nom": "Cantal"},
    "16": {"lat": 45.7187, "lon": 0.2031, "nom": "Charente"},
    "17": {"lat": 45.7657, "lon": -0.6542, "nom": "Charente-Maritime"},
    "18": {"lat": 47.0658, "lon": 2.4911, "nom": "Cher"},
    "19": {"lat": 45.3573, "lon": 1.8777, "nom": "Corrèze"},
    "20": {"lat": 42.1517, "lon": 9.1060, "nom": "Corse (código postal 20)"},
    "21": {"lat": 47.4261, "lon": 4.7727, "nom": "Côte-d'Or"},
    "22": {"lat": 48.4405, "lon": -2.8645, "nom": "Côtes-d'Armor"},
    "23": {"lat": 46.0906, "lon": 2.0182, "nom": "Creuse"},
    "24": {"lat": 45.1049, "lon": 0.7412, "nom": "Dordogne"},
    "25": {"lat": 47.1659, "lon": 6.3627, "nom": "Doubs"},
    "26": {"lat": 44.6791, "lon": 5.1635, "nom": "Drôme"},
    "27": {"lat": 49.1137, "lon": 0.9964, "nom": "Eure"},
    "28": {"lat": 48.3880, "lon": 1.3700, "nom": "Eure-et-Loir"},
    "29": {"lat": 48.2611, "lon": -4.0571, "nom": "Finistère"},
    "2A": {"lat": 41.8643, "lon": 8.9875, "nom": "Corse-du-Sud"},
    "2B": {"lat": 42.3949, "lon": 9.2062, "nom": "Haute-Corse"},
    "30": {"lat": 43.9936, "lon": 4.1799, "nom": "Gard"},
    "31": {"lat": 43.3589, "lon": 1.1750, "nom": "Haute-Garonne"},
    "32": {"lat": 43.6929, "lon": 0.4529, "nom": "Gers"},
    "33": {"lat": 44.8390, "lon": -0.5831, "nom": "Gironde"},
    "34": {"lat": 43.5795, "lon": 3.3685, "nom": "Hérault"},
    "35": {"lat": 48.1509, "lon": -1.6341, "nom": "Ille-et-Vilaine"},
    "36": {"lat": 46.7783, "lon": 1.5760, "nom": "Indre"},
    "37": {"lat": 47.2585, "lon": 0.6911, "nom": "Indre-et-Loire"},
    "38": {"lat": 45.2639, "lon": 5.5742, "nom": "Isère"},
    "39": {"lat": 46.7293, "lon": 5.6974, "nom": "Jura"},
    "40": {"lat": 43.9658, "lon": -0.7837, "nom": "Landes"},
    "41": {"lat": 47.6168, "lon": 1.4279, "nom": "Loir-et-Cher"},
    "42": {"lat": 45.7280, "lon": 4.1646, "nom": "Loire"},
    "43": {"lat": 45.1281, "lon": 3.8063, "nom": "Haute-Loire"},
    "44": {"lat": 47.3630, "lon": -1.6792, "nom": "Loire-Atlantique"},
    "45": {"lat": 47.9119, "lon": 2.3440, "nom": "Loiret"},
    "46": {"lat": 44.6246, "lon": 1.6055, "nom": "Lot"},
    "47": {"lat": 44.3679, "lon": 0.4607, "nom": "Lot-et-Garonne"},
    "48": {"lat": 44.5175, "lon": 3.4997, "nom": "Lozère"},
    "49": {"lat": 47.3898, "lon": -0.5594, "nom": "Maine-et-Loire"},
    "50": {"lat": 49.0813, "lon": -1.3288, "nom": "Manche"},
    "51": {"lat": 48.9499, "lon": 4.2385, "nom": "Marne"},
    "52": {"lat": 48.1104, "lon": 5.2255, "nom": "Haute-Marne"},
    "53": {"lat": 48.1472, "lon": -0.6574, "nom": "Mayenne"},
    "54": {"lat": 48.7882, "lon": 6.1624, "nom": "Meurthe-et-Moselle"},
    "55": {"lat": 48.9914, "lon": 5.3815, "nom": "Meuse"},
    "56": {"lat": 47.8554, "lon": -2.8045, "nom": "Morbihan"},
    "57": {"lat": 49.0375, "lon": 6.6614, "nom": "Moselle"},
    "58": {"lat": 47.1157, "lon": 3.5042, "nom": "Nièvre"},
    "59": {"lat": 50.4488, "lon": 3.2162, "nom": "Nord"},
    "60": {"lat": 49.4099, "lon": 2.4249, "nom": "Oise"},
    "61": {"lat": 48.6231, "lon": 0.1278, "nom": "Orne"},
    "62": {"lat": 50.4926, "lon": 2.2888, "nom": "Pas-de-Calais"},
    "63": {"lat": 45.7259, "lon": 3.1402, "nom": "Puy-de-Dôme"},
    "64": {"lat": 43.2566, "lon": -0.7581, "nom": "Pyrénées-Atlantiques"},
    "65": {"lat": 43.0513, "lon": 0.1664, "nom": "Hautes-Pyrénées"},
    "66": {"lat": 42.5993, "lon": 2.5207, "nom": "Pyrénées-Orientales"},
    "67": {"lat": 48.6715, "lon": 7.5520, "nom": "Bas-Rhin"},
    "68": {"lat": 47.8594, "lon": 7.2740, "nom": "Haut-Rhin"},
    "69": {"lat": 45.8710, "lon": 4.6408, "nom": "Rhône"},
    "70": {"lat": 47.6412, "lon": 6.0872, "nom": "Haute-Saône"},
    "71": {"lat": 46.6448, "lon": 4.5428, "nom": "Saône-et-Loire"},
    "72": {"lat": 47.9949, "lon": 0.2226, "nom": "Sarthe"},
    "73": {"lat": 45.4775, "lon": 6.4429, "nom": "Savoie"},
    "74": {"lat": 46.0346, "lon": 6.4284, "nom": "Haute-Savoie"},
    "75": {"lat": 48.8566, "lon": 2.3428, "nom": "Paris"},
    "76": {"lat": 49.6547, "lon": 1.0272, "nom": "Seine-Maritime"},
    "77": {"lat": 48.6275, "lon": 2.9341, "nom": "Seine-et-Marne"},
    "78": {"lat": 48.8153, "lon": 1.8413, "nom": "Yvelines"},
    "79": {"lat": 46.5570, "lon": -0.3178, "nom": "Deux-Sèvres"},
    "80": {"lat": 49.9579, "lon": 2.2761, "nom": "Somme"},
    "81": {"lat": 43.7857, "lon": 2.1657, "nom": "Tarn"},
    "82": {"lat": 44.0858, "lon": 1.2822, "nom": "Tarn-et-Garonne"},
    "83": {"lat": 43.4438, "lon": 6.2442, "nom": "Var"},
    "84": {"lat": 43.9940, "lon": 5.1852, "nom": "Vaucluse"},
    "85": {"lat": 46.6726, "lon": -1.2877, "nom": "Vendée"},
    "86": {"lat": 46.5649, "lon": 0.4595, "nom": "Vienne"},
    "87": {"lat": 45.8922, "lon": 1.2348, "nom": "Haute-Vienne"},
    "88": {"lat": 48.1962, "lon": 6.3802, "nom": "Vosges"},
    "89": {"lat": 47.8405, "lon": 3.5633, "nom": "Yonne"},
    "90": {"lat": 47.6317, "lon": 6.9286, "nom": "Territoire de Belfort"},
    "91": {"lat": 48.5226, "lon": 2.2434, "nom": "Essonne"},
    "92": {"lat": 48.8475, "lon": 2.2461, "nom": "Hauts-de-Seine"},
    "93": {"lat": 48.9176, "lon": 2.4784, "nom": "Seine-Saint-Denis"},
    "94": {"lat": 48.7774, "lon": 2.4693, "nom": "Val-de-Marne"},
    "95": {"lat": 49.0827, "lon": 2.1310, "nom": "Val-d'Oise"},
}

#: Regiões (18) — centro de massa dos departamentos que as compõem.
FR_REGION_CENTROIDS: Dict[str, Dict[str, Any]] = {

    "01": {"lat": 15.9985, "lon": -61.7294, "nom": "Guadeloupe (Basse-Terre)"},
    "02": {"lat": 14.6161, "lon": -61.0588, "nom": "Martinique (Fort-de-France)"},
    "03": {"lat": 4.9372, "lon": -52.3260, "nom": "Guyane (Cayenne)"},
    "04": {"lat": -20.8823, "lon": 55.4504, "nom": "La Réunion (Saint-Denis)"},
    "06": {"lat": -12.7806, "lon": 45.2278, "nom": "Mayotte (Mamoudzou)"},
    "11": {"lat": 48.7093, "lon": 2.5034, "nom": "Île-de-France"},
    "24": {"lat": 47.4847, "lon": 1.6844, "nom": "Centre-Val de Loire"},
    "27": {"lat": 47.2343, "lon": 4.8071, "nom": "Bourgogne-Franche-Comté"},
    "28": {"lat": 49.1202, "lon": 0.1108, "nom": "Normandie"},
    "32": {"lat": 49.9693, "lon": 2.7715, "nom": "Hauts-de-France"},
    "44": {"lat": 48.6889, "lon": 5.6131, "nom": "Grand Est"},
    "52": {"lat": 47.4793, "lon": -0.8137, "nom": "Pays de la Loire"},
    "53": {"lat": 48.1803, "lon": -2.8394, "nom": "Bretagne"},
    "75": {"lat": 45.2033, "lon": 0.2120, "nom": "Nouvelle-Aquitaine"},
    "76": {"lat": 43.7024, "lon": 2.1453, "nom": "Occitanie"},
    "84": {"lat": 45.5126, "lon": 4.5369, "nom": "Auvergne-Rhône-Alpes"},
    "93": {"lat": 43.9556, "lon": 6.0604, "nom": "Provence-Alpes-Côte d'Azur"},
    "94": {"lat": 42.1517, "lon": 9.1060, "nom": "Corse"},
}

#: Ultramar (DOM/COM) — coordenadas da prefeitura.
FR_OVERSEAS_CENTROIDS: Dict[str, Dict[str, Any]] = {

    "971": {"lat": 15.9985, "lon": -61.7294, "nom": "Guadeloupe (Basse-Terre)"},
    "972": {"lat": 14.6161, "lon": -61.0588, "nom": "Martinique (Fort-de-France)"},
    "973": {"lat": 4.9372, "lon": -52.3260, "nom": "Guyane (Cayenne)"},
    "974": {"lat": -20.8823, "lon": 55.4504, "nom": "La Réunion (Saint-Denis)"},
    "975": {"lat": 46.8852, "lon": -56.3159, "nom": "Saint-Pierre-et-Miquelon"},
    "976": {"lat": -12.7806, "lon": 45.2278, "nom": "Mayotte (Mamoudzou)"},
    "977": {"lat": 17.9000, "lon": -62.8333, "nom": "Saint-Barthélemy"},
    "978": {"lat": 18.0708, "lon": -63.0501, "nom": "Saint-Martin"},
}
