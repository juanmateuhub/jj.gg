"""Datos estáticos: estadísticas (Data Dragon), habilidades y pasivas (Meraki) y objetos."""
import json
import re

import requests

from . import config

DDRAGON = "https://ddragon.leagueoflegends.com"
MERAKI_CHAMPIONS = "https://cdn.merakianalytics.com/riot/lol/resources/latest/en-US/champions.json"


def stat_at_level(base, growth, level):
    """Fórmula oficial de crecimiento de estadísticas por nivel."""
    n = level - 1
    return base + growth * n * (0.7025 + 0.0175 * n)


def by_level(value, level):
    """Resuelve un valor que puede ser fijo o un rango (nivel 1, nivel 18) interpolado linealmente."""
    if isinstance(value, (tuple, list)):
        a, b = value
        return a + (b - a) * (level - 1) / 17
    return value


def download_all():
    """Descarga los ficheros estáticos a data/cache/. Ejecutar al cambiar de parche."""
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    version = requests.get(f"{DDRAGON}/api/versions.json", timeout=20).json()[0]
    files = {
        "championFull.json": f"{DDRAGON}/cdn/{version}/data/en_US/championFull.json",
        "item.json": f"{DDRAGON}/cdn/{version}/data/en_US/item.json",
        "meraki_champions.json": MERAKI_CHAMPIONS,
    }
    for lang in ("es_ES", "en_US"):
        files[f"summoner_{lang}.json"] = f"{DDRAGON}/cdn/{version}/data/{lang}/summoner.json"
        files[f"runes_{lang}.json"] = f"{DDRAGON}/cdn/{version}/data/{lang}/runesReforged.json"
    files["item_es_ES.json"] = f"{DDRAGON}/cdn/{version}/data/es_ES/item.json"
    for name, url in files.items():
        print(f"Descargando {name} ...")
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        (config.CACHE_DIR / name).write_text(r.text, encoding="utf-8")
    (config.CACHE_DIR / "version.txt").write_text(version, encoding="utf-8")
    return version


def _norm(name):
    return "".join(ch for ch in name.lower() if ch.isalnum())


