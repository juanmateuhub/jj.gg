"""Auditoría de habilidades y pasivas de TODOS los campeones.

Genera dos ficheros en data/:
  auditoria_habilidades.csv -> por habilidad: atributo de daño elegido, golpes y su origen
  auditoria_pasivas.csv     -> por campeón: estado de la pasiva y nota
y muestra en pantalla las habilidades que requieren revisión.

Uso:  python audit_abilities.py            -> todos los campeones
      python audit_abilities.py Garen Zed  -> solo esos campeones (sin generar CSV)
"""
import csv
import sys
from collections import Counter

from lolmatchups import config
from lolmatchups.static_data import StaticData
from lolmatchups.theory import passive_of


def main():
    sd = StaticData()
    only = [sd.resolve(c) for c in sys.argv[1:]]
    champs = only or sorted(sd.champions)
    ability_rows, passive_rows, no_data = [], [], []
    for cid in champs:
        if not sd.meraki_champ(cid).get("abilities"):
            no_data.append(cid)
            passive_rows.append({"campeon": cid, "estado": "sin_datos", "efectos": 0,
                                 "nota": "Meraki aún no tiene datos de este campeón; solo cuentan los datos reales."})
            continue
        for key, ab in sd.abilities(cid).items():
            ability_rows.append({
                "campeon": cid, "habilidad": key, "atributo": ab["attribute"] or "(sin daño)",
                "golpes": ab["hits"], "origen_golpes": ab["hits_source"], "enfriamiento_r1": ab["cooldown"][0],
                "origen_enfriamiento": ab["cooldown_source"], "bloqueo_ataques_s": ab["attack_lock"], "tipo": ab["damage_type"],
                "base_r1": ab["flat"][0], "ratio_ad_r1": ab["ad"][0], "ratio_ap_r1": ab["ap"][0],
            })
        p = passive_of(cid)
        passive_rows.append({"campeon": cid, "estado": p["status"], "efectos": len(p["effects"]), "nota": p["note"]})

    if only:
        for cid in no_data:
            print(f"{cid:>12}: sin datos en Meraki")
        for r in ability_rows:
            print(f"{r['campeon']:>12} {r['habilidad']}: {r['atributo']:<40} golpes={r['golpes']} ({r['origen_golpes']})")
        for r in passive_rows:
            print(f"{r['campeon']:>12} P: [{r['estado']}] {r['nota']}")
        return

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name, rows in (("auditoria_habilidades.csv", ability_rows), ("auditoria_pasivas.csv", passive_rows)):
        with open(config.DATA_DIR / name, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter=";")
            writer.writeheader()
            writer.writerows(rows)

    if no_data:
        print(f"Campeones sin datos en Meraki ({len(no_data)}): {', '.join(no_data)}")
        print("  -> Vuelve a ejecutar 'python main.py static' más adelante; cuando Meraki los publique,")
        print("     habrá que añadir su pasiva a lolmatchups/passives.py.\n")
    pending = [r for r in ability_rows if r["origen_golpes"] == "REVISAR"]
    print(f"Habilidades analizadas: {len(ability_rows)}")
    print("Origen del número de golpes:", dict(Counter(r["origen_golpes"] for r in ability_rows)))
    print("Estado de las pasivas:", dict(Counter(r["estado"] for r in passive_rows)))
    print(f"\nHabilidades pendientes de revisar ({len(pending)}):")
    for r in pending:
        print(f"  {r['campeon']:>12} {r['habilidad']}: {r['atributo']}")
    print(f"\nInformes completos en {config.DATA_DIR} (se abren con Excel).")


if __name__ == "__main__":
    main()
