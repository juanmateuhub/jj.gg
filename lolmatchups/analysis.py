"""Análisis estadístico de un matchup combinando datos teóricos y empíricos.

Idea clave (inferencia bayesiana):
  - El modelo teórico da una probabilidad inicial ('prior') de ganar un duelo a cada nivel.
  - Las muertes reales en solitario a ese nivel actualizan esa probabilidad.
  - Con pocos datos manda la teoría; con muchos datos mandan las partidas reales.
Lo mismo se hace con el winrate: se parte del winrate general de ambos campeones y el
matchup concreto lo corrige según su tamaño de muestra.

Filtros disponibles: parches, ligas (mínima y máxima), servidores y, para cada campeón,
hechizos de invocador y runa principal.
"""
import math
import statistics
from collections import Counter, defaultdict

from scipy.stats import beta

from . import config
from .theory import duel

DURATION_BUCKETS = [(0, 25, "<25 min"), (25, 30, "25-30 min"), (30, 35, "30-35 min"), (35, 999, ">35 min")]
LEVEL_BUCKETS = [(1, 3, "Nv 1-3"), (4, 5, "Nv 4-5"), (6, 8, "Nv 6-8"), (9, 11, "Nv 9-11"), (12, 18, "Nv 12+")]
DIFF_MINUTES = tuple(range(1, config.LANE_FRAME_MAX_MINUTE + 1))


def wilson(k, n, z=1.645):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (centre - half, centre + half)


def beta_posterior(successes, failures, prior_p, prior_strength):
    a = prior_p * prior_strength + successes
    b = (1 - prior_p) * prior_strength + failures
    lo = (1 - config.CREDIBLE_LEVEL) / 2
    return {"mean": a / (a + b), "low": beta.ppf(lo, a, b), "high": beta.ppf(1 - lo, a, b)}


def default_patches(conn, n=2):
    rows = [r[0] for r in conn.execute("SELECT DISTINCT patch FROM matches")]
    rows.sort(key=lambda p: tuple(int(x) if x.isdigit() else 0 for x in p.split(".")), reverse=True)
    return rows[:n]


class Filters:
    """Filtros de un análisis. Los de hechizos y runas se aplican a cada campeón por separado."""

    def __init__(self, patches=None, tier_min=None, tier_max=None, platforms=None,
                 spells_a=None, spells_b=None, keystone_a=None, keystone_b=None):
        self.patches, self.platforms = patches, platforms
        self.tier_min, self.tier_max = tier_min, tier_max
        self.spells_a, self.spells_b = spells_a or [], spells_b or []
        self.keystone_a, self.keystone_b = keystone_a, keystone_b

    def describe(self, sd):
        parts = []
        if self.tier_min or self.tier_max:
            parts.append(f"ligas {self.tier_min or 'IRON'}-{self.tier_max or 'CHALLENGER'}")
        if self.platforms:
            parts.append("servidores " + ",".join(self.platforms))
        for side, spells, ks in (("A", self.spells_a, self.keystone_a), ("B", self.spells_b, self.keystone_b)):
            if spells:
                parts.append(f"hechizos {side}: " + "+".join(sd.spell_name(s) for s in spells))
            if ks:
                parts.append(f"runa {side}: {sd.rune_name(ks)}")
        return "; ".join(parts) or "sin filtros adicionales"


def _select_matches(conn, f):
    """Crea la tabla temporal 'sel' con las partidas que cumplen parche, liga y servidor."""
    where, params = ["patch IN (%s)" % ",".join("?" * len(f.patches))], list(f.patches)
    if f.tier_min:
        where.append("tier_score >= ?")
        params.append(config.tier_score(f.tier_min, "IV"))
    if f.tier_max:
        where.append("tier_score <= ?")
        params.append(config.tier_score(f.tier_max, "I") + 0.99)
    if f.platforms:
        where.append("platform IN (%s)" % ",".join("?" * len(f.platforms)))
        params.extend(f.platforms)
    conn.execute("DROP TABLE IF EXISTS temp.sel")
    conn.execute(f"CREATE TEMP TABLE sel AS SELECT match_id FROM matches WHERE {' AND '.join(where)}", params)


