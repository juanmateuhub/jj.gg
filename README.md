<p align="center">
  <img src="web/favicon.svg" width="88" alt="Emblema de jj.gg">
</p>

<h1 align="center">jj.gg</h1>

<p align="center">
  <strong>Analizador de enfrentamientos de League of Legends</strong><br>
  Quién gana cada fase de la calle, contra quién gana cada campeón y qué campeones dominan cada rol,<br>
  combinando un simulador teórico de duelos con miles de partidas reales.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white" alt="SQLite">
  <img src="https://img.shields.io/badge/Riot%20API-Match--v5-C8AA6E" alt="Riot API Match-v5">
  <img src="https://img.shields.io/badge/pruebas-19%20superadas-0AC8B9" alt="19 pruebas superadas">
</p>


---

## Índice

- [Qué es jj.gg](#qué-es-jjgg)
- [Características](#características)
- [Cómo funciona](#cómo-funciona)
- [Recolector de partidas](#recolector-de-partidas)
- [Instalación](#instalación)
- [Uso](#uso)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Pruebas](#pruebas)
- [Limitaciones conocidas](#limitaciones-conocidas)
- [Hoja de ruta](#hoja-de-ruta)
- [Aviso legal](#aviso-legal)

---

## Qué es jj.gg

La mayoría de webs de estadísticas responden a una sola pregunta: *¿qué campeón gana más?*
jj.gg va un paso más allá y analiza **cómo** se gana un enfrentamiento: quién domina los duelos
en cada nivel, cómo evoluciona el oro minuto a minuto, qué pasa en la fase de líneas y con qué
configuraciones se gana.

Para ello combina dos fuentes:

- **Un modelo teórico** que simula duelos entre campeones a partir de sus estadísticas, habilidades y pasivas.
- **Partidas reales** de jugadores de Oro a Challenger, descargadas de la Riot API y guardadas completas.

Cuando hay pocas partidas de un enfrentamiento, manda la teoría; a medida que se acumulan, mandan
los datos reales. Cada resultado se acompaña de su margen de error.

---

## Características

### Enfrentamiento

Eliges tu campeón, el rival y el rol, y obtienes un informe completo:

| Sección | Qué muestra |
|---|---|
| **Probabilidad de victoria** | Winrate ajustado del enfrentamiento con su intervalo de credibilidad. |
| **Quién gana cada fase** | Duelos igualados en los niveles clave **1, 3, 6, 9, 12, 15 y 18**, y winrate según la duración de la partida. |
| **Diferencia de oro** | Curva minuto a minuto (del 1 al 30) con margen de error; los tramos con poca muestra se marcan. |
| **Duelos por nivel** | Comparación entre la predicción teórica y el resultado con partidas reales. |
| **Fase de líneas** | Lane kill rate, kills en solitario, kills con ayuda, muertes por emboscadas del jungla, placas y minuto del primer objeto. |
| **Configuraciones** | Runas, hechizos, orden de habilidades y objetos iniciales más usados, con su winrate. |
| **Efecto del primer objeto** | Cómo cambia el reparto de kills cuando uno de los dos completa su primer objeto. |
| **Power spikes** | Detección automática de los momentos en los que el enfrentamiento se inclina con claridad. |

Se puede filtrar por **parche, servidor, liga**, y por **hechizos y runa de cada campeón**
(por ejemplo, Darius con Prender contra Garen con Teleportar).

### Counters

Eliges un campeón y su rol y ves contra quién gana y contra quién sufre: los cinco mejores y peores
enfrentamientos, y una tabla ordenable con el winrate, el oro en los minutos 10 y 15, el lane kill
rate y los duelos de los niveles 1 a 5 contra cada rival.


### Tier list

Clasificación de los campeones de cada rol en **S, A, B, C y D** según su winrate ajustado, junto
con su tasa de selección, oro en el minuto 15, lane kill rate y duelos tempranos.


### Una interfaz con identidad propia

- Estética inspirada en el cliente del juego: azul abisal, oro hextech y marcos biselados.
- Ilustraciones de pantalla de carga y *splash art* de cada campeón.
- Animaciones con propósito: los campeones entran desde cada lado, el anillo de victoria se completa
  y las barras crecen desde el eje central. Se respeta la preferencia de reducir animaciones del sistema.
- Buscador de campeones con retratos y navegación por teclado.
- Todo enlazado: de la tier list a los counters, y de los counters al enfrentamiento completo.
- Las consultas se guardan en la dirección de la página, así que se pueden guardar en favoritos o compartir.
- Diseño adaptado a móvil.

---

## Cómo funciona

### 1. Modelo teórico de duelos

Un simulador enfrenta a los dos campeones **a la vez** al mismo nivel, con un equipo inicial estándar
según su tipo de daño, y mide cuánto tarda cada uno en matar al otro. Incluye:

- **Estadísticas por nivel** con la fórmula oficial de crecimiento (Data Dragon).
- **Habilidades** leídas automáticamente de Meraki Analytics: daño base, ratios de AD y AP, % de vida
  máxima, golpes múltiples, daño repartido en el tiempo y bloqueo de ataques durante la habilidad.
- **Orden de subida estándar** hasta nivel 18, con la definitiva en los niveles 6, 11 y 16.
- **Pasivas de los 171 campeones**, clasificadas como *modelada*, *aproximada*, *sin efecto en duelo*
  o *no modelada*: daño al golpear, sangrados, acumulaciones, escudos, curaciones, robo de vida,
  regeneración, reducciones de daño y efectos que dependen de la vida perdida.
- **27 correcciones manuales** documentadas para habilidades con cargas, enfriamientos por objetivo
  o mecánicas especiales.

Un script de auditoría revisa todas las habilidades y pasivas y genera informes en CSV.

### 2. Datos reales

De cada partida se extraen, con precisión de milisegundos gracias a la *timeline*:

- El nivel exacto de cada jugador en cada muerte (eventos `LEVEL_UP`).
- Los kills entre rivales directos de calle, distinguiendo los conseguidos en solitario.
- Las muertes con participación del jungla rival.
- Las diferencias de oro, experiencia y súbditos minuto a minuto.
- Hechizos, runas, orden de habilidades, objetos iniciales (descontando compras deshechas),
  placas y primer objeto completo.

### 3. Combinación bayesiana

La teoría actúa como punto de partida (*prior*) y los duelos reales la corrigen:

- Con pocos datos (típico a nivel 1, donde hay pocas muertes) pesa más la teoría.
- Con muchos datos, mandan las partidas reales.
- Desde nivel 9 la teoría pesa menos, porque no incluye objetos.

El winrate se suaviza hacia lo esperable según el rendimiento general de cada campeón, de modo que
un 3 de 3 no aparece como un 100 %. Los enfrentamientos con poca muestra se marcan como orientativos.

---

## Recolector de partidas

El recolector descarga partidas de la Riot API y está optimizado para sacar el máximo partido a una
clave con límites de peticiones:

- **Varias regiones en paralelo.** Los límites de la Riot API se aplican por región (Europa, América,
  Asia y Sudeste Asiático/Oceanía), así que recoger en un servidor de cada una multiplica la velocidad.
- **De Oro a Challenger**, con reparto equilibrado entre ligas o sin él para ir más rápido.
- **Solo el parche que elijas**, deduciendo automáticamente cuándo empezó para no descargar partidas antiguas.
- **Partidas completas guardadas** y comprimidas (unos 75 KB cada una). Cualquier métrica nueva se
  recalcula sobre todas ellas con `python main.py rebuild`, sin volver a descargar nada.
- **Tolerante a interrupciones:** se puede detener y reanudar sin perder ni repetir partidas.
- **Diagnóstico en pantalla:** velocidad, peticiones por partida y motivos de descarte.

Con la clave de desarrollo se alcanzan del orden de **1.000 partidas por hora por región**.

---

## Instalación

### Requisitos

- Python 3.10 o superior.
- Una clave de la Riot API, gratuita en [developer.riotgames.com](https://developer.riotgames.com).

### Pasos

```bash
# 1. Clonar el repositorio
git clone https://github.com/juanmateuhub/jjgg.git
cd jjgg

# 2. Crear y activar un entorno virtual
python -m venv .venv
source .venv/Scripts/activate    # Windows (Git Bash)
# source .venv/bin/activate      # Linux y macOS

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar la clave de la Riot API
cp .env.example .env
# Edita .env y pega tu clave en RIOT_API_KEY

# 5. Descargar los datos estáticos (campeones, habilidades, objetos, runas)
python main.py static

# 6. Comprobar que todo funciona
pytest -q
```

> La clave de desarrollo caduca cada 24 horas. Cuando ocurra, genera una nueva y actualiza el `.env`.

---

## Uso

### Recoger partidas

```bash
# Recogida básica en tu servidor
python main.py crawl --matches 500

# Recogida rápida del parche actual en las cuatro regiones
python main.py crawl --matches 2000 --patch 16.19 --platforms euw1 na1 kr oc1 --per-player 100

# Solo algunas ligas
python main.py crawl --matches 600 --patch 16.19 --tiers GOLD PLATINUM EMERALD

# Resumen de la base de datos (partidas por parche, liga y servidor)
python main.py stats
```

| Opción | Descripción |
|---|---|
| `--matches` | Número de partidas nuevas a recoger. |
| `--patch` | Parche a aceptar (repetible). |
| `--platforms` | Servidores, uno por región: `euw1`, `na1`, `kr`, `oc1`... |
| `--tiers` | Ligas a recoger (por defecto, de Oro a Challenger). |
| `--no-balance` | No repartir por igual entre ligas; más rápido. |
| `--per-player` | Partidas revisadas por jugador (hasta 100). |
| `--precise-rank` | Liga media real de los 10 jugadores; más preciso pero más lento. |
| `--days` | Solo partidas de los últimos N días. |

### Aplicación web

```bash
uvicorn api:app --reload
```

Abre **http://127.0.0.1:8000**. La documentación interactiva de la API está en `/docs`.

### Consola

```bash
python main.py matchup Darius Garen --role top
python main.py matchup Darius Garen --role top --tier-min EMERALD --spells-a Prender --spells-b Teleportar
```

### Mantenimiento

```bash
python main.py static        # en cada parche nuevo
python main.py rebuild       # regenera el análisis desde las partidas guardadas
python audit_abilities.py    # auditoría de habilidades y pasivas
```

---

## Estructura del proyecto

```
jjgg/
├── api.py                  Aplicación web y API (FastAPI)
├── main.py                 Interfaz por consola
├── audit_abilities.py      Auditoría de habilidades y pasivas
├── lolmatchups/
│   ├── config.py           Parámetros: límites, ligas, niveles clave, correcciones de habilidades
│   ├── riot_client.py      Cliente de la Riot API con control de límites y reintentos
│   ├── collector.py        Recolector multirregión
│   ├── parser.py           Partida + timeline -> datos de análisis
│   ├── raw_store.py        Partidas completas comprimidas
│   ├── rebuild.py          Regeneración del análisis
│   ├── db.py               Esquema SQLite
│   ├── static_data.py      Data Dragon y Meraki Analytics
│   ├── passives.py         Tabla de pasivas de los 171 campeones
│   ├── theory.py           Simulador de duelos
│   ├── analysis.py         Análisis de enfrentamientos
│   └── overview.py         Counters y tier list
├── web/                    Interfaz (HTML, CSS y JavaScript)
└── tests/                  Pruebas automáticas
```

Los datos (`data/`) y la clave (`.env`) se excluyen del repositorio.

---

## Pruebas

```bash
pytest -q
```

El proyecto incluye pruebas con partidas simuladas que no necesitan clave ni conexión: análisis de
partidas, filtros, recolector multirregión (con una Riot API simulada), regeneración desde las partidas
guardadas, simulador de duelos y API web. Si los datos estáticos están descargados, una prueba adicional
simula los 171 campeones con los datos reales para verificar que ninguno falla.

---

## Limitaciones conocidas

- El modelo teórico no incluye control de masas, esquivar habilidades, posicionamiento ni objetos más
  allá del equipo inicial. Por eso se usa como punto de partida y no como resultado final.
- 22 pasivas no son simulables (transformaciones, resurrecciones, controles de masas); en esos campeones
  manda el dato real.
- Los campeones que Meraki Analytics aún no ha publicado reciben una probabilidad teórica neutra.
- Por defecto, la liga de cada partida es la del jugador desde el que se encontró, una aproximación
  habitual porque el emparejamiento junta a jugadores de nivel similar.
- Los resultados de un enfrentamiento concreto necesitan decenas de partidas para ser fiables.

---

## Hoja de ruta

- [ ] Calibración automática del peso del modelo teórico con los datos reales.
- [ ] Página de campeón con sus estadísticas generales por rol.
- [ ] Tendencias entre parches.
- [ ] Recogida programada y copias de seguridad automáticas.

---

## Tecnologías

**Python** · **FastAPI** · **SQLite** · **SciPy** · **Chart.js** · **Riot API (Match-v5, League-v4)** ·
**Data Dragon** · **Meraki Analytics**

---

## Aviso legal

jj.gg isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone
officially involved in producing or managing Riot Games properties. Riot Games, and all associated
properties are trademarks or registered trademarks of Riot Games, Inc.

jj.gg no está respaldado por Riot Games y no refleja las opiniones de Riot Games ni de nadie implicado
oficialmente en la producción o gestión de sus propiedades.

---

<p align="center">Desarrollado por <a href="https://github.com/juanmateuhub">Juan Mateu Museros</a></p>
