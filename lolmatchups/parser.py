"""Convierte una partida + su timeline (Match-v5) en filas de análisis por calle."""
import bisect

from . import config

ROLES = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")
ROLE_LANE = {"TOP": "TOP_LANE", "MIDDLE": "MID_LANE", "BOTTOM": "BOT_LANE", "UTILITY": "BOT_LANE"}
SKILL_KEYS = {1: "Q", 2: "W", 3: "E", 4: "R"}
TRINKETS = {3340, 3363, 3364, 3330, 3513}


def patch_of(game_version):
    return ".".join(game_version.split(".")[:2])


def _perks(p):
    styles = (p.get("perks") or {}).get("styles") or []
    primary = styles[0] if styles else {}
    secondary = styles[1] if len(styles) > 1 else {}
    selections = primary.get("selections") or [{}]
    return selections[0].get("perk"), primary.get("style"), secondary.get("style")


def parse_match(match, timeline, legendary_ids, meta=None):
    """Devuelve (filas, None) o (None, motivo) si la partida no sirve.

    meta: {'platform', 'tier', 'division', 'tier_score', 'rank_source'} de la recogida.
    """
    meta = meta or {}
    info = match["info"]
    match_id = match["metadata"]["matchId"]
    if info.get("gameDuration", 0) < config.MIN_GAME_DURATION:
        return None, "remake"
    parts = info["participants"]
    if any(p.get("gameEndedInEarlySurrender") for p in parts):
        return None, "rendicion_temprana"

    lanes = {}
    for p in parts:
        if p.get("teamPosition") in ROLES:
            lanes.setdefault(p["teamPosition"], {})[p["teamId"]] = p
    if len(lanes) != 5 or any(len(v) != 2 for v in lanes.values()):
        return None, "posiciones_incompletas"

    frames = timeline["info"]["frames"]
    events = sorted((e for f in frames for e in f.get("events", [])), key=lambda e: e["timestamp"])
    by_pid = {p["participantId"]: p for p in parts}

    # --- Niveles, habilidades, objetos y placas a partir de los eventos ---
    level_times = {pid: [0] for pid in by_pid}
    level_vals = {pid: [1] for pid in by_pid}
    skills = {pid: [] for pid in by_pid}
    start_items = {pid: [] for pid in by_pid}
    first_legendary = {}
    plates = []  # (lane, team propietario de la torre)
    for e in events:
        et, pid, ts = e["type"], e.get("participantId"), e["timestamp"]
        if et == "LEVEL_UP" and pid in level_times:
            level_times[pid].append(ts)
            level_vals[pid].append(e["level"])
        elif et == "SKILL_LEVEL_UP" and pid in skills and e.get("levelUpType", "NORMAL") == "NORMAL":
            skills[pid].append(SKILL_KEYS.get(e.get("skillSlot"), "?"))
        elif et == "ITEM_PURCHASED" and pid in start_items:
            if ts <= config.START_ITEMS_WINDOW_MS and e.get("itemId") not in TRINKETS:
                start_items[pid].append(e["itemId"])
            if e.get("itemId") in legendary_ids and pid not in first_legendary:
                first_legendary[pid] = (ts, e["itemId"])
        elif et == "ITEM_UNDO" and pid in start_items:
            # Compra deshecha: no cuenta ni como objeto inicial ni como primer objeto completo
            if pid in first_legendary and first_legendary[pid][1] == e.get("beforeId"):
                del first_legendary[pid]
            if ts <= config.START_ITEMS_WINDOW_MS:
                if e.get("beforeId") in start_items[pid]:
                    start_items[pid].remove(e["beforeId"])
                if e.get("afterId") and e["afterId"] not in TRINKETS:
                    start_items[pid].append(e["afterId"])
        elif et == "TURRET_PLATE_DESTROYED" and ts <= config.EARLY_WINDOW_MS:
            plates.append((e.get("laneType"), e.get("teamId")))

    first_legendary = {pid: v[0] for pid, v in first_legendary.items()}

    def level_at(pid, ts):
        i = bisect.bisect_right(level_times[pid], ts) - 1
        return level_vals[pid][max(i, 0)]

    def reached(pid, lvl):
        for t, v in zip(level_times[pid], level_vals[pid]):
            if v >= lvl:
                return t
        return None

    def first_to(pa, pb, lvl):
        ta, tb = reached(pa, lvl), reached(pb, lvl)
        if (ta is None and tb is None) or ta == tb:
            return None
        if tb is None:
            return 1
        if ta is None:
            return 0
        return int(ta < tb)

    opponents, role_of = {}, {}
    jungler = {}
    for role, teams in lanes.items():
        a, b = teams[100], teams[200]
        opponents[a["participantId"]] = b["participantId"]
        opponents[b["participantId"]] = a["participantId"]
        role_of[a["participantId"]] = role_of[b["participantId"]] = role
        if role == "JUNGLE":
            jungler[100], jungler[200] = a["participantId"], b["participantId"]
    champ_of = {pid: p["championName"] for pid, p in by_pid.items()}
    team_of = {pid: p["teamId"] for pid, p in by_pid.items()}

    matchups, frame_rows, kill_rows, death_rows = [], [], [], []
    for pid, opp in opponents.items():
        p = by_pid[pid]
        role = role_of[pid]
        keystone, primary, secondary = _perks(p)
        lane = ROLE_LANE.get(role)
        taken = sum(1 for ln, owner in plates if lane and ln == lane and owner != team_of[pid]) if lane else None
        lost = sum(1 for ln, owner in plates if lane and ln == lane and owner == team_of[pid]) if lane else None
        matchups.append({
            "match_id": match_id, "role": role, "champ": champ_of[pid], "opponent": champ_of[opp],
            "win": int(p["win"]),
            "first_to_2": first_to(pid, opp, 2), "first_to_3": first_to(pid, opp, 3),
            "first_to_6": first_to(pid, opp, 6),
            "first_legendary_time": first_legendary.get(pid),
            "spell1": min(p.get("summoner1Id", 0), p.get("summoner2Id", 0)),
            "spell2": max(p.get("summoner1Id", 0), p.get("summoner2Id", 0)),
            "keystone": keystone, "primary_style": primary, "secondary_style": secondary,
            "skill_order": "".join(skills[pid])[:18],
            "start_items": ",".join(str(i) for i in sorted(start_items[pid])),
            "plates_taken": taken, "plates_lost": lost,
        })
        for minute in range(1, min(config.LANE_FRAME_MAX_MINUTE, len(frames) - 1) + 1):
            pf = frames[minute]["participantFrames"]
            me, them = pf[str(pid)], pf[str(opp)]
            cs = lambda x: x.get("minionsKilled", 0) + x.get("jungleMinionsKilled", 0)
            frame_rows.append({
                "match_id": match_id, "role": role, "champ": champ_of[pid], "minute": minute,
                "gold_diff": me["totalGold"] - them["totalGold"], "xp_diff": me["xp"] - them["xp"],
                "cs_diff": cs(me) - cs(them),
            })

    for e in events:
        if e["type"] != "CHAMPION_KILL":
            continue
        k, v, ts = e.get("killerId", 0), e.get("victimId", 0), e["timestamp"]
        assists = e.get("assistingParticipantIds") or []
        if k in opponents and opponents[k] == v:
            kill_rows.append({
                "match_id": match_id, "role": role_of[k], "killer": champ_of[k], "victim": champ_of[v],
                "timestamp": ts, "killer_level": level_at(k, ts), "victim_level": level_at(v, ts),
                "solo": int(not assists),
                "killer_has_item": int(first_legendary.get(k, 10**9) <= ts),
                "victim_has_item": int(first_legendary.get(v, 10**9) <= ts),
            })
        if v in opponents and ts <= config.DEATHS_WINDOW_MS:
            involved = {k, *assists}
            enemy_team = 300 - team_of[v]
            pos = e.get("position") or {}
            death_rows.append({
                "match_id": match_id, "role": role_of[v], "champ": champ_of[v], "opponent": champ_of[opponents[v]],
                "timestamp": ts, "level": level_at(v, ts),
                "killer_role": role_of.get(k, "OTRO"),
                "enemy_jungler_involved": int(jungler.get(enemy_team) in involved),
                "lane_opponent_involved": int(opponents[v] in involved),
                "solo": int(not assists), "x": pos.get("x"), "y": pos.get("y"),
            })

    return {
        "match": {"match_id": match_id, "platform": meta.get("platform", ""),
                  "patch": patch_of(info["gameVersion"]), "game_duration": info["gameDuration"],
                  "game_creation": info.get("gameCreation", 0), "tier": meta.get("tier"),
                  "division": meta.get("division"), "tier_score": meta.get("tier_score"),
                  "rank_source": meta.get("rank_source")},
        "matchups": matchups, "frames": frame_rows, "kills": kill_rows, "deaths": death_rows,
    }, None