def _build_clause(alias, spells, keystone):
    where, params = [], []
    for s in spells:
        where.append(f"({alias}.spell1=? OR {alias}.spell2=?)")
        params += [s, s]
    if keystone:
        where.append(f"{alias}.keystone=?")
        params.append(keystone)
    return where, params


def _select_matchup(conn, a, b, role, f):
    """Tabla temporal 'selmu': partidas del matchup A vs B que cumplen todos los filtros."""
    wa, pa = _build_clause("x", f.spells_a, f.keystone_a)
    wb, pb = _build_clause("y", f.spells_b, f.keystone_b)
    extra = " AND ".join(wa + wb)
    conn.execute("DROP TABLE IF EXISTS temp.selmu")
    conn.execute(
        f"""CREATE TEMP TABLE selmu AS SELECT x.match_id FROM lane_matchups x
            JOIN lane_matchups y ON y.match_id=x.match_id AND y.role=x.role AND y.champ=x.opponent
            WHERE x.champ=? AND x.opponent=? AND x.role=? AND x.match_id IN (SELECT match_id FROM sel)
            {'AND ' + extra if extra else ''}""",
        (a, b, role, *pa, *pb))


def champion_winrate(conn, champ, role):
    """Winrate general del campeón en el rol (con las partidas seleccionadas), suavizado hacia el 50%."""
    r = conn.execute(
        """SELECT COUNT(*) n, COALESCE(SUM(win),0) w FROM lane_matchups
           WHERE champ=? AND role=? AND match_id IN (SELECT match_id FROM sel)""", (champ, role)).fetchone()
    k = config.PRIOR_STRENGTH_WINRATE
    return (r["w"] + 0.5 * k) / (r["n"] + k), r["n"]


def _top(rows, key, n=3):
    groups = defaultdict(list)
    for r in rows:
        v = key(r)
        if v not in (None, "", 0):
            groups[v].append(r["win"])
    ranked = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)[:n]
    total = sum(len(v) for v in groups.values()) or 1
    return [{"value": v, "n": len(w), "pick": len(w) / total, "wr": sum(w) / len(w)} for v, w in ranked]


def builds(sd, rows):
    """Opciones más habituales de un campeón en el matchup (con su frecuencia y winrate)."""
    def names(ids, fn):
        return " + ".join(fn(int(i)) for i in ids)
    top = {
        "Runa principal": _top(rows, lambda r: r["keystone"]),
        "Hechizos": _top(rows, lambda r: (r["spell1"], r["spell2"])),
        "Habilidades Nv 1-3": _top(rows, lambda r: (r["skill_order"] or "")[:3]),
        "Objetos iniciales": _top(rows, lambda r: r["start_items"]),
    }
    for e in top["Runa principal"]:
        e["label"] = sd.rune_name(e["value"])
    for e in top["Hechizos"]:
        e["label"] = names(e["value"], sd.spell_name)
    for e in top["Habilidades Nv 1-3"]:
        e["label"] = "-".join(e["value"])
    for e in top["Objetos iniciales"]:
        e["label"] = names(e["value"].split(","), sd.item_name)
    return top


