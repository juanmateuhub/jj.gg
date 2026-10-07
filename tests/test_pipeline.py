"""Pruebas con datos sintéticos (no necesitan clave de API ni conexión).  Ejecutar: pytest -q"""
import json
import random

import pytest

from lolmatchups import config, db, raw_store
from lolmatchups.analysis import Filters, matchup_report
from lolmatchups.parser import parse_match
from lolmatchups.static_data import StaticData, stat_at_level

CHAMPS = ["Darius", "Garen", "LeeSin", "Ahri", "Zed", "Jinx", "Caitlyn", "Thresh", "Lulu", "Vi"]
IGNITE, TELEPORT, FLASH, SMITE = 14, 12, 4, 11
CONQUEROR, GRASP = 8010, 8437


def _stats(hp=650, ad=64):
    return {"hp": hp, "hpperlevel": 110, "armor": 36, "armorperlevel": 5, "spellblock": 32,
            "spellblockperlevel": 2.05, "attackdamage": ad, "attackdamageperlevel": 3.5,
            "attackspeed": 0.625, "attackspeedperlevel": 3, "attackrange": 175}


def _ability(flat, ratio, cd, dtype="PHYSICAL_DAMAGE"):
    return [{"effects": [{"leveling": [{"attribute": "Physical Damage", "modifiers": [
        {"values": flat, "units": [""] * 5}, {"values": ratio, "units": ["% AD"] * 5}]}]}],
        "cooldown": {"modifiers": [{"values": cd}]}, "damageType": dtype}]


@pytest.fixture
def static(tmp_path):
    champs = {c: {"name": c, "stats": _stats(ad=70 if c == "Darius" else 64)} for c in CHAMPS}
    meraki = {c: {"abilities": {k: _ability([40, 60, 80, 100, 120], [100] * 5, [8, 7, 6, 5, 4])
                                for k in "QWER"}} for c in CHAMPS}
    (tmp_path / "championFull.json").write_text(json.dumps({"data": champs}))
    items = {"3071": {"name": "Cleaver", "gold": {"total": 3000, "purchasable": True}, "maps": {"11": True}},
             "1055": {"name": "Doran's Blade", "gold": {"total": 450, "purchasable": True}, "maps": {"11": True}},
             "2003": {"name": "Health Potion", "gold": {"total": 50, "purchasable": True}, "maps": {"11": True}}}
    (tmp_path / "item.json").write_text(json.dumps({"data": items}))
    es_items = {k: {**v, "name": {"3071": "Cuchilla", "1055": "Filo de Doran", "2003": "Poción de vida"}[k]}
                for k, v in items.items()}
    (tmp_path / "item_es_ES.json").write_text(json.dumps({"data": es_items}))
    (tmp_path / "meraki_champions.json").write_text(json.dumps(meraki))
    for lang, names in (("en_US", ("Ignite", "Teleport", "Flash", "Smite", "Conqueror", "Grasp of the Undying")),
                        ("es_ES", ("Prender", "Teleportar", "Destello", "Aplastar", "Conquistador",
                                   "Garras del Inmortal"))):
        spells = {f"Summoner{k}": {"id": f"Summoner{k}", "key": str(sid), "name": n}
                  for k, sid, n in (("Dot", IGNITE, names[0]), ("Teleport", TELEPORT, names[1]),
                                    ("Flash", FLASH, names[2]), ("Smite", SMITE, names[3]))}
        (tmp_path / f"summoner_{lang}.json").write_text(json.dumps({"data": spells}))
        runes = [{"id": 8000, "key": "Precision", "name": "Precision", "slots": [
                     {"runes": [{"id": CONQUEROR, "key": "Conqueror", "name": names[4]}]}]},
                 {"id": 8400, "key": "Resolve", "name": "Resolve", "slots": [
                     {"runes": [{"id": GRASP, "key": "GraspOfTheUndying", "name": names[5]}]}]}]
        (tmp_path / f"runes_{lang}.json").write_text(json.dumps(runes))
    return StaticData(tmp_path)


