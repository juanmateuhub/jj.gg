"""jj.gg: aplicación web (API + interfaz).

Arrancar con:   uvicorn api:app --reload
Abrir en:       http://127.0.0.1:8000
Documentación de la API: http://127.0.0.1:8000/docs
"""
import math
from collections import Counter
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from lolmatchups import config, db
from lolmatchups.analysis import Filters, default_patches, matchup_report
from lolmatchups.static_data import StaticData

WEB_DIR = Path(__file__).resolve().parent / "web"
ROLES = [("top", "Top"), ("jungle", "Jungla"), ("middle", "Medio"), ("bottom", "Tirador"), ("utility", "Apoyo")]

app = FastAPI(title="jj.gg")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
_static = None


def static():
    """Datos estáticos, cargados una sola vez (y sustituibles en las pruebas)."""
    global _static
    if _static is None:
        _static = StaticData()
    return _static


def _clean(value):
    """Convierte el informe a JSON: números de numpy, tuplas, Counter, NaN..."""
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_clean(v) for v in value]
    if hasattr(value, "item"):  # numpy
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/options")
def options():
    """Todo lo que la interfaz necesita para los selectores."""
    sd = static()
    conn = db.connect()
    try:
        patches = default_patches(conn, n=50)
        total = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        platforms = [r[0] for r in conn.execute("SELECT DISTINCT platform FROM matches ORDER BY platform")]
    finally:
        conn.close()
    champs = sorted(({"id": cid, "name": c["name"], "icon": sd.champion_icon(cid),
                      "has_theory": bool(sd.meraki_champ(cid).get("abilities"))}
                     for cid, c in sd.champions.items()), key=lambda c: c["name"])
    return {
        "champions": champs,
        "roles": [{"id": r, "name": n} for r, n in ROLES],
        "tiers": [t for t in config.TIERS if config.TIERS.index(t) >= config.TIERS.index(config.MIN_TIER)],
        "patches": patches,
        "spells": sd.spells_list(),
        "keystones": sd.keystones_list(),
        "platforms": platforms,
        "total_matches": total,
    }


@app.get("/api/matchup")
def matchup(a: str, b: str, role: str, patch: list[str] | None = Query(None),
            tier_min: str | None = None, tier_max: str | None = None, platform: list[str] | None = Query(None),
            spells_a: list[str] = Query([]), spells_b: list[str] = Query([]),
            keystone_a: str | None = None, keystone_b: str | None = None):
    sd = static()
    if role.lower() not in {r for r, _ in ROLES}:
        raise HTTPException(status_code=400, detail=f"Rol desconocido: {role}")
    for t in (tier_min, tier_max):
        if t and t.upper() not in config.TIERS:
            raise HTTPException(status_code=400, detail=f"Liga desconocida: {t}")
    try:
        f = Filters(tier_min=tier_min.upper() if tier_min else None, tier_max=tier_max.upper() if tier_max else None,
                    platforms=platform, spells_a=[sd.spell_id(s) for s in spells_a],
                    spells_b=[sd.spell_id(s) for s in spells_b],
                    keystone_a=sd.rune_id(keystone_a) if keystone_a else None,
                    keystone_b=sd.rune_id(keystone_b) if keystone_b else None)
        conn = db.connect()
        try:
            rep = matchup_report(conn, sd, a, b, role, patch, f)
        finally:
            conn.close()
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e).strip("'\""))
    rep["tiers"] = dict(Counter(rep["tiers"]))
    rep["names"] = {rep["champ_a"]: sd.champions[rep["champ_a"]]["name"],
                    rep["champ_b"]: sd.champions[rep["champ_b"]]["name"]}
    rep["art"] = {c: sd.champion_art(c) for c in (rep["champ_a"], rep["champ_b"])}
    rep["min_games"] = config.MIN_GAMES_RELIABLE
    return _clean(rep)