class StaticData:
    def __init__(self, cache_dir=None):
        cache_dir = cache_dir or config.CACHE_DIR
        try:
            self.champions = json.loads((cache_dir / "championFull.json").read_text(encoding="utf-8"))["data"]
            self.items = json.loads((cache_dir / "item.json").read_text(encoding="utf-8"))["data"]
            meraki = json.loads((cache_dir / "meraki_champions.json").read_text(encoding="utf-8"))
        except FileNotFoundError as e:
            raise FileNotFoundError("Faltan datos estáticos. Ejecuta primero: python main.py static") from e
        self.meraki = {_norm(k): v for k, v in meraki.items()}
        self._load_names(cache_dir)
        self._index = {}
        for cid, c in self.champions.items():
            self._index[_norm(cid)] = cid
            self._index[_norm(c["name"])] = cid
        self._ability_cache = {}

    # ------------------------------------------------------------------ nombres
    def _load_names(self, cache_dir):
        """Hechizos, runas y objetos, en español (para mostrar) e inglés (también aceptado en filtros)."""
        self.spell_names, self.rune_names, self.item_names = {}, {}, {}
        self._spell_index, self._rune_index = {}, {}
        self.rift_spells, self.keystones = set(), []
        try:
            for lang in ("en_US", "es_ES"):  # español al final: es el nombre que se muestra
                spells = json.loads((cache_dir / f"summoner_{lang}.json").read_text(encoding="utf-8"))["data"]
                for sp in spells.values():
                    sid = int(sp["key"])
                    self.spell_names[sid] = sp["name"]
                    if "CLASSIC" in (sp.get("modes") or ["CLASSIC"]):
                        self.rift_spells.add(sid)
                    self._spell_index[_norm(sp["name"])] = sid
                    self._spell_index[_norm(sp["id"].replace("Summoner", ""))] = sid
                trees = json.loads((cache_dir / f"runes_{lang}.json").read_text(encoding="utf-8"))
                self.keystones = [(r["id"], tree["id"]) for tree in trees for r in (tree["slots"] or [{}])[0].get("runes", [])]
                for tree in trees:
                    self.rune_names[tree["id"]] = tree["name"]
                    self._rune_index[_norm(tree["name"])] = tree["id"]
                    self._rune_index[_norm(tree["key"])] = tree["id"]
                    for slot in tree["slots"]:
                        for rune in slot["runes"]:
                            self.rune_names[rune["id"]] = rune["name"]
                            self._rune_index[_norm(rune["name"])] = rune["id"]
                            self._rune_index[_norm(rune["key"])] = rune["id"]
            items_es = json.loads((cache_dir / "item_es_ES.json").read_text(encoding="utf-8"))["data"]
        except FileNotFoundError as e:
            raise FileNotFoundError("Faltan datos estáticos nuevos. Ejecuta: python main.py static") from e
        self.item_names = {int(k): v["name"] for k, v in items_es.items()}
        version_file = cache_dir / "version.txt"
        self.version = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else None

    def spells_list(self):
        """Hechizos de invocador de la Grieta del Invocador, con su nombre en español."""
        return sorted(({"id": s, "name": self.spell_name(s)} for s in self.rift_spells), key=lambda x: x["name"])

    def keystones_list(self):
        return [{"id": rid, "name": self.rune_name(rid), "tree": self.rune_name(tid)} for rid, tid in self.keystones]

    def champion_art(self, champ_id):
        """Retrato cuadrado, imagen de pantalla de carga y splash art del campeón (Data Dragon)."""
        return {"icon": self.champion_icon(champ_id),
                "loading": f"{DDRAGON}/cdn/img/champion/loading/{champ_id}_0.jpg",
                "splash": f"{DDRAGON}/cdn/img/champion/splash/{champ_id}_0.jpg"}

    def champion_icon(self, champ_id):
        if not self.version:
            return None
        return f"{DDRAGON}/cdn/{self.version}/img/champion/{champ_id}.png"

    def spell_id(self, name):
        if str(name).isdigit():
            return int(name)
        sid = self._spell_index.get(_norm(name))
        if sid is None:
            raise KeyError(f"Hechizo de invocador desconocido: {name}")
        return sid

    def rune_id(self, name):
        if str(name).isdigit():
            return int(name)
        rid = self._rune_index.get(_norm(name))
        if rid is None:
            raise KeyError(f"Runa desconocida: {name}")
        return rid

    def spell_name(self, sid):
        return self.spell_names.get(sid, str(sid))

    def rune_name(self, rid):
        return self.rune_names.get(rid, str(rid))

    def item_name(self, iid):
        return self.item_names.get(int(iid), str(iid))

    # ------------------------------------------------------------------ campeones
    def resolve(self, name):
        cid = self._index.get(_norm(name))
        if not cid:
            raise KeyError(f"Campeón desconocido: {name}")
        return cid

    def meraki_champ(self, champ_id):
        return self.meraki.get(_norm(champ_id), {})

    def base_stats(self, champ_id):
        return self.champions[champ_id]["stats"]

    def adaptive_type(self, champ_id):
        return self.meraki_champ(champ_id).get("adaptiveType") or "PHYSICAL_DAMAGE"

    def starter(self, champ_id):
        """Equipo inicial aproximado (objeto inicial + runas) según el tipo de daño del campeón."""
        return config.STARTER.get(self.adaptive_type(champ_id), config.STARTER["PHYSICAL_DAMAGE"])

    def stats_at_level(self, champ_id, level, with_starter=True):
        s = self.base_stats(champ_id)
        start = self.starter(champ_id) if with_starter else {"ad": 0, "ap": 0, "hp": 0}
        ratio = (self.meraki_champ(champ_id).get("stats", {}).get("attackSpeedRatio") or {}).get("flat") \
            or s["attackspeed"]
        bonus_as = stat_at_level(0, s["attackspeedperlevel"], level) / 100
        base_ad = stat_at_level(s["attackdamage"], s["attackdamageperlevel"], level)
        base_hp = stat_at_level(s["hp"], s["hpperlevel"], level)
        return {
            "hp": base_hp + start["hp"], "bonus_hp": start["hp"],
            "base_ad": base_ad, "ad": base_ad + start["ad"], "bonus_ad": start["ad"], "ap": start["ap"],
            "armor": stat_at_level(s["armor"], s["armorperlevel"], level),
            "mr": stat_at_level(s["spellblock"], s["spellblockperlevel"], level),
            "base_as": s["attackspeed"], "as_ratio": ratio, "bonus_as": bonus_as,
            "range": s["attackrange"],
        }

    def passive_cooldown(self, champ_id, level):
        p = (self.meraki_champ(champ_id).get("abilities", {}).get("P") or [{}])[0]
        mods = (p.get("cooldown") or {}).get("modifiers") or []
        if not mods or not mods[0].get("values"):
            return None
        vals = mods[0]["values"]
        if len(vals) >= 18:
            return float(vals[level - 1])
        if len(vals) == 3:  # por rangos de nivel 1-5 / 6-10 / 11+
            return float(vals[0 if level < 6 else 1 if level < 11 else 2])
        return float(vals[min(level - 1, len(vals) - 1)])

    def abilities(self, champ_id):
        """Q, W, E, R con el daño contra campeones, golpes, enfriamiento y tipo de daño."""
        if champ_id in self._ability_cache:
            return self._ability_cache[champ_id]
        m = self.meraki_champ(champ_id)
        overrides = config.ABILITY_OVERRIDES.get(champ_id, {})
        result = {}
        for key in ("Q", "W", "E", "R"):
            if m.get("abilities", {}).get(key):
                ov = overrides.get(key, {})
                ability = parse_ability(m["abilities"][key][0], ov.get("attribute"))
                if "hits" in ov:
                    ability["hits"], ability["hits_source"] = ov["hits"], "manual"
                if "attack_lock" in ov:
                    ability["attack_lock"] = float(ov["attack_lock"])
                if "duration" in ov:
                    ability["duration"] = float(ov["duration"])
                if "cooldown" in ov:
                    ability["cooldown"], ability["cooldown_source"] = [float(ov["cooldown"])], "manual"
                result[key] = ability
        self._ability_cache[champ_id] = result
        return result

    def legendary_item_ids(self):
        """Objetos 'completos' (aproximación: >= 2200 de oro, sin mejoras y comprables en la Grieta)."""
        ids = set()
        for iid, it in self.items.items():
            gold = it.get("gold", {})
            if (gold.get("total", 0) >= 2200 and gold.get("purchasable", False)
                    and not it.get("into") and it.get("maps", {}).get("11", False)):
                ids.add(int(iid))
        return ids


