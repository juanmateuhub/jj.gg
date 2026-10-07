"""Punto de entrada por consola.  Ayuda de cada orden:  python main.py <orden> -h

  python main.py static                               descarga datos estáticos (en cada parche nuevo)
  python main.py crawl --matches 800                  recoge partidas repartidas entre ligas
  python main.py rebuild                              regenera el análisis desde las partidas guardadas
  python main.py stats                                resumen de la base de datos
  python main.py matchup Darius Garen --role top      informe del matchup (admite filtros)
"""
import argparse
import sys

from lolmatchups import config, db, raw_store
from lolmatchups.analysis import Filters, matchup_report
from lolmatchups.static_data import StaticData, download_all


def pct(x):
    return "  -  " if x is None else f"{x:5.1%}"


def print_report(rep):
    a, b = rep["champ_a"], rep["champ_b"]
    print(f"\n=== {a} vs {b} ({rep['role']}) | parches {', '.join(rep['patches'])} ===")
    print(f"Filtros: {rep['filters']}")
    tiers = ", ".join(f"{t}: {n}" for t, n in sorted(rep["tiers"].items(), key=lambda kv: config.TIERS.index(kv[0])
                                                      if kv[0] in config.TIERS else 99))
    print(f"Partidas analizadas: {rep['games']}" + (f" ({tiers})" if tiers else "")
          + ("" if rep["reliable"] else "  [MUESTRA PEQUEÑA: resultados orientativos]"))
    wa = rep["winrate_adjusted"]
    lo, hi = rep["winrate_raw_ci"]
    print(f"Winrate de {a}: bruto {pct(rep['winrate_raw'])} (IC90 {lo:.0%}-{hi:.0%}) | "
          f"ajustado {pct(wa['mean'])} (IC90 {wa['low']:.0%}-{wa['high']:.0%})")

    missing = next((L["theory"].get("missing") for L in rep["levels"] if not L["theory"].get("available", True)), None)
    if missing:
        print(f"\nAVISO: no hay datos de habilidades para {', '.join(missing)} (campeón demasiado reciente para Meraki).")
        print("       La parte teórica es neutra (50%) y el resultado depende solo de las partidas reales.")
    print("\n-- Duelos igualados por nivel (probabilidad de que gane", a + ") --")
    print(" Nivel | Teoría | TTK A / B     | Solo-kills A-B | Combinado (IC90)")
    for L in rep["levels"]:
        t, c = L["theory"], L["combined"]
        ttk = f"{t['ttk_a']:5.1f}/{t['ttk_b']:5.1f} s" if t.get("ttk_a") is not None else "  sin datos  "
        print(f"   {L['level']}   | {pct(t['p_a'])}  | {ttk} |     {L['solo_kills_a']:3d}-{L['solo_kills_b']:<3d}    | "
              f"{pct(c['mean'])} ({c['low']:.0%}-{c['high']:.0%})")


    print("\n-- Diferencias medias para", a, "--")
    if not rep["diffs"]:
        print("  Sin datos suficientes.")
    for m, d in rep["diffs"].items():
        if m % 5:
            continue
        print(f"  min {m:2d}: oro {d['gold']:+6.0f} (±{d['gold_ci']:.0f}) | xp {d['xp']:+6.0f} | "
              f"súbditos {d['cs']:+5.1f} (n={d['n']})")

    print("\n-- Fase de líneas (hasta el minuto 14, por partida) --")
    for champ in (a, b):
        ln = rep["lane"][champ]
        solo = "-" if ln["solo_kills_pg"] is None else f"{ln['solo_kills_pg']:.2f}"
        helped = "-" if ln["assisted_kills_pg"] is None else f"{ln['assisted_kills_pg']:.2f}"
        print(f"  {champ:>12}: lane kill rate {pct(ln['lane_kill_rate'])} | kills en solitario por partida {solo}"
              f" | kills con ayuda por partida {helped}")
    for champ in (a, b):
        g, pl = rep["ganks"][champ], rep["plates"][champ]
        print(f"  {champ:>12}: muertes con el jungla rival implicado {'-' if g is None else f'{g:.2f}'} | "
              f"placas conseguidas {'-' if pl is None else f'{pl:.2f}'}")

    print("\n-- Winrate de", a, "según duración --")
    for d in rep["winrate_by_duration"]:
        print(f"  {d['label']:>10}: {pct(d['wr'])} (n={d['n']})")

    print("\n-- Cuota de muertes de", a, "en la calle según nivel --")
    print(f"  Global: {pct(rep['kill_share_total'])}")
    for d in rep["kill_share_by_level"]:
        print(f"  {d['label']:>8}: {pct(d['share_a'])} (n={d['n']})")

    print("\n-- Efecto del primer objeto completo --")
    for k, (s, n) in rep["item_spike"].items():
        print(f"  {k:>18}: cuota de {a} {pct(s)} (n={n})")
    for champ, t in rep["first_item_minute"].items():
        print(f"  Minuto mediano del primer objeto de {champ}: {'-' if t is None else f'{t:.1f}'}")

    for champ, groups in rep["builds"].items():
        print(f"\n-- Configuraciones más usadas por {champ} en este matchup (uso | winrate) --")
        for title, entries in groups.items():
            if not entries:
                continue
            txt = " / ".join(f"{e['label']} ({e['pick']:.0%} | {e['wr']:.0%}, n={e['n']})" for e in entries)
            print(f"  {title}: {txt}")

    print("\n-- Power spikes detectados --")
    for note in rep["spikes"] or ["No hay diferencias significativas con los datos actuales."]:
        print("  *", note)
    print()


