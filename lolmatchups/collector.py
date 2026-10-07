"""Recolector de partidas por ligas: jugadores de cada liga -> sus partidas -> partida + timeline.

Cada partida válida se guarda completa y comprimida en data/raw/ y sus datos extraídos en la BD.
La recogida se reparte por igual entre las ligas pedidas para que todas tengan muestra.
"""
import math
import time

from . import config, db, raw_store
from .parser import parse_match, patch_of


def seed_tier(client, conn, tier, page=1):
    """Añade a la cola jugadores de una liga (todas sus divisiones)."""
    added = 0
    if tier in config.APEX_TIERS:
        chunks = [(None, (client.apex_league(tier) or {}).get("entries", []))] if page == 1 else []
    else:
        chunks = [(div, client.league_entries(tier, div, page)) for div in config.DIVISIONS]
    for division, entries in chunks:
        for e in entries:
            puuid = e.get("puuid")
            if not puuid and e.get("summonerId"):
                puuid = (client.summoner_by_id(e["summonerId"]) or {}).get("puuid")
            if puuid:
                cur = conn.execute("INSERT OR IGNORE INTO players VALUES (?, ?, ?, ?, NULL)",
                                   (puuid, client.platform, tier, division or e.get("rank")))
                added += cur.rowcount
    conn.commit()
    return added


def _next_player(conn, platform, tier, max_age_hours=24):
    """Jugador de la liga que lleva más tiempo sin revisarse (o nunca revisado)."""
    return conn.execute(
        """SELECT puuid, tier, division FROM players WHERE platform=? AND tier=?
           AND (last_crawled IS NULL OR last_crawled < ?)
           ORDER BY last_crawled IS NOT NULL, last_crawled LIMIT 1""",
        (platform, tier, time.time() - max_age_hours * 3600)).fetchone()


def _rank_of(client, conn, puuid):
    row = conn.execute("SELECT tier, division, fetched_at FROM rank_cache WHERE puuid=?", (puuid,)).fetchone()
    if row and time.time() - row["fetched_at"] < config.RANK_CACHE_DAYS * 86400:
        return (row["tier"], row["division"]) if row["tier"] else None
    rank = client.rank_by_puuid(puuid)
    conn.execute("INSERT OR REPLACE INTO rank_cache VALUES (?, ?, ?, ?, ?)",
                 (puuid, client.platform, rank[0] if rank else None, rank[1] if rank else None, time.time()))
    return rank


def match_rank(client, conn, match, seed_tier_name, seed_division, precise):
    """Liga de la partida: la del jugador semilla o, en modo preciso, la media de los 10 jugadores."""
    seed = {"tier": seed_tier_name, "division": None if seed_tier_name in config.APEX_TIERS else seed_division,
            "tier_score": config.tier_score(seed_tier_name, seed_division), "rank_source": "semilla"}
    if not precise:
        return seed
    scores = []
    for puuid in match["metadata"].get("participants", []):
        rank = _rank_of(client, conn, puuid)
        if rank:
            score = config.tier_score(*rank)
            if score is not None:
                scores.append(score)
    if len(scores) < 5:
        return seed
    avg = sum(scores) / len(scores)
    tier, division = config.tier_from_score(avg)
    return {"tier": tier, "division": division, "tier_score": round(avg, 2), "rank_source": f"media_{len(scores)}"}


def process_match(client, conn, static, match_id, seed_row, patches, precise, legendary, raw_dir=None):
    """Descarga, guarda y analiza una partida. Devuelve (guardada, motivo)."""
    if db.match_known(conn, match_id):
        return False, "ya_conocida"
    match = client.match(match_id)
    if not match:
        return False, "no_disponible"
    if match["info"].get("queueId") not in (None, config.QUEUE_ID):
        db.save_skipped(conn, match_id, "otra_cola")
        return False, "otra_cola"
    if patches and patch_of(match["info"]["gameVersion"]) not in patches:
        db.save_skipped(conn, match_id, "otro_parche")
        return False, "otro_parche"
    timeline = client.timeline(match_id)
    if not timeline:
        return False, "no_disponible"
    meta = {"platform": client.platform,
            **match_rank(client, conn, match, seed_row["tier"], seed_row["division"], precise)}
    if meta["tier_score"] is not None and meta["tier_score"] < config.tier_score(config.MIN_TIER, "IV"):
        db.save_skipped(conn, match_id, "liga_baja")  # p. ej. media real de los 10 jugadores por debajo de ORO
        return False, "liga_baja"
    parsed, reason = parse_match(match, timeline, legendary, meta)
    if parsed is None:
        db.save_skipped(conn, match_id, reason)
        return False, reason
    raw_store.save(client.platform, match_id, match, timeline, meta, raw_dir)
    db.save_parsed(conn, parsed)
    return True, "guardada"


def _patch_start_time(conn, platform, patches, margin_days=0.25):
    """Inicio aproximado del parche: la partida más antigua ya guardada de ese parche, menos un margen
    de 6 horas.

    Así no se piden a Riot partidas anteriores al parche, que se descargarían para luego descartarlas.
    """
    if not patches:
        return None
    row = conn.execute(
        f"SELECT MIN(game_creation) FROM matches WHERE platform=? AND patch IN ({','.join('?' * len(patches))})",
        (platform, *patches)).fetchone()
    return row[0] / 1000 - margin_days * 86400 if row and row[0] else None