# ----------------------------------------------------------------------------------------------
# Lectura de habilidades
# ----------------------------------------------------------------------------------------------
_EXCLUDED = ("minion", "monster", "non-champion", "structure", "turret", "reduction", "reduced", "increase",
             "modifier", "threshold", "heal", "shield", "bonus attack damage", "secondary", "sweetspot",
             "clone", "pet", "tower", "soldier", "effectiveness")
_PER_HIT = re.compile(r"\bper (spin|tick|second|hit|shot|bolt|arrow|bullet|pass|orb|slash|strike|wave|dagger|missile)\b")
_TIMES = re.compile(r"(\d+)\s*(?:\([^)]*\)\s*)?times\b")
_EVERY_OVER = re.compile(r"every ([\d.]+) seconds? over ([\d.]+) seconds")
_OVER = re.compile(r"over ([\d.]+) seconds")
_ATTACK_LOCK = re.compile(r"(?:unable to|cannot) (?:declare )?basic attack")
_LOCK_TIME = re.compile(r"(?:over|for) ([\d.]+) seconds")
_COUNT = re.compile(r"\b(\d+)\s+(?:bolts|shots|arrows|bullets|missiles|strikes|slashes|daggers|waves|spins|hits)\b")


def _score(attr):
    a = attr.lower()
    if "damage" not in a or any(w in a for w in _EXCLUDED):
        return None
    if "minimum" in a:
        return 1.2 if "total" in a else 0.5
    if _PER_HIT.search(a):
        return 1
    if "total" in a:
        return 3
    if "maximum" in a:
        return 1.5
    return 2


