"""Modelo teórico de duelo: simulación simultánea de dos campeones con habilidades y pasivas.

Sigue siendo una APROXIMACIÓN: no modela control de masas, esquivar habilidades, oleadas de súbditos
ni posicionamiento. Por eso se usa como punto de partida ('prior') que los datos reales corrigen.
"""
from .passives import MERAKI_CD, PASSIVES
from .static_data import _norm, ability_cooldown, ability_damage, by_level

SIM_DT = 0.05
SIM_MAX_TIME = 40.0
SHARPNESS = 2.0
MAX_ATTACK_SPEED = 2.5
# Orden de subida estándar: 1 = habilidad principal, 2 = secundaria, 3 = terciaria, R = definitiva.
SKILL_ORDER = [1, 2, 3, 1, 1, "R", 1, 2, 1, 2, "R", 2, 2, 3, 3, "R", 3, 3]


def ranks_at(level):
    """Rangos de (principal, secundaria, terciaria, definitiva) a un nivel dado."""
    order = SKILL_ORDER[:level]
    return [order.count(1), order.count(2), order.count(3), order.count("R")]
_PASSIVES_NORM = {_norm(k): v for k, v in PASSIVES.items()}


def passive_of(champ_id):
    return _PASSIVES_NORM.get(_norm(champ_id), {"status": "no_modelada", "note": "Sin entrada en la tabla.",
                                                "effects": []})


