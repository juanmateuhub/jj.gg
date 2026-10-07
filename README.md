# jj.gg — analizador de enfrentamientos de League of Legends

Combina **datos teóricos** (estadísticas y habilidades) con **datos empíricos** (partidas
reales de la Riot API) para responder: quién gana a nivel 1, 2, 3..., quién llega antes a
cada nivel, cómo evoluciona la ventaja de oro y dónde están los *power spikes*.

## Cómo se garantiza la fiabilidad

1. **Datos de alto elo**: se recogen partidas de jugadores Challenger, Grandmaster y Master.
2. **Filtro por parche**: por defecto solo se analizan los 2 parches más recientes.
3. **Limpieza**: se descartan remakes, rendiciones tempranas y partidas con posiciones incompletas.
4. **Niveles exactos**: el nivel de cada jugador en cada muerte se calcula con los eventos
   `LEVEL_UP` de la timeline (precisión de milisegundos, no por minuto).
5. **Duelos limpios**: para medir la fuerza a un nivel solo cuentan las muertes *en solitario*
   entre los dos rivales de calle y *con el mismo nivel* (sin ganks que contaminen el dato).
6. **Combinación bayesiana**: el modelo teórico actúa como punto de partida y las muertes reales
   lo corrigen. Con pocos datos (típico a nivel 1, donde hay pocas muertes) pesa más la teoría;
   con muchos datos, mandan las partidas reales.
7. **Intervalos de confianza**: cada resultado va acompañado de su margen de error; los
   matchups con menos de 30 partidas se marcan como poco fiables.
8. **Winrate ajustado**: el winrate del matchup se corrige hacia lo esperable según el winrate
   general de ambos campeones, evitando conclusiones exageradas con muestras pequeñas.

## Puesta en marcha (Windows + Git Bash)

```bash
cd ~/Desktop/lol-matchups
python -m venv .venv                  # solo la primera vez
source .venv/Scripts/activate
pip install -r requirements.txt       # solo la primera vez o si cambia
pytest -q                             # comprueba que todo funciona
cp .env.example .env                  # solo la primera vez; pega tu clave en .env
python main.py static                 # en cada parche nuevo
```

## Recoger partidas

```bash
python main.py crawl --matches 800
```

La recogida se reparte por igual entre las ligas, de ORO a CHALLENGER. No se recogen partidas por
debajo de ORO IV (se puede cambiar en `MIN_TIER`, dentro de `lolmatchups/config.py`). Opciones:

```bash
python main.py crawl --matches 400 --tiers GOLD PLATINUM EMERALD   # solo esas ligas
python main.py crawl --matches 800 --patch 16.19                   # solo un parche (partidas de los últimos 16 días)
python main.py crawl --matches 800 --platform kr                   # otro servidor
python main.py crawl --matches 1000 --patch 16.19 --platforms euw1 na1 kr oc1   # 4 regiones a la vez
python main.py crawl --matches 1000 --patch 16.19 --no-balance     # sin repartir por igual entre ligas
python main.py crawl --matches 200 --precise-rank                  # liga media real de los 10 jugadores
```

Los límites de la Riot API se aplican por región de enrutado (europe, americas, asia y sea), así que
recoger a la vez en un servidor de cada región multiplica la velocidad. Usa un solo servidor por región:
euw1 y eun1, por ejemplo, comparten el límite de Europa.

Por defecto, la liga de cada partida es la del jugador desde el que se encontró (el emparejamiento
junta a jugadores de nivel similar). Con `--precise-rank` se consulta la liga de los 10 jugadores y
se usa la media: es más exacto, pero hasta 6 veces más lento al principio (la liga de cada jugador se guarda 7 días y
se reutiliza, así que se acelera con el tiempo).

Cada partida se guarda **completa y comprimida** en `data/raw/`. Si se añade una métrica nueva al
programa, se recalcula todo sin volver a descargar nada:

```bash
python main.py rebuild
```

## Analizar un matchup