def _modifiers(leveling):
    out = {"flat": [0.0], "ad": [0.0], "bonus_ad": [0.0], "ap": [0.0], "tmaxhp": [0.0], "maxhp": [0.0]}
    for mod in leveling.get("modifiers", []):
        vals = [float(v) for v in (mod.get("values") or [0]) if isinstance(v, (int, float))] or [0.0]
        unit = ((mod.get("units") or [""])[0] or "").strip().lower()
        if unit == "":
            out["flat"] = vals
        elif unit == "% ad":
            out["ad"] = [v / 100 for v in vals]
        elif unit == "% bonus ad":
            out["bonus_ad"] = [v / 100 for v in vals]
        elif unit == "% ap":
            out["ap"] = [v / 100 for v in vals]
        elif "target" in unit and "maximum health" in unit and "per 100" not in unit:
            out["tmaxhp"] = [v / 100 for v in vals]
        elif unit == "% maximum health":
            out["maxhp"] = [v / 100 for v in vals]
    return out


def _hits_from_text(text):
    t = text.lower()
    m = _TIMES.search(t)
    if m:
        return int(m.group(1))
    m = _EVERY_OVER.search(t)
    if m:
        return max(1, round(float(m.group(2)) / float(m.group(1))))
    m = _COUNT.search(t)
    if m:
        return int(m.group(1))
    return None


def parse_ability(ab, forced_attribute=None):
    best, best_score, best_text = None, -1, ""
    for eff in ab.get("effects", []):
        for lv in eff.get("leveling", []):
            if forced_attribute:
                sc = 99 if (lv.get("attribute") or "") == forced_attribute else None
            else:
                sc = _score(lv.get("attribute") or "")
            if sc is not None and sc > best_score:
                best, best_score, best_text = lv, sc, eff.get("description", "")
    all_text = " ".join(e.get("description", "") for e in ab.get("effects", []))
    cd_mods = (ab.get("cooldown") or {}).get("modifiers") or [{}]
    cooldown = [float(v) for v in (cd_mods[0].get("values") or [10.0])]
    dtype = (ab.get("damageType") or "PHYSICAL_DAMAGE").upper()
    info = {"attribute": "", "has_damage": False, "hits": 1, "hits_source": "-", "cooldown": cooldown,
            "cooldown_source": "meraki", "attack_lock": 0.0, "duration": 0.0,
            "damage_type": dtype, **{k: [0.0] for k in ("flat", "ad", "bonus_ad", "ap", "tmaxhp", "maxhp")}}
    lock = _ATTACK_LOCK.search(all_text.lower())
    if lock:
        m = _LOCK_TIME.search(all_text.lower())
        info["attack_lock"] = float(m.group(1)) if m else 0.0
    if best is None:
        return info
    attr = best.get("attribute") or ""
    info.update(_modifiers(best))
    info.update({"attribute": attr, "has_damage": True})
    per_hit = _PER_HIT.search(attr.lower())
    if "total" in attr.lower() or per_hit:
        m = _OVER.search(best_text.lower())
        if m:
            info["duration"] = min(float(m.group(1)), 15.0)
    if per_hit:
        kind = per_hit.group(1)
        hits = None
        if kind == "second":
            m = _OVER.search(best_text.lower()) or _OVER.search(all_text.lower())
            hits = round(float(m.group(1))) if m else None
        else:
            hits = _hits_from_text(best_text) or _hits_from_text(all_text)
        info["hits"], info["hits_source"] = (hits, "auto") if hits else (1, "REVISAR")
    return info


def _rank_value(values, rank):
    return float(values[min(rank - 1, len(values) - 1)]) if values else 0.0


def ability_damage(ability, rank, attacker, target_max_hp=0.0):
    """Daño total (antes de resistencias) de una habilidad a un rango dado."""
    r = lambda k: _rank_value(ability[k], rank)
    per_hit = (r("flat") + r("ad") * attacker["ad"] + r("bonus_ad") * attacker["bonus_ad"]
               + r("ap") * attacker["ap"] + r("tmaxhp") * target_max_hp + r("maxhp") * attacker["hp"])
    return per_hit * ability.get("hits", 1)


def ability_cooldown(ability, rank):
    return max(_rank_value(ability["cooldown"], rank), 0.5)