class Fighter:
    def __init__(self, sd, champ_id, level):
        self.id, self.level, self.sd = champ_id, level, sd
        self.s = sd.stats_at_level(champ_id, level)
        self.effects = passive_of(champ_id)["effects"]
        v = lambda x: by_level(x, level)

        # --- Estadísticas planas de la pasiva ---
        self.as_passive = self.lifesteal = self.flat_reduction = self.magic_reduction = 0.0
        self.magic_to_true = self.ability_heal = self.first_hit_reduction = 0.0
        self.auto_multiplier = 1.0
        for e in self.effects:
            if e["kind"] != "stats":
                continue
            self.s["ad"] += v(e.get("ad", 0)) + v(e.get("ad_pct", 0)) * self.s["base_ad"]
            self.s["bonus_ad"] += v(e.get("ad", 0)) + v(e.get("ad_pct", 0)) * self.s["base_ad"]
            self.s["armor"] += v(e.get("armor", 0))
            self.s["mr"] += v(e.get("mr", 0))
            if e.get("ad_from_resists"):
                extra = e["ad_from_resists"] * (self.s["armor"] + self.s["mr"])
                self.s["ad"] += extra
                self.s["bonus_ad"] += extra
            if e.get("convert_bonus_hp_to_ad"):
                extra = self.s["bonus_hp"] * e["convert_bonus_hp_to_ad"]
                self.s["hp"] -= self.s["bonus_hp"]
                self.s["ad"] += extra
                self.s["bonus_ad"] += extra
            self.as_passive += v(e.get("as_pct", 0))
            self.lifesteal += v(e.get("lifesteal", 0))
            self.flat_reduction += v(e.get("flat_reduction", 0))
            self.magic_reduction += v(e.get("magic_reduction", 0))
            self.magic_to_true += v(e.get("magic_to_true", 0))
            self.ability_heal += v(e.get("ability_heal", 0))
            self.first_hit_reduction = max(self.first_hit_reduction, v(e.get("first_hit_reduction", 0)))
            self.auto_multiplier *= e.get("auto_multiplier", 1.0)

        self.max_hp = self.hp = self.s["hp"]
        self.shield = 0.0
        self.t_now = 0.0
        self.dead_at = None
        self.first_hit_taken = False
        self.low_hp_shield_used = False
        self.next_auto = 0.0
        self.loadout = self._loadout()
        self.next_cast = {k: 0.0 for k, _, _ in self.loadout}
        self.ready_at = {}        # índice de efecto -> instante en que vuelve a estar disponible
        self.counters = {}        # índice de efecto -> golpes acumulados (procs)
        self.used_once = set()
        self.charges = {}         # índice de efecto -> cargas tras habilidad
        self.ramp = {}            # índice de efecto -> (acumulaciones, último golpe)
        self.dot_apps = {}        # índice de efecto -> instantes de aplicación
        self.ad_buff_until, self.ad_buff = -1.0, 0.0
        self.ability_dots = []    # daño de habilidades repartido en el tiempo: (fin, dps, tipo)
        for i, e in enumerate(self.effects):
            if e["kind"] == "shield" and e.get("trigger") == "start":
                self.shield += self._shield_amount(e)

    # ------------------------------------------------------------------ utilidades
    def v(self, x):
        return by_level(x, self.level)

    def cooldown_of(self, e):
        cd = e.get("cooldown")
        if cd == MERAKI_CD:
            return self.sd.passive_cooldown(self.id, self.level) or 10.0
        return cd

    def available(self, i, e, t):
        if e.get("once") and i in self.used_once:
            return False
        return t >= self.ready_at.get(i, 0.0)

    def consume(self, i, e, t):
        if e.get("once"):
            self.used_once.add(i)
        cd = self.cooldown_of(e)
        if cd:
            self.ready_at[i] = t + cd

    def _shield_amount(self, e):
        return (self.v(e.get("flat", 0)) + self.v(e.get("maxhp_pct", 0)) * self.max_hp
                + self.v(e.get("ap", 0)) * self.s["ap"])

    def _loadout(self):
        abil = self.sd.abilities(self.id)
        basics = [(k, a) for k, a in abil.items() if k != "R"]
        # Orden de subida: la habilidad con más daño por segundo (enfriamiento mínimo de 4 s para no
        # sobrevalorar las de uso continuo); las que no hacen daño, al final.
        dmg = lambda a: (ability_damage(a, 1, self.s, 1000) / max(a["cooldown"][0], 4.0)) if a["has_damage"] else -1
        basics.sort(key=lambda ka: dmg(ka[1]), reverse=True)
        ranks = ranks_at(self.level)
        loadout = []
        for i, (k, a) in enumerate(basics[:3]):
            if ranks[i] > 0:
                loadout.append((k, a, ranks[i]))
        if ranks[3] > 0 and "R" in abil:
            loadout.append(("R", abil["R"], ranks[3]))
        return loadout

    def attack_speed(self, t):
        bonus = self.s["bonus_as"] + self.as_passive
        for i, e in enumerate(self.effects):
            if e["kind"] == "ramp" and e.get("as_per_stack"):
                stacks, last = self.ramp.get(i, (0, -99))
                if t - last <= e.get("duration", 5):
                    bonus += stacks * self.v(e["as_per_stack"])
            elif e["kind"] == "after_ability" and e.get("as_bonus") and self.charges.get(i, 0) > 0:
                bonus += self.v(e["as_bonus"])
            elif e["kind"] == "missing_hp":
                frac = min(max(1 - self.hp / self.max_hp, 0) / e["at_missing"], 1)
                bonus += frac * self.v(e["as_pct"])
        return min(self.s["base_as"] + self.s["as_ratio"] * bonus, MAX_ATTACK_SPEED)

    def current_lifesteal(self):
        ls = self.lifesteal
        for e in self.effects:
            if e["kind"] == "missing_hp" and e.get("lifesteal"):
                frac = min(max(1 - self.hp / self.max_hp, 0) / e["at_missing"], 1)
                ls += frac * self.v(e["lifesteal"])
        return ls

    def heal(self, amount):
        if self.dead_at is None:
            self.hp = min(self.max_hp, self.hp + amount)

    # ------------------------------------------------------------------ recibir daño
    def take(self, amount, dtype, t):
        if amount <= 0:
            return 0.0
        if dtype == "PHYSICAL":
            amount *= 100 / (100 + max(self.s["armor"], 0))
        elif dtype == "MAGIC":
            amount *= 100 / (100 + max(self.s["mr"], 0)) * (1 - self.magic_reduction)
        if self.flat_reduction:
            amount = max(amount - self.flat_reduction, amount * 0.5)
        if not self.first_hit_taken:
            self.first_hit_taken = True
            amount *= 1 - self.first_hit_reduction
        dealt = amount
        absorbed = min(self.shield, amount)
        self.shield -= absorbed
        self.hp -= amount - absorbed
        for e in self.effects:
            if (e["kind"] == "shield" and e.get("trigger") == "low_hp" and not self.low_hp_shield_used
                    and 0 < self.hp < e["threshold"] * self.max_hp):
                self.low_hp_shield_used = True
                self.shield += self._shield_amount(e)
        if self.hp <= 0 and self.dead_at is None:
            self.dead_at = t
        return dealt