def fake_game(i, rng, darius_bias=0.6):
    roles = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
    blue_wins = rng.random() < darius_bias
    darius_ignite = i % 2 == 0
    names = CHAMPS[:5] + ["Garen", "Vi", "Ahri", "Jinx", "Thresh"]
    parts = []
    for pid in range(1, 11):
        spells = (FLASH, IGNITE if (pid == 1 and darius_ignite) else SMITE if pid in (2, 7) else TELEPORT)
        keystone = CONQUEROR if pid == 1 else GRASP
        parts.append({"participantId": pid, "teamId": 100 if pid <= 5 else 200,
                      "teamPosition": roles[(pid - 1) % 5], "championName": names[pid - 1],
                      "win": blue_wins if pid <= 5 else not blue_wins,
                      "summoner1Id": spells[0], "summoner2Id": spells[1],
                      "perks": {"styles": [{"style": 8000 if keystone == CONQUEROR else 8400,
                                            "selections": [{"perk": keystone}]}, {"style": 8100}]}})
    frames, events = [], []
    for m in range(0, 26):
        pf = {str(p): {"totalGold": 500 + m * 400 + (40 * m if p == 1 else 0), "xp": m * 500,
                       "minionsKilled": m * 7, "jungleMinionsKilled": 0} for p in range(1, 11)}
        frames.append({"participantFrames": pf, "events": []})
    for p in range(1, 11):
        for lvl, t in [(2, 90_000 if p == 1 else 95_000), (3, 180_000 if p == 1 else 185_000),
                       (6, 480_000), (9, 800_000)]:
            events.append({"type": "LEVEL_UP", "participantId": p, "level": lvl, "timestamp": t})
        for n, slot in enumerate((1, 2, 3)):
            events.append({"type": "SKILL_LEVEL_UP", "participantId": p, "skillSlot": slot,
                           "levelUpType": "NORMAL", "timestamp": 1000 + n * 90_000})
        events.append({"type": "ITEM_PURCHASED", "participantId": p, "itemId": 1055, "timestamp": 5000})
        events.append({"type": "ITEM_PURCHASED", "participantId": p, "itemId": 2003, "timestamp": 6000})
    # Deshacer una compra: Darius compra y devuelve un objeto
    events.append({"type": "ITEM_PURCHASED", "participantId": 1, "itemId": 3071, "timestamp": 7000})
    events.append({"type": "ITEM_UNDO", "participantId": 1, "beforeId": 3071, "afterId": 0, "timestamp": 8000})
    killer, victim = (1, 6) if rng.random() < (0.8 if darius_ignite else 0.4) else (6, 1)
    events.append({"type": "CHAMPION_KILL", "killerId": killer, "victimId": victim, "timestamp": 200_000,
                   "position": {"x": 1000, "y": 12000}})
    # Emboscada: el jungla rojo (7) mata a Darius con ayuda de Garen
    events.append({"type": "CHAMPION_KILL", "killerId": 7, "victimId": 1, "assistingParticipantIds": [6],
                   "timestamp": 400_000, "position": {"x": 1500, "y": 11000}})
    events.append({"type": "ITEM_PURCHASED", "participantId": 1, "itemId": 3071, "timestamp": 700_000})
    events.append({"type": "TURRET_PLATE_DESTROYED", "laneType": "TOP_LANE", "teamId": 200,
                   "killerId": 1, "timestamp": 600_000})
    frames[1]["events"] = events
    return ({"metadata": {"matchId": f"EUW1_{i}", "participants": [f"puuid{p}" for p in range(10)]},
             "info": {"gameDuration": 1800 + rng.randint(-600, 600), "gameVersion": "26.18.1.1",
                      "gameCreation": 0, "queueId": 420, "participants": parts}},
            {"info": {"frames": frames}})


def _meta(i):
    tier = ["SILVER", "GOLD", "DIAMOND", "CHALLENGER"][i % 4]
    div = None if tier == "CHALLENGER" else "II"
    return {"platform": "euw1", "tier": tier, "division": div, "tier_score": config.tier_score(tier, div),
            "rank_source": "semilla"}


def _load_db(static, n=80, seed=1):
    rng = random.Random(seed)
    conn = db.connect(":memory:")
    for i in range(n):
        parsed, reason = parse_match(*fake_game(i, rng), static.legendary_item_ids(), _meta(i))
        assert reason is None
        db.save_parsed(conn, parsed)
    return conn


def test_stat_formula():
    assert stat_at_level(100, 10, 1) == 100
    assert round(stat_at_level(0, 10, 18), 1) == 170.0


