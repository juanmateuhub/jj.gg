"""Configuración central del proyecto. Los valores sensibles se leen del fichero .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# --- Riot API ---
RIOT_API_KEY = os.getenv("RIOT_API_KEY", "").strip()
PLATFORM = os.getenv("PLATFORM", "euw1").lower()   # servidor (EUW para España)
QUEUE_ID = 420                                      # Clasificatoria Solo/Dúo

# Enrutado regional de Match-v5 para cada servidor
PLATFORM_TO_REGION = {
    "euw1": "europe", "eun1": "europe", "tr1": "europe", "ru": "europe", "me1": "europe",
    "na1": "americas", "br1": "americas", "la1": "americas", "la2": "americas",
    "kr": "asia", "jp1": "asia",
    "oc1": "sea", "sg2": "sea", "tw2": "sea", "vn2": "sea",
}
REGION = os.getenv("REGION", PLATFORM_TO_REGION.get(PLATFORM, "europe"))

# --- Ligas ---
TIERS = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER"]
APEX_TIERS = ["MASTER", "GRANDMASTER", "CHALLENGER"]
DIVISIONS = ["IV", "III", "II", "I"]
MIN_TIER = "GOLD"              # liga mínima: no se recogen ni guardan partidas por debajo de ORO IV
DEFAULT_CRAWL_TIERS = ["GOLD", "PLATINUM", "EMERALD", "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER"]
RANK_CACHE_DAYS = 7            # días que se reutiliza la liga consultada de un jugador

# Límites de la clave de desarrollo: 20 peticiones/1 s y 100 peticiones/120 s.
# Si obtienes una clave personal o de producción, ajústalos aquí.
RATE_LIMITS = [(20, 1.0), (100, 120.0)]

# --- Almacenamiento ---
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
RAW_DIR = DATA_DIR / "raw"     # partidas completas comprimidas (data/raw/<servidor>/<id>.json.gz)
DB_PATH = Path(os.getenv("DB_PATH", DATA_DIR / "lol.db"))
SCHEMA_VERSION = 2

# --- Filtros de calidad de datos ---
MIN_GAME_DURATION = 300        # segundos; descarta remakes
LANE_FRAME_MAX_MINUTE = 30     # minutos de la timeline que se guardan (requiere 'rebuild' si se cambia)
START_ITEMS_WINDOW_MS = 90_000 # compras antes de este instante = objetos iniciales
EARLY_WINDOW_MS = 14 * 60_000  # ventana de la fase de líneas (emboscadas y placas)
DEATHS_WINDOW_MS = 20 * 60_000 # muertes de los jugadores de calle que se registran

# --- Parámetros estadísticos ---
PRIOR_STRENGTH_THEORY = 5      # peso (en "combates equivalentes") del modelo teórico
PRIOR_STRENGTH_THEORY_LATE = 2 # desde nivel 9 la teoría pesa menos: no incluye objetos

# Niveles clave del análisis de duelos y rango de niveles igualados que cuenta cada uno
# (nivel mostrado, primer nivel del tramo, último nivel del tramo)
KEY_LEVELS = [(1, 1, 2), (3, 3, 5), (6, 6, 8), (9, 9, 11), (12, 12, 14), (15, 15, 17), (18, 18, 18)]
PRIOR_STRENGTH_WINRATE = 20    # peso (en "partidas equivalentes") del winrate general del campeón
MIN_GAMES_RELIABLE = 30        # por debajo de esto el matchup se marca como poco fiable
CREDIBLE_LEVEL = 0.90          # nivel de los intervalos de credibilidad

# Equipo inicial aproximado (objeto inicial + runas) según el tipo de daño del campeón
STARTER = {
    "PHYSICAL_DAMAGE": {"ad": 19, "ap": 0, "hp": 80},   # objeto inicial de AD + runas adaptativas
    "MAGIC_DAMAGE": {"ad": 0, "ap": 33, "hp": 70},      # objeto inicial de AP + runas adaptativas
}

# Correcciones manuales de habilidades (tienen prioridad sobre la lectura automática de Meraki):
#   hits      -> número de golpes de una habilidad de varios impactos
#   cooldown  -> tiempo real entre usos en un duelo (habilidades con cargas o enfriamiento por objetivo)
#   attribute -> atributo de daño de Meraki que se debe usar
#   duration  -> segundos en los que se reparte el daño (se detecta automáticamente)
#   attack_lock -> segundos sin poder atacar al usarla (se detecta automáticamente; 0 para anularlo)
# Genera la lista de casos a revisar con:  python audit_abilities.py
ABILITY_OVERRIDES = {
    "Aatrox": {"Q": {"hits": 3}},                    # 3 lanzamientos (se usa el daño del primero: conservador)
    "Akshan": {"E": {"hits": 9}},                    # dispara cada 0,231 s durante ~2,1 s de balanceo
    "Amumu": {"W": {"hits": 2}},                     # activable: golpe cada 0,5 s (enfriamiento de 1 s)
    "Anivia": {"R": {"hits": 8}},                    # activable: golpe cada 0,5 s (enfriamiento de 4 s)
    "AurelionSol": {"Q": {"cooldown": 6.25}},        # canaliza hasta 3,25 s antes del enfriamiento de 3 s
    "Azir": {"W": {"cooldown": 5.0}},                # cargas de soldados
    "Belveth": {"Q": {"cooldown": 4.0}},             # enfriamiento independiente por dirección
    "Corki": {"R": {"cooldown": 8.0}},               # misiles con cargas
    "Gangplank": {"E": {"cooldown": 18.0}},          # barriles con cargas
    "Garen": {"E": {"hits": 7}},                     # 7 giros en 3 s
    "Jhin": {"E": {"cooldown": 14.0},                # 2 cargas cada 28 s
             "R": {"attribute": "Minimum Physical Damage per Bullet", "hits": 4, "duration": 3.0}},
    "Karthus": {"E": {"hits": 2}},                   # activable: golpe cada 0,25 s (enfriamiento de 0,5 s)
    "KogMaw": {"R": {"cooldown": 4.0}},              # el coste de maná creciente limita su uso
    "Nilah": {"E": {"cooldown": 13.0}},              # 2 cargas cada 26 s
    "Renekton": {"R": {"duration": 15.0}},           # daño repartido durante 15 s
    "Rumble": {"E": {"cooldown": 12.0}},             # daño total de los 2 arpones
    "Samira": {"R": {"cooldown": 20.0}},             # requiere el rango S de estilo
    "Sejuani": {"E": {"cooldown": 10.0}},            # requiere acumular escarcha
    "Shaco": {"W": {"hits": 10}},                    # la caja dispara cada 0,5 s durante 5 s
    "Singed": {"Q": {"cooldown": 3.25}},             # el rastro de veneno no se acumula consigo mismo
    "Swain": {"R": {"hits": 16, "duration": 8.0}},   # drenaje cada 0,5 s (se asumen 8 s)
    "Teemo": {"R": {"cooldown": 30.0}},              # setas con cargas
    "Urgot": {"W": {"attack_lock": 0.0}},            # su W sustituye a los ataques básicos
    "Velkoz": {"W": {"cooldown": 9.0}},              # 2 cargas
    "Vi": {"E": {"cooldown": 7.0}},                  # 2 cargas
    "Yasuo": {"E": {"attribute": "Physical Damage", "cooldown": 10.0}},  # enfriamiento por objetivo
    "Zoe": {"W": {"cooldown": 30.0}},                # depende de hechizos de invocador recogidos
}


def tier_score(tier, division=None):
    """Convierte una liga en un número ordenable: HIERRO IV = 0 ... CHALLENGER = 36."""
    tier = (tier or "").upper()
    if tier not in TIERS:
        return None
    base = TIERS.index(tier) * 4
    if tier in APEX_TIERS or not division:
        return float(base)
    return float(base + DIVISIONS.index(division.upper()))


def tier_from_score(score):
    """Liga correspondiente a una puntuación media (p. ej. 17.4 -> PLATINUM II)."""
    idx = min(int(score // 4), len(TIERS) - 1)
    tier = TIERS[idx]
    if tier in APEX_TIERS:
        return tier, None
    return tier, DIVISIONS[min(int(round(score - idx * 4)), 3)]