def _effect_damage(att, e, target, v=None):
    v = v or att.v
    return (v(e.get("flat", 0)) + v(e.get("ad", 0)) * att.current_ad() + v(e.get("bonus_ad", 0)) * att.s["bonus_ad"]
            + v(e.get("ap", 0)) * att.s["ap"] + v(e.get("tmaxhp", 0)) * target.max_hp
            + v(e.get("tcurhp", 0)) * max(target.hp, 0) + v(e.get("tmissing", 0)) * (target.max_hp - max(target.hp, 0))
            + v(e.get("armor_pct", 0)) * att.s["armor"] + v(e.get("mr_pct", 0)) * att.s["mr"]
            + v(e.get("bonus_mr", 0)) * 0)


def _current_ad(self):
    return self.s["ad"] + (self.ad_buff if self.t_now <= self.ad_buff_until else 0)


Fighter.current_ad = _current_ad


def _deal(att, target, amount, dtype, t, source_effect=None, is_attack=False):
    dealt = target.take(amount, dtype, t)
    if dtype == "MAGIC" and att.magic_to_true:
        dealt += target.take(amount * att.magic_to_true, "TRUE", t)
    if is_attack:
        att.heal(dealt * att.current_lifesteal())
    if source_effect:
        att.heal(dealt * source_effect.get("heal_dealt", 0))
        below = source_effect.get("heal_dealt_below")
        if below and att.hp < below["threshold"] * att.max_hp:
            att.heal(dealt * below["pct"])
    return dealt


def _on_hit_event(att, target, t, source):
    """Procesa los efectos de la pasiva al golpear. source: 'attack' o 'ability'."""
    for i, e in enumerate(att.effects):
        k = e["kind"]
        if k == "proc" and e["source"] in (source, "any"):
            att.counters[i] = att.counters.get(i, 0) + 1
            if att.counters[i] >= e["every"]:
                att.counters[i] = 0
                dmg = _effect_damage(att, e, target)
                if e.get("ap_tmaxhp"):
                    dmg += e["ap_tmaxhp"] * att.s["ap"] / 100 * target.max_hp
                _deal(att, target, dmg, e["dtype"], t, e)
                att.heal(att.v(e.get("heal_maxhp", 0)) * att.max_hp)
        elif k == "dot" and e["source"] in (source, "any"):
            apps = [x for x in att.dot_apps.get(i, []) if t - x < e["duration"]]
            if len(apps) < e["max_stacks"]:
                apps.append(t)
                _deal(att, target, _effect_damage(att, e, target), e["dtype"], t, e)
                att.heal(att.v(e.get("heal_flat", 0)))
            att.dot_apps[i] = apps
        elif k == "ramp" and e["source"] in (source, "any"):
            stacks, last = att.ramp.get(i, (0, -99))
            if t - last > e.get("duration", 5):
                stacks = 0
            stacks = min(stacks + 1, e["max_stacks"])
            att.ramp[i] = (stacks, t)
            at_max = e.get("at_max") or {}
            if stacks == e["max_stacks"] and "ad" in at_max and t > att.ad_buff_until:
                att.ad_buff, att.ad_buff_until = att.v(at_max["ad"]), t + at_max.get("lasts", 5)
        elif k == "heal" and e.get("trigger") == source and att.available(i, e, t):
            att.consume(i, e, t)
            att.heal(att.v(e.get("maxhp_pct", 0)) * att.max_hp)
        elif k == "shield" and e.get("trigger") == "on_attack" and source == "attack" and att.available(i, e, t):
            att.consume(i, e, t)
            att.shield += att._shield_amount(e)


def _auto_attack(att, target, t):
    _deal(att, target, att.current_ad() * att.auto_multiplier, "PHYSICAL", t, is_attack=True)
    for i, e in enumerate(att.effects):
        k = e["kind"]
        if k == "on_hit" and att.available(i, e, t):
            if e.get("target_below") and target.hp > e["target_below"] * target.max_hp:
                continue
            att.consume(i, e, t)
            _deal(att, target, _effect_damage(att, e, target), e["dtype"], t, e, is_attack=True)
            att.heal(att.v(e.get("heal_flat", 0)))
        elif k == "after_ability" and att.charges.get(i, 0) > 0:
            att.charges[i] -= 1
            dmg = _effect_damage(att, e, target)
            if dmg:
                _deal(att, target, dmg, e.get("dtype", "PHYSICAL"), t, e, is_attack=True)
        elif k == "ramp":
            stacks, last = att.ramp.get(i, (0, -99))
            on_hit = (e.get("at_max") or {}).get("on_hit")
            if on_hit and stacks == e["max_stacks"] and t - last <= e.get("duration", 5):
                _deal(att, target, _effect_damage(att, on_hit, target), on_hit["dtype"], t, is_attack=True)
    _on_hit_event(att, target, t, "attack")