def crawl(client, conn, static, max_matches=500, tiers=None, patches=None, precise_rank=False,
          matches_per_player=20, raw_dir=None, max_days=None, balance=True, stop_event=None, label=""):
    """Recoge partidas de un servidor.

    max_days: solo se piden partidas de los últimos N días. Con filtro de parche, además, el límite se
              ajusta solo al inicio del parche en cuanto se guarda la primera partida.
    balance:  reparte las partidas por igual entre ligas; sin reparto, cada liga aporta lo que encuentre.
    stop_event: permite detener la recogida desde otro hilo (varios servidores a la vez).
    """
    base_start = time.time() - max_days * 86400 if max_days else None
    tiers = [t.upper() for t in (tiers or config.DEFAULT_CRAWL_TIERS)]
    for t in tiers:
        if t not in config.TIERS:
            raise ValueError(f"Liga desconocida: {t}. Opciones: {', '.join(config.TIERS)}")
        if config.TIERS.index(t) < config.TIERS.index(config.MIN_TIER):
            raise ValueError(f"La liga {t} está por debajo de la mínima configurada ({config.MIN_TIER}). "
                             "Puedes cambiarla en MIN_TIER, dentro de lolmatchups/config.py.")
    prefix = f"[{label}] " if label else ""
    legendary = static.legendary_item_ids()
    target = math.ceil(max_matches / len(tiers)) if balance else max_matches
    counts = {t: 0 for t in tiers}
    reasons = {}
    pages = {t: 1 for t in tiers}
    active = list(tiers)
    start = time.time()
    stopped = lambda: stop_event is not None and stop_event.is_set()

    for t in tiers:
        if stopped():
            return counts
        if _next_player(conn, client.platform, t) is None:
            print(f"{prefix}Obteniendo jugadores de {t}...")
            seed_tier(client, conn, t)

    while active and sum(counts.values()) < max_matches and not stopped():
        patch_start = _patch_start_time(conn, client.platform, patches)
        start_time = max(filter(None, (base_start, patch_start)), default=None)
        for tier in list(active):
            if stopped():
                break
            if counts[tier] >= target:
                active.remove(tier)
                continue
            player = _next_player(conn, client.platform, tier)
            if player is None:
                pages[tier] += 1
                if tier in config.APEX_TIERS or seed_tier(client, conn, tier, pages[tier]) == 0:
                    print(f"{prefix}{tier}: no quedan jugadores nuevos por revisar hoy.")
                    active.remove(tier)
                continue
            conn.execute("UPDATE players SET last_crawled=? WHERE puuid=?", (time.time(), player["puuid"]))
            conn.commit()
            for match_id in client.match_ids(player["puuid"], count=matches_per_player, start_time=start_time):
                if counts[tier] >= target or sum(counts.values()) >= max_matches or stopped():
                    break
                saved, reason = process_match(client, conn, static, match_id, player, patches, precise_rank,
                                              legendary, raw_dir)
                reasons[reason] = reasons.get(reason, 0) + 1
                if saved:
                    counts[tier] += 1
                    total = sum(counts.values())
                    if total % 10 == 0:
                        elapsed = max(time.time() - start, 1)
                        rate = total / elapsed * 3600
                        per_match = client.requests_made / total
                        detail = ", ".join(f"{k}: {v}" for k, v in counts.items() if v)
                        print(f"{prefix}{total}/{max_matches} partidas (~{rate:.0f}/hora, "
                              f"{per_match:.1f} peticiones por partida) | {detail}")
    skipped = {k: v for k, v in reasons.items() if k not in ("guardada", "ya_conocida")}
    if skipped:
        print(f"{prefix}Descartadas: " + ", ".join(f"{k} {v}" for k, v in sorted(skipped.items())))
    return counts


def crawl_many(platforms, static, max_matches, **kwargs):
    """Recoge en varios servidores a la vez, uno por región de enrutado.

    Los límites de la Riot API se aplican por región (europe, americas, asia, sea), así que cada
    servidor de una región distinta tiene su propio cupo de peticiones y la velocidad se suma.
    """
    import threading

    from .riot_client import RiotClient

    regions = {}
    for p in platforms:
        region = config.PLATFORM_TO_REGION.get(p.lower())
        if region is None:
            raise ValueError(f"Servidor desconocido: {p}. Opciones: {', '.join(config.PLATFORM_TO_REGION)}")
        if region in regions:
            raise ValueError(f"{p} y {regions[region]} comparten la región '{region}' y su límite de peticiones: "
                             "usa un solo servidor por región (por ejemplo euw1, na1, kr y oc1).")
        regions[region] = p.lower()
    per_platform = math.ceil(max_matches / len(platforms))
    stop = threading.Event()
    results, errors = {}, {}

    def worker(platform):
        conn = db.connect()
        try:
            results[platform] = crawl(RiotClient(platform=platform), conn, static, per_platform,
                                      stop_event=stop, label=platform, **kwargs)
        except Exception as e:  # clave caducada, error de red persistente...
            errors[platform] = e
            stop.set()
        finally:
            conn.close()

    threads = [threading.Thread(target=worker, args=(p,), daemon=True) for p in regions.values()]
    for t in threads:
        t.start()
    try:
        while any(t.is_alive() for t in threads):
            for t in threads:
                t.join(timeout=0.5)
    except KeyboardInterrupt:
        print("\nDeteniendo la recogida (las partidas ya guardadas se conservan)...")
        stop.set()
        for t in threads:
            t.join(timeout=30)
    for platform, e in errors.items():
        print(f"[{platform}] Error: {e}")
    return results
