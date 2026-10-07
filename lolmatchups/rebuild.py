"""Regenera todas las tablas de análisis a partir de las partidas completas guardadas en data/raw/.

Úsalo después de añadir una métrica nueva al analizador o de actualizar los datos estáticos:
    python main.py rebuild
"""
import time

from . import db, raw_store
from .parser import parse_match


def rebuild(conn, static, raw_dir=None):
    legendary = static.legendary_item_ids()
    db.reset_derived(conn)
    ok = skipped = 0
    start = time.time()
    for i, path in enumerate(raw_store.iter_all(raw_dir), 1):
        payload = raw_store.load(path)
        parsed, _ = parse_match(payload["match"], payload["timeline"], legendary, payload.get("meta"))
        if parsed is None:
            skipped += 1
            continue
        db.save_parsed(conn, parsed, commit=False)
        ok += 1
        if i % 500 == 0:
            conn.commit()
            print(f"  {i} partidas procesadas ({time.time() - start:.0f} s)")
    conn.commit()
    return ok, skipped