def test_tier_score():
    assert config.tier_score("IRON", "IV") == 0
    assert config.tier_score("GOLD", "I") < config.tier_score("PLATINUM", "IV")
    assert config.tier_from_score(config.tier_score("EMERALD", "II")) == ("EMERALD", "II")
    assert config.tier_from_score(36) == ("CHALLENGER", None)


def test_parser_new_fields(static):
    parsed, _ = parse_match(*fake_game(0, random.Random(0)), static.legendary_item_ids(), _meta(0))
    darius = next(r for r in parsed["matchups"] if r["champ"] == "Darius")
    assert (darius["spell1"], darius["spell2"]) == (FLASH, IGNITE)
    assert darius["keystone"] == CONQUEROR and darius["primary_style"] == 8000
    assert darius["skill_order"] == "QWE"
    assert darius["start_items"] == "1055,2003"          # el objeto devuelto no cuenta
    assert darius["plates_taken"] == 1 and darius["plates_lost"] == 0
    assert darius["first_legendary_time"] == 700_000     # la compra deshecha del minuto 0 no cuenta
    gank = [d for d in parsed["deaths"] if d["champ"] == "Darius" and d["enemy_jungler_involved"]]
    assert len(gank) == 1 and gank[0]["killer_role"] == "JUNGLE"
    assert parsed["match"]["tier"] == "SILVER"


def test_pipeline(static):
    conn = _load_db(static)
    rep = matchup_report(conn, static, "darius", "garen", "top")
    assert rep["games"] == 80 and rep["reliable"]
    assert rep["first_to"][2][0] == 1.0
    lvl3 = next(L for L in rep["levels"] if L["level"] == 3)
    assert lvl3["solo_kills_a"] + lvl3["solo_kills_b"] == 80
    assert rep["diffs"][10]["gold"] == 400
    assert rep["ganks"]["Darius"] == 1.0 and rep["ganks"]["Garen"] == 0.0
    assert rep["plates"]["Darius"] == 1.0
    assert [L["level"] for L in rep["levels"]] == [1, 3, 6, 9, 12, 15, 18]
    lane_a, lane_b = rep["lane"]["Darius"], rep["lane"]["Garen"]
    assert lane_a["lane_kill_rate"] + lane_b["lane_kill_rate"] == 1.0   # una muerte de calle por partida
    assert lane_a["solo_kills_pg"] == lane_a["kills_pg"] and lane_a["assisted_kills_pg"] == 0
    assert max(rep["diffs"]) == 25                         # la partida simulada dura 25 minutos de timeline
    top_spells = rep["builds"]["Darius"]["Hechizos"]
    assert {e["label"] for e in top_spells} == {"Destello + Prender", "Destello + Teleportar"}
    assert rep["builds"]["Darius"]["Objetos iniciales"][0]["label"] == "Filo de Doran + Poción de vida"
    rev = matchup_report(conn, static, "garen", "darius", "top")
    assert abs(rev["winrate_raw"] + rep["winrate_raw"] - 1) < 1e-9


def test_filters(static):
    conn = _load_db(static)
    ignite = matchup_report(conn, static, "darius", "garen", "top",
                            filters=Filters(spells_a=[static.spell_id("Prender")]))
    no_ignite = matchup_report(conn, static, "darius", "garen", "top",
                               filters=Filters(spells_a=[static.spell_id("teleport")]))
    assert ignite["games"] == no_ignite["games"] == 40
    share = lambda r: next(L for L in r["levels"] if L["level"] == 3)["solo_kills_a"] / 40
    assert share(ignite) > share(no_ignite)                # con Prender gana más duelos (datos sintéticos)
    assert matchup_report(conn, static, "darius", "garen", "top",
                          filters=Filters(keystone_a=static.rune_id("Conqueror")))["games"] == 80
    assert matchup_report(conn, static, "darius", "garen", "top",
                          filters=Filters(keystone_a=static.rune_id("Garras del Inmortal")))["games"] == 0
    gold_plus = matchup_report(conn, static, "darius", "garen", "top", filters=Filters(tier_min="GOLD"))
    assert gold_plus["games"] == 60 and "SILVER" not in gold_plus["tiers"]
    only_dia = matchup_report(conn, static, "darius", "garen", "top",
                              filters=Filters(tier_min="DIAMOND", tier_max="DIAMOND"))
    assert only_dia["games"] == 20 and set(only_dia["tiers"]) == {"DIAMOND"}