def print_stats(conn):
    print("Partidas por parche:")
    patch_key = lambda p: tuple(int(x) if x.isdigit() else 0 for x in p.split("."))
    rows = conn.execute("SELECT patch, COUNT(*) n FROM matches GROUP BY patch").fetchall()
    for r in sorted(rows, key=lambda r: patch_key(r["patch"])):
        print(f"  {r['patch']}: {r['n']}")
    print("Partidas por liga:")
    rows = {r["tier"]: r["n"] for r in conn.execute("SELECT tier, COUNT(*) n FROM matches GROUP BY tier")}
    for t in config.TIERS:
        if t in rows:
            print(f"  {t}: {rows[t]}")
    print("Partidas por servidor:")
    for r in conn.execute("SELECT platform, COUNT(*) n FROM matches GROUP BY platform"):
        print(f"  {r['platform']}: {r['n']}")
    n, size = raw_store.disk_usage()
    per = f" ({size / n / 1024:.0f} KB por partida)" if n else ""
    print(f"Partidas completas guardadas: {n}, {size / 1024**2:.1f} MB{per}")
    print("Jugadores en cola:", conn.execute("SELECT COUNT(*) FROM players").fetchone()[0])


def main():
    parser = argparse.ArgumentParser(description="Analizador de matchups de League of Legends")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("static", help="Descarga datos estáticos")

    c = sub.add_parser("crawl", help="Recoge partidas reales")
    c.add_argument("--matches", type=int, default=200, help="Total de partidas nuevas a recoger")
    c.add_argument("--tiers", nargs="+", default=config.DEFAULT_CRAWL_TIERS,
                   help="Ligas a recoger (por defecto de GOLD a CHALLENGER)")
    c.add_argument("--patch", action="append", help="Parche a aceptar (repetible), p. ej. --patch 16.19")
    c.add_argument("--platform", "--platforms", dest="platforms", nargs="+", default=[config.PLATFORM],
                   help="Servidor o servidores (uno por región), p. ej. --platforms euw1 na1 kr oc1")
    c.add_argument("--precise-rank", action="store_true",
                   help="Liga media real de los 10 jugadores (más preciso, pero hasta ~6 veces más lento)")
    c.add_argument("--per-player", type=int, default=20, help="Partidas revisadas por jugador")
    c.add_argument("--no-balance", action="store_true",
                   help="No repartir por igual entre ligas: cada liga aporta lo que encuentre (más rápido)")
    c.add_argument("--days", type=int, default=None,
                   help="Solo partidas de los últimos N días (por defecto 16 si se indica --patch)")

    sub.add_parser("rebuild", help="Regenera el análisis desde data/raw")
    sub.add_parser("stats", help="Resumen de la base de datos")

    m = sub.add_parser("matchup", help="Informe de un matchup")
    m.add_argument("champ_a")
    m.add_argument("champ_b")
    m.add_argument("--role", required=True, choices=["top", "jungle", "middle", "bottom", "utility"])
    m.add_argument("--patch", action="append")
    m.add_argument("--tier-min", type=str.upper, choices=config.TIERS)
    m.add_argument("--tier-max", type=str.upper, choices=config.TIERS)
    m.add_argument("--platform", action="append", help="Servidor (repetible)")
    m.add_argument("--spells-a", nargs="+", default=[], help="Hechizos que debe llevar A (p. ej. Prender Destello)")
    m.add_argument("--spells-b", nargs="+", default=[], help="Hechizos que debe llevar B")
    m.add_argument("--keystone-a", help="Runa principal de A (p. ej. Conquistador)")
    m.add_argument("--keystone-b", help="Runa principal de B")
    args = parser.parse_args()

    if args.cmd == "static":
        print("Versión descargada:", download_all())
        return
    try:
        conn = db.connect()
    except db.OldDatabaseError as e:
        sys.exit(str(e))

    if args.cmd == "crawl":
        from lolmatchups.collector import crawl_many
        try:
            results = crawl_many(args.platforms, StaticData(), args.matches, tiers=args.tiers,
                                 patches=set(args.patch) if args.patch else None, precise_rank=args.precise_rank,
                                 matches_per_player=args.per_player, balance=not args.no_balance,
                                 max_days=args.days or (16 if args.patch else None))
        except ValueError as e:
            sys.exit(str(e))
        for platform, counts in results.items():
            print(f"[{platform}] Partidas nuevas por liga:", ", ".join(f"{k}: {v}" for k, v in counts.items()))
    elif args.cmd == "rebuild":
        from lolmatchups.rebuild import rebuild
        ok, skipped = rebuild(conn, StaticData())
        print(f"Regeneradas {ok} partidas ({skipped} descartadas).")
    elif args.cmd == "stats":
        print_stats(conn)
    elif args.cmd == "matchup":
        sd = StaticData()
        try:
            f = Filters(tier_min=args.tier_min, tier_max=args.tier_max, platforms=args.platform,
                        spells_a=[sd.spell_id(s) for s in args.spells_a],
                        spells_b=[sd.spell_id(s) for s in args.spells_b],
                        keystone_a=sd.rune_id(args.keystone_a) if args.keystone_a else None,
                        keystone_b=sd.rune_id(args.keystone_b) if args.keystone_b else None)
            print_report(matchup_report(conn, sd, args.champ_a, args.champ_b, args.role, args.patch, f))
        except KeyError as e:
            sys.exit(str(e))


if __name__ == "__main__":
    main()