def matchup_report(conn, sd, champ_a, champ_b, role, patches=None, filters=None):
    a, b = sd.resolve(champ_a), sd.resolve(champ_b)
    role = role.upper()
    f = filters or Filters()
    f.patches = patches or f.patches or default_patches(conn) or ["-"]
    _select_matches(conn, f)
    _select_matchup(conn, a, b, role, f)
    rep = {"champ_a": a, "champ_b": b, "role": role, "patches": f.patches, "filters": f.describe(sd)}

    # ---------- Winrate (con suavizado hacia el winrate general de ambos) ----------
    rows = conn.execute(
        """SELECT mu.*, m.game_duration FROM lane_matchups mu JOIN matches m USING(match_id)
           WHERE mu.champ=? AND mu.role=? AND mu.match_id IN (SELECT match_id FROM selmu)""",
        (a, role)).fetchall()
    rows_b = conn.execute(
        """SELECT * FROM lane_matchups WHERE champ=? AND role=? AND match_id IN (SELECT match_id FROM selmu)""",
        (b, role)).fetchall()
    n = len(rows)
    wins = sum(r["win"] for r in rows)
    wr_a, _ = champion_winrate(conn, a, role)
    wr_b, _ = champion_winrate(conn, b, role)
    prior_wr = min(max(0.5 + (wr_a - 0.5) - (wr_b - 0.5), 0.05), 0.95)
    rep["games"] = n
    rep["reliable"] = n >= config.MIN_GAMES_RELIABLE
    rep["winrate_raw"] = wins / n if n else None
    rep["winrate_raw_ci"] = wilson(wins, n)
    rep["winrate_adjusted"] = beta_posterior(wins, n - wins, prior_wr, config.PRIOR_STRENGTH_WINRATE)
    rep["tiers"] = Counter(r["tier"] for r in conn.execute(
        "SELECT tier FROM matches WHERE match_id IN (SELECT match_id FROM selmu)"))

    # ---------- Carrera de niveles ----------
    def rate(col):
        vals = [r[col] for r in rows if r[col] is not None]
        return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)
    rep["first_to"] = {lvl: rate(f"first_to_{lvl}") for lvl in (2, 3, 6)}

    # ---------- Duelos por nivel: teoría + muertes reales ----------
    kills = conn.execute(
        """SELECT * FROM lane_kills WHERE role=? AND match_id IN (SELECT match_id FROM selmu)
           AND ((killer=? AND victim=?) OR (killer=? AND victim=?))""", (role, a, b, b, a)).fetchall()
    levels = []
    for lvl, lo, hi in config.KEY_LEVELS:
        th = duel(sd, a, b, lvl)
        # Duelos igualados: muertes en solitario con ambos al mismo nivel, dentro del rango del nivel clave
        even = [k for k in kills if k["solo"] and k["killer_level"] == k["victim_level"] and lo <= k["killer_level"] <= hi]
        ka = sum(1 for k in even if k["killer"] == a)
        kb = len(even) - ka
        strength = config.PRIOR_STRENGTH_THEORY if lvl < 9 else config.PRIOR_STRENGTH_THEORY_LATE
        levels.append({"level": lvl, "range": [lo, hi], "theory": th, "solo_kills_a": ka, "solo_kills_b": kb,
                       "combined": beta_posterior(ka, kb, th["p_a"], strength)})
    rep["levels"] = levels

    # ---------- Diferencias de oro / experiencia / súbditos ----------
    frames = conn.execute(
        """SELECT minute, gold_diff, xp_diff, cs_diff FROM lane_frames
           WHERE champ=? AND role=? AND match_id IN (SELECT match_id FROM selmu)""", (a, role)).fetchall()
    diffs = {}
    for minute in DIFF_MINUTES:
        sub = [fr for fr in frames if fr["minute"] == minute]
        if len(sub) >= 2:
            g = [fr["gold_diff"] for fr in sub]
            diffs[minute] = {"gold": statistics.mean(g), "gold_ci": 1.96 * statistics.stdev(g) / math.sqrt(len(g)),
                             "xp": statistics.mean(fr["xp_diff"] for fr in sub),
                             "cs": statistics.mean(fr["cs_diff"] for fr in sub), "n": len(g)}
    rep["diffs"] = diffs

    # ---------- Fase de líneas: emboscadas y placas ----------
    deaths = conn.execute(
        """SELECT champ, enemy_jungler_involved, timestamp FROM lane_deaths
           WHERE role=? AND champ IN (?, ?) AND timestamp <= ? AND match_id IN (SELECT match_id FROM selmu)""",
        (role, a, b, config.EARLY_WINDOW_MS)).fetchall()
    rep["ganks"] = {c: (sum(1 for d in deaths if d["champ"] == c and d["enemy_jungler_involved"]) / n if n else None)
                    for c in (a, b)}
    # Muertes entre los dos rivales antes del minuto 14: kills en solitario y lane kill rate
    # (porcentaje de partidas en las que consigue al menos una muerte sobre su rival de calle)
    early = [k for k in kills if k["timestamp"] <= config.EARLY_WINDOW_MS]
    rep["lane"] = {}
    for c in (a, b):
        mine = [k for k in early if k["killer"] == c]
        rep["lane"][c] = {
            "kills_pg": len(mine) / n if n else None,
            "solo_kills_pg": sum(1 for k in mine if k["solo"]) / n if n else None,
            "assisted_kills_pg": sum(1 for k in mine if not k["solo"]) / n if n else None,
            "lane_kill_rate": len({k["match_id"] for k in mine}) / n if n else None,
            "solo_kill_rate": len({k["match_id"] for k in mine if k["solo"]}) / n if n else None,
        }
    plates = lambda rs: [r["plates_taken"] for r in rs if r["plates_taken"] is not None]
    rep["plates"] = {a: statistics.mean(plates(rows)) if plates(rows) else None,
                     b: statistics.mean(plates(rows_b)) if plates(rows_b) else None}

    # ---------- Power spikes ----------
    by_duration = []
    for lo, hi, label in DURATION_BUCKETS:
        sub = [r for r in rows if lo * 60 <= r["game_duration"] < hi * 60]
        w = sum(r["win"] for r in sub)
        by_duration.append({"label": label, "n": len(sub), "wr": w / len(sub) if sub else None,
                            "ci": wilson(w, len(sub))})
    rep["winrate_by_duration"] = by_duration
    rep["kill_share_total"] = (sum(1 for k in kills if k["killer"] == a) / len(kills)) if kills else None
    by_level = []
    for lo, hi, label in LEVEL_BUCKETS:
        sub = [k for k in kills if lo <= k["killer_level"] <= hi]
        ka = sum(1 for k in sub if k["killer"] == a)
        by_level.append({"label": label, "n": len(sub), "share_a": ka / len(sub) if sub else None,
                         "ci": wilson(ka, len(sub))})
    rep["kill_share_by_level"] = by_level

    def share(fn):
        sub = [k for k in kills if fn(k)]
        return (sum(1 for k in sub if k["killer"] == a) / len(sub), len(sub)) if sub else (None, 0)
    only = lambda c: lambda k: ((k["killer"] == c and k["killer_has_item"] and not k["victim_has_item"])
                                or (k["victim"] == c and k["victim_has_item"] and not k["killer_has_item"]))
    rep["item_spike"] = {"sin_objetos": share(lambda k: not k["killer_has_item"] and not k["victim_has_item"]),
                         "solo_a_con_objeto": share(only(a)), "solo_b_con_objeto": share(only(b))}
    item_t = lambda rs: [r["first_legendary_time"] / 60000 for r in rs if r["first_legendary_time"]]
    rep["first_item_minute"] = {a: statistics.median(item_t(rows)) if item_t(rows) else None,
                                b: statistics.median(item_t(rows_b)) if item_t(rows_b) else None}

    # ---------- Configuraciones más habituales ----------
    rep["builds"] = {a: builds(sd, rows), b: builds(sd, rows_b)}
    rep["spikes"] = detect_spikes(rep)
    return rep