def test_raw_store_and_rebuild(static, tmp_path):
    from lolmatchups.rebuild import rebuild
    rng = random.Random(3)
    conn = db.connect(":memory:")
    for i in range(12):
        match, tl = fake_game(i, rng)
        raw_store.save("euw1", match["metadata"]["matchId"], match, tl, _meta(i), tmp_path)
    ok, skipped = rebuild(conn, static, tmp_path)
    assert (ok, skipped) == (12, 0)
    assert conn.execute("SELECT COUNT(*) FROM lane_matchups").fetchone()[0] == 120
    assert raw_store.disk_usage(tmp_path)[0] == 12


class FakeClient:
    """Imita la Riot API para probar el recolector sin conexión."""
    platform = "euw1"

    def __init__(self, platform="euw1"):
        self.platform = platform
        self.requests_made = 0
        self.start_times = []
        self.rng = random.Random(5)
        self.games = {}
        self.n = 0

    def apex_league(self, tier):
        return {"entries": [{"puuid": f"{self.platform}-{tier}-{k}", "rank": "I"} for k in range(3)]}

    def league_entries(self, tier, division, page=1):
        return [{"puuid": f"{self.platform}-{tier}-{division}-{page}-{k}", "rank": division} for k in range(2)] if page == 1 else []

    def rank_by_puuid(self, puuid):
        return ("EMERALD", "I")

    def match_ids(self, puuid, count=20, start_time=None):
        self.start_times.append(start_time)
        ids = []
        for _ in range(3):
            self.n += 1
            mid = f"{self.platform.upper()}_{self.n}"
            self.games[mid] = fake_game(self.n, self.rng)
            ids.append(mid)
        return ids

    def match(self, mid):
        m = self.games[mid][0]
        m["metadata"]["matchId"] = mid
        return m

    def timeline(self, mid):
        return self.games[mid][1]


def test_crawler(static, tmp_path):
    from lolmatchups.collector import crawl
    conn = db.connect(":memory:")
    counts = crawl(FakeClient(), conn, static, max_matches=12, tiers=["GOLD", "DIAMOND", "CHALLENGER"],
                   raw_dir=tmp_path)
    assert counts == {"GOLD": 4, "DIAMOND": 4, "CHALLENGER": 4}
    tiers = dict(conn.execute("SELECT tier, COUNT(*) FROM matches GROUP BY tier").fetchall())
    assert tiers == {"GOLD": 4, "DIAMOND": 4, "CHALLENGER": 4}
    assert raw_store.disk_usage(tmp_path)[0] == 12
    # Modo preciso: la liga es la media real de los 10 jugadores
    conn2 = db.connect(":memory:")
    crawl(FakeClient(), conn2, static, max_matches=2, tiers=["GOLD"], precise_rank=True, raw_dir=tmp_path / "p")
    row = conn2.execute("SELECT tier, division, rank_source FROM matches LIMIT 1").fetchone()
    assert tuple(row) == ("EMERALD", "I", "media_10")


