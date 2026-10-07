"""Base de datos SQLite (datos extraídos de las partidas).

Las tablas de análisis se pueden regenerar en cualquier momento a partir de las partidas completas
guardadas en data/raw/ con:  python main.py rebuild
Cada matchup se guarda desde las dos perspectivas (A vs B y B vs A).
"""
import sqlite3

from . import config

# Tablas derivadas de las partidas (se borran y regeneran con 'rebuild')
DERIVED_SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY, platform TEXT, patch TEXT, game_duration INTEGER, game_creation INTEGER,
    tier TEXT, division TEXT, tier_score REAL, rank_source TEXT
);
CREATE TABLE IF NOT EXISTS lane_matchups (
    match_id TEXT, role TEXT, champ TEXT, opponent TEXT, win INTEGER,
    first_to_2 INTEGER, first_to_3 INTEGER, first_to_6 INTEGER, first_legendary_time INTEGER,
    spell1 INTEGER, spell2 INTEGER, keystone INTEGER, primary_style INTEGER, secondary_style INTEGER,
    skill_order TEXT, start_items TEXT, plates_taken INTEGER, plates_lost INTEGER,
    PRIMARY KEY (match_id, role, champ)
);
CREATE TABLE IF NOT EXISTS lane_frames (
    match_id TEXT, role TEXT, champ TEXT, minute INTEGER,
    gold_diff INTEGER, xp_diff INTEGER, cs_diff INTEGER,
    PRIMARY KEY (match_id, role, champ, minute)
);
CREATE TABLE IF NOT EXISTS lane_kills (
    match_id TEXT, role TEXT, killer TEXT, victim TEXT, timestamp INTEGER,
    killer_level INTEGER, victim_level INTEGER, solo INTEGER,
    killer_has_item INTEGER, victim_has_item INTEGER
);
CREATE TABLE IF NOT EXISTS lane_deaths (
    match_id TEXT, role TEXT, champ TEXT, opponent TEXT, timestamp INTEGER, level INTEGER,
    killer_role TEXT, enemy_jungler_involved INTEGER, lane_opponent_involved INTEGER, solo INTEGER,
    x INTEGER, y INTEGER
);
CREATE INDEX IF NOT EXISTS ix_m ON matches(patch, tier_score);
CREATE INDEX IF NOT EXISTS ix_mu ON lane_matchups(champ, opponent, role);
CREATE INDEX IF NOT EXISTS ix_fr ON lane_frames(champ, role);
CREATE INDEX IF NOT EXISTS ix_k ON lane_kills(killer, victim, role);
CREATE INDEX IF NOT EXISTS ix_d ON lane_deaths(champ, role);
"""

# Tablas de funcionamiento del recolector (no se tocan en 'rebuild')
STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS skipped_matches (match_id TEXT PRIMARY KEY, reason TEXT);
CREATE TABLE IF NOT EXISTS players (
    puuid TEXT PRIMARY KEY, platform TEXT, tier TEXT, division TEXT, last_crawled REAL
);
CREATE TABLE IF NOT EXISTS rank_cache (
    puuid TEXT PRIMARY KEY, platform TEXT, tier TEXT, division TEXT, fetched_at REAL
);
CREATE INDEX IF NOT EXISTS ix_p ON players(platform, tier, last_crawled);
"""

DERIVED_TABLES = ("matches", "lane_matchups", "lane_frames", "lane_kills", "lane_deaths")


class OldDatabaseError(RuntimeError):
    pass


def connect(path=None):
    path = path or config.DB_PATH
    if str(path) != ":memory:":
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60)  # espera si otro proceso o hilo está escribiendo
    conn.row_factory = sqlite3.Row
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "matches" in tables and "meta" not in tables:
        conn.close()
        raise OldDatabaseError(
            "La base de datos es de una versión anterior y le faltan datos (hechizos, runas, ligas...).\n"
            f"Borra el fichero {config.DB_PATH} y vuelve a recoger partidas."
        )
    conn.executescript(STATE_SCHEMA + DERIVED_SCHEMA)
    conn.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(config.SCHEMA_VERSION),))
    conn.commit()
    return conn


def reset_derived(conn):
    with conn:
        for t in DERIVED_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {t}")
    conn.executescript(DERIVED_SCHEMA)


def match_known(conn, match_id):
    return conn.execute(
        "SELECT 1 FROM matches WHERE match_id=? UNION SELECT 1 FROM skipped_matches WHERE match_id=?",
        (match_id, match_id)).fetchone() is not None


def save_skipped(conn, match_id, reason):
    conn.execute("INSERT OR IGNORE INTO skipped_matches VALUES (?, ?)", (match_id, reason))
    conn.commit()


def _insert(conn, table, rows):
    if not rows:
        return
    cols = list(rows[0])
    conn.executemany(f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                     [tuple(r[c] for c in cols) for r in rows])


def save_parsed(conn, parsed, commit=True):
    _insert(conn, "matches", [parsed["match"]])
    _insert(conn, "lane_matchups", parsed["matchups"])
    _insert(conn, "lane_frames", parsed["frames"])
    _insert(conn, "lane_kills", parsed["kills"])
    _insert(conn, "lane_deaths", parsed["deaths"])
    if commit:
        conn.commit()