def detect_spikes(rep, min_n=15, threshold=0.08):
    """Etiqueta fases donde A es claramente más fuerte (o más débil) que su media en el matchup."""
    notes = []
    base = rep["kill_share_total"]
    if base is not None:
        for bucket in rep["kill_share_by_level"]:
            if bucket["n"] >= min_n and bucket["share_a"] is not None:
                delta = bucket["share_a"] - base
                if delta >= threshold:
                    notes.append(f"{rep['champ_a']} rinde más en {bucket['label']} (+{delta:.0%} de cuota de muertes)")
                elif delta <= -threshold:
                    notes.append(f"{rep['champ_b']} rinde más en {bucket['label']} ({delta:.0%} para {rep['champ_a']})")
    valid = [d for d in rep["winrate_by_duration"] if d["n"] >= min_n]
    if len(valid) >= 2:
        first, last = valid[0], valid[-1]
        if first["wr"] - last["wr"] >= threshold:
            notes.append(f"{rep['champ_a']} pierde fuerza con la duración: campeón de early en este matchup")
        elif last["wr"] - first["wr"] >= threshold:
            notes.append(f"{rep['champ_a']} gana fuerza con la duración: escala mejor en este matchup")
    for L in rep["levels"]:
        n = L["solo_kills_a"] + L["solo_kills_b"]
        p = L["combined"]["mean"]
        if n >= min_n and abs(p - 0.5) >= 0.15:
            who = rep["champ_a"] if p > 0.5 else rep["champ_b"]
            notes.append(f"{who} domina los duelos igualados a nivel {L['level']} ({max(p, 1 - p):.0%}, {n} duelos reales)")
    return notes