def test_crawl_many_regions(static, tmp_path, monkeypatch):
    """Varios servidores de regiones distintas a la vez, cada uno con su propio cupo de peticiones."""
    import lolmatchups.riot_client as rc
    from lolmatchups.collector import crawl_many
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "multi.db")
    monkeypatch.setattr(config, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(rc, "RiotClient", lambda platform: FakeClient(platform))
    db.connect().close()
    results = crawl_many(["euw1", "kr"], static, 8, tiers=["GOLD", "DIAMOND"])
    assert results == {"euw1": {"GOLD": 2, "DIAMOND": 2}, "kr": {"GOLD": 2, "DIAMOND": 2}}
    conn = db.connect()
    assert dict(conn.execute("SELECT platform, COUNT(*) FROM matches GROUP BY platform").fetchall()) == {"euw1": 4, "kr": 4}
    with pytest.raises(ValueError):          # euw1 y eun1 comparten la región europe
        crawl_many(["euw1", "eun1"], static, 4)


def test_patch_start_limits_requests(static, tmp_path):
    """Con filtro de parche, tras guardar la primera partida solo se piden partidas desde el inicio del parche."""
    import time as _time
    from lolmatchups.collector import crawl
    client = FakeClient()
    conn = db.connect(":memory:")
    crawl(client, conn, static, max_matches=6, tiers=["GOLD"], patches={"26.18"}, raw_dir=tmp_path, max_days=16)
    conn.execute("UPDATE matches SET game_creation=?", (int((_time.time() - 3600) * 1000),))
    conn.commit()
    crawl(client, conn, static, max_matches=3, tiers=["GOLD"], patches={"26.18"}, raw_dir=tmp_path, max_days=16)
    assert _time.time() - client.start_times[-1] < 2.1 * 86400   # partida más antigua del parche - 2 días
    assert _time.time() - client.start_times[0] > 15.9 * 86400   # al principio, los 16 días completos


def test_min_tier(static, tmp_path, monkeypatch):
    """No se aceptan ligas por debajo de la mínima, ni partidas cuya liga media real quede por debajo."""
    from lolmatchups.collector import crawl
    with pytest.raises(ValueError):
        crawl(FakeClient(), db.connect(":memory:"), static, max_matches=2, tiers=["SILVER"], raw_dir=tmp_path)
    low = FakeClient()
    low.rank_by_puuid = lambda puuid: ("SILVER", "I")
    conn = db.connect(":memory:")
    counts = crawl(low, conn, static, max_matches=2, tiers=["GOLD"], precise_rank=True, raw_dir=tmp_path)
    assert counts == {"GOLD": 0}
    assert conn.execute("SELECT COUNT(*) FROM skipped_matches WHERE reason='liga_baja'").fetchone()[0] > 0
    assert raw_store.disk_usage(tmp_path)[0] == 0


def test_skill_ranks():
    from lolmatchups.theory import ranks_at
    assert ranks_at(1) == [1, 0, 0, 0]
    assert ranks_at(3) == [1, 1, 1, 0]
    assert ranks_at(6) == [3, 1, 1, 1]
    assert ranks_at(9) == [5, 2, 1, 1]
    assert ranks_at(18) == [5, 5, 5, 3]


def test_remake_skipped(static):
    match, tl = fake_game(0, random.Random(0))
    match["info"]["gameDuration"] = 120
    assert parse_match(match, tl, set()) == (None, "remake")


def test_multi_hit(static, monkeypatch):
    from lolmatchups.static_data import ability_damage
    attacker = {"ad": 60, "bonus_ad": 0, "ap": 0, "hp": 600}
    monkeypatch.setitem(config.ABILITY_OVERRIDES, "Garen", {})
    single = ability_damage(static.abilities("Garen")["E"], 1, attacker)
    static._ability_cache.clear()
    monkeypatch.setitem(config.ABILITY_OVERRIDES, "Garen", {"E": {"hits": 7}})
    assert ability_damage(static.abilities("Garen")["E"], 1, attacker) == 7 * single


def test_all_champions_real_data():
    """Con los datos reales descargados: todos los campeones simulan sin errores.

    Los campeones que Meraki todavía no ha publicado (muy recientes) no son un error: se avisa de
    ellos y el modelo usa una probabilidad neutra para que manden las partidas reales.
    """
    import warnings

    from lolmatchups.passives import PASSIVES
    from lolmatchups.theory import duel
    if not (config.CACHE_DIR / "summoner_es_ES.json").exists():
        pytest.skip("Datos estáticos no descargados (python main.py static)")
    sd = StaticData()
    known = {k.lower() for k in PASSIVES}
    with_data = [c for c in sd.champions if sd.meraki_champ(c).get("abilities")]
    without_data = [c for c in sd.champions if c not in with_data]
    if without_data:
        warnings.warn(f"Campeones sin datos en Meraki (se usará solo el dato real): {without_data}")
    missing = [c for c in with_data if c.lower() not in known]
    assert not missing, f"Campeones con datos en Meraki pero sin entrada en la tabla de pasivas: {missing}"
    for cid in sd.champions:
        for level in (1, 3, 6):
            r = duel(sd, cid, "Garen", level)
            assert 0 < r["p_a"] < 1
            assert r["available"] == (cid in with_data)