def _cast(att, target, key, ability, rank, t):
    for i, e in enumerate(att.effects):
        if e["kind"] == "after_ability":
            att.charges[i] = min(att.charges.get(i, 0) + e["attacks"], e.get("max_charges", e["attacks"]))
        elif e["kind"] in ("shield", "heal") and e.get("trigger") == "after_ability" and att.available(i, e, t):
            att.consume(i, e, t)
            if e["kind"] == "shield":
                att.shield += att._shield_amount(e)
            else:
                att.heal(att.v(e.get("maxhp_pct", 0)) * att.max_hp)
    if not ability["has_damage"]:
        return
    dtype = "TRUE" if "TRUE" in ability["damage_type"] else "MAGIC" if "MAGIC" in ability["damage_type"] else "PHYSICAL"
    total = ability_damage(ability, rank, att.s, target.max_hp)
    if ability.get("duration", 0) > 0.3:
        att.ability_dots.append((t + ability["duration"], total / ability["duration"], dtype))
    else:
        dealt = _deal(att, target, total, dtype, t)
        att.heal(dealt * att.ability_heal)
    _on_hit_event(att, target, t, "ability")


def _tick_continuous(att, target, t):
    active = []
    for end, dps, dtype in att.ability_dots:
        if t < end:
            dealt = _deal(att, target, dps * SIM_DT, dtype, t)
            att.heal(dealt * att.ability_heal)
            active.append((end, dps, dtype))
    att.ability_dots = active
    for i, e in enumerate(att.effects):
        if e["kind"] == "ramp":
            dps = (e.get("at_max") or {}).get("dps")
            stacks, last = att.ramp.get(i, (0, -99))
            if dps and stacks == e["max_stacks"] and t - last <= e.get("duration", 5):
                _deal(att, target, _effect_damage(att, dps, target) * SIM_DT, dps["dtype"], t)
        elif e["kind"] == "regen" and not e.get("out_of_combat_only"):
            regen = att.v(e.get("maxhp_pct_per_s", 0)) * att.max_hp
            if e.get("missing_hp_flat_per_s"):
                regen += att.v(e["missing_hp_flat_per_s"]) * min(max(1 - att.hp / att.max_hp, 0) / 0.95, 1)
            att.heal(regen * SIM_DT)


def simulate(sd, champ_a, champ_b, level):
    a, b = Fighter(sd, champ_a, level), Fighter(sd, champ_b, level)
    t = 0.0
    while t <= SIM_MAX_TIME and (a.dead_at is None or b.dead_at is None):
        for att, tgt in ((a, b), (b, a)):
            att.t_now = t
            for key, ability, rank in att.loadout:
                if t >= att.next_cast[key]:
                    _cast(att, tgt, key, ability, rank, t)
                    att.next_cast[key] = t + ability_cooldown(ability, rank)
                    if ability.get("attack_lock"):
                        att.next_auto = max(att.next_auto, t + ability["attack_lock"])
            if t >= att.next_auto:
                _auto_attack(att, tgt, t)
                att.next_auto = t + 1 / att.attack_speed(t)
            _tick_continuous(att, tgt, t)
        t += SIM_DT
    return a, b


def duel(sd, champ_a, champ_b, level):
    """Probabilidad teórica de que A gane un duelo igualado a este nivel.

    Ambos luchan a la vez (curaciones, escudos y robo de vida incluidos). Se mide cuánto tarda cada
    uno en matar al otro; si uno muere antes, se le deja seguir actuando para medir su tiempo.
    """
    missing = [c for c in (champ_a, champ_b) if not sd.meraki_champ(c).get("abilities")]
    if missing:
        # Sin datos de habilidades la simulación solo tendría ataques básicos y sería engañosa:
        # se devuelve una probabilidad neutra para que manden los datos reales.
        return {"level": level, "ttk_a": None, "ttk_b": None, "p_a": 0.5, "available": False,
                "missing": missing}
    a, b = simulate(sd, champ_a, champ_b, level)
    ttk_a = (b.dead_at if b.dead_at is not None else SIM_MAX_TIME) + SIM_DT
    ttk_b = (a.dead_at if a.dead_at is not None else SIM_MAX_TIME) + SIM_DT
    p = ttk_b ** SHARPNESS / (ttk_a ** SHARPNESS + ttk_b ** SHARPNESS)
    return {"level": level, "ttk_a": round(ttk_a, 2), "ttk_b": round(ttk_b, 2), "p_a": p, "available": True}
