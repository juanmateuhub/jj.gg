"""Almacén de partidas completas comprimidas: data/raw/<servidor>/<id>.json.gz

Cada fichero contiene la partida, su timeline y los metadatos de la recogida (servidor y liga).
Gracias a esto, cualquier métrica nueva puede calcularse más adelante con:  python main.py rebuild
"""
import gzip
import json

from . import config


def path_for(platform, match_id, raw_dir=None):
    return (raw_dir or config.RAW_DIR) / platform / f"{match_id}.json.gz"


def save(platform, match_id, match, timeline, meta, raw_dir=None):
    path = path_for(platform, match_id, raw_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "match": match, "timeline": timeline}
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as f:
        json.dump(payload, f, separators=(",", ":"))
    return path.stat().st_size


def load(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def iter_all(raw_dir=None):
    base = raw_dir or config.RAW_DIR
    if not base.exists():
        return
    for path in sorted(base.glob("*/*.json.gz")):
        yield path


def disk_usage(raw_dir=None):
    files = list(iter_all(raw_dir))
    return len(files), sum(p.stat().st_size for p in files)