```bash
python main.py matchup Darius Garen --role top
python main.py matchup Darius Garen --role top --tier-min EMERALD            # Esmeralda o superior
python main.py matchup Darius Garen --role top --tier-min GOLD --tier-max PLATINUM
python main.py matchup Darius Garen --role top --spells-a Prender --spells-b Teleportar
python main.py matchup Darius Garen --role top --keystone-a Conquistador
python main.py stats                                                          # resumen de la base de datos
```

Los hechizos y runas se pueden escribir en español o en inglés (Prender / Ignite).

El informe incluye: winrate (bruto y ajustado), duelos en los niveles clave 1, 3, 6, 9, 11, 13 y 16
(teoría + partidas), diferencias de oro/experiencia/súbditos, lane kill rate, kills en solitario,
muertes por emboscadas del jungla, placas,
winrate según duración, efecto del primer objeto, configuraciones más usadas (runas, hechizos,
orden de habilidades y objetos iniciales, con su winrate) y power spikes.

## Aplicación web

```bash
uvicorn api:app --reload
```

Abre http://127.0.0.1:8000 en el navegador. Elige tu campeón, el rival y el rol, y pulsa
**Analizar**. En **Filtros** puedes limitar por parche, liga, hechizos y runa de cada campeón.
La dirección de la página guarda la consulta, así que puedes añadirla a favoritos.
Para detener el servidor, pulsa Ctrl+C en la terminal. Puede funcionar a la vez que el recolector.

## Modelo teórico: habilidades y pasivas

El simulador enfrenta a los dos campeones a la vez, con su equipo inicial, sus habilidades
(leídas de Meraki, incluidos golpes múltiples y daño repartido en el tiempo) y sus pasivas
(tabla `lolmatchups/passives.py`, con los 171 campeones clasificados como *modelada*,
*aproximada*, *sin efecto en duelo* o *no modelada*).

Para revisar qué se está leyendo de cada campeón:

```bash
python audit_abilities.py              # genera data/auditoria_habilidades.csv y data/auditoria_pasivas.csv
python audit_abilities.py Garen Darius # detalle en pantalla de esos campeones
```

Las correcciones manuales de habilidades (golpes, enfriamientos reales, atributo de daño) están
en `ABILITY_OVERRIDES` dentro de `lolmatchups/config.py`.

## Volumen de datos necesario

Con la clave de desarrollo (100 peticiones cada 2 minutos) y 2 peticiones por partida, se
recogen unas **1.500 partidas por hora**. El recolector puede interrumpirse (Ctrl+C) y
reanudarse sin perder nada. Orientativamente:

- Winrate y diferencias de oro fiables: 30+ partidas del matchup.
- Duelos a nivel 1–3: cientos de partidas del matchup (las muertes tempranas son poco
  frecuentes; hasta entonces el resultado se apoya más en el modelo teórico).

## Estructura

```
lolmatchups/
  config.py       Parámetros (límites, filtros, pesos estadísticos)
  riot_client.py  Cliente de la API con control de límites y reintentos
  static_data.py  Data Dragon (estadísticas) + Meraki (habilidades)
  theory.py       Simulador teórico de duelos por nivel
  parser.py       Partida + timeline -> filas de matchup, muertes y diferencias
  collector.py    Recolector de partidas repartido por ligas
  raw_store.py    Partidas completas comprimidas (data/raw)
  rebuild.py      Regenera el análisis desde data/raw
  passives.py     Tabla de pasivas de los campeones
  db.py           Esquema SQLite
  analysis.py     Estadística: combinación bayesiana, intervalos, power spikes
main.py           Interfaz por consola
api.py            Aplicación web (FastAPI): uvicorn api:app --reload -> http://127.0.0.1:8000
web/              Interfaz (HTML, CSS y JavaScript; Chart.js incluido en web/vendor)
tests/            Pruebas con datos sintéticos
```

## Limitaciones conocidas

- El modelo teórico no tiene en cuenta control de masas, escudos, curaciones, pasivas ni
  runas; por eso solo se usa como punto de partida.
- La detección de "objeto completo" es aproximada (objetos de 2.200+ de oro sin mejoras).
- Riot exige, para aplicaciones públicas, registrar el producto y mostrar el aviso de que el
  proyecto no está respaldado por Riot Games.

*jj.gg isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot
Games or anyone officially involved in producing or managing Riot Games properties.*
