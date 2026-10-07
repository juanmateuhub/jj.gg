/* jj.gg: selectores, consulta a la API y dibujo del informe. */
const $ = (id) => document.getElementById(id);
const state = { options: null, byName: new Map(), byId: new Map(), selected: { a: null, b: null }, charts: [] };
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x, d = 0) => (x == null ? "—" : `${(x * 100).toFixed(d)} %`);
const fix = (x, d = 2) => (x == null ? "—" : Number(x).toFixed(d).replace(".", ","));
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const norm = (s) => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]/g, "");

const TIER_NAMES = { GOLD: "Oro", PLATINUM: "Platino", EMERALD: "Esmeralda", DIAMOND: "Diamante", MASTER: "Maestro",
  GRANDMASTER: "Gran Maestro", CHALLENGER: "Aspirante", SILVER: "Plata", BRONZE: "Bronce", IRON: "Hierro" };
const tierName = (t) => TIER_NAMES[t] ?? t;

/* ------------------------------------------------------------------ opciones */
async function loadOptions() {
  const res = await fetch("/api/options");
  if (!res.ok) throw new Error("No se pudieron cargar los datos del juego. Ejecuta 'python main.py static' y recarga la página.");
  const o = await res.json();
  state.options = o;
  for (const c of o.champions) {
    state.byName.set(norm(c.name), c);
    state.byId.set(c.id.toLowerCase(), c);
  }
  $("roles").insertAdjacentHTML("beforeend", o.roles.map((r, i) =>
    `<label><input type="radio" name="role" value="${r.id}"${i === 0 ? " checked" : ""}>${esc(r.name)}</label>`).join(""));
  $("patch").innerHTML = `<option value="">Últimos 2 parches</option>` + o.patches.map((p) => `<option>${esc(p)}</option>`).join("");
  const SERVERS = { euw1: "Europa Oeste", eun1: "Europa Nórdica y Este", na1: "Norteamérica", kr: "Corea", jp1: "Japón",
    br1: "Brasil", la1: "Latinoamérica Norte", la2: "Latinoamérica Sur", oc1: "Oceanía", tr1: "Turquía", ru: "Rusia",
    me1: "Oriente Medio", sg2: "Sudeste Asiático", tw2: "Taiwán", vn2: "Vietnam" };
  $("platform").innerHTML = `<option value="">Todos</option>` +
    o.platforms.map((p) => `<option value="${esc(p)}">${esc(SERVERS[p] ?? p)}</option>`).join("");
  const tiers = o.tiers.map((t) => `<option value="${t}">${tierName(t)}</option>`).join("");
  $("tier-min").innerHTML = `<option value="">Cualquiera</option>${tiers}`;
  $("tier-max").innerHTML = `<option value="">Cualquiera</option>${tiers}`;
  const spells = `<option value="">Cualquiera</option>` + o.spells.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join("");
  $("spell-a").innerHTML = spells;
  $("spell-b").innerHTML = spells;
  const trees = {};
  for (const k of o.keystones) (trees[k.tree] ??= []).push(k);
  const runes = `<option value="">Cualquiera</option>` + Object.entries(trees).map(([t, list]) =>
    `<optgroup label="${esc(t)}">${list.map((k) => `<option value="${k.id}">${esc(k.name)}</option>`).join("")}</optgroup>`).join("");
  $("keystone-a").innerHTML = runes;
  $("keystone-b").innerHTML = runes;
  $("db-info").textContent = o.total_matches
    ? `${o.total_matches.toLocaleString("es-ES")} partidas analizadas en la base de datos.`
    : "Todavía no hay partidas recogidas: de momento verás la parte teórica.";
}

/* ------------------------------------------------------------------ selector de campeón con buscador */
function setupPicker(side) {
  const root = document.querySelector(`.picker[data-side="${side}"]`);
  const input = root.querySelector("input"), list = root.querySelector("ul"), icon = root.querySelector(".picker-icon");
  let items = [], active = -1;

  const close = () => { list.hidden = true; input.setAttribute("aria-expanded", "false"); active = -1; };
  const choose = (champ) => {
    state.selected[side] = champ;
    input.value = champ ? champ.name : "";
    icon.hidden = !champ?.icon;
    if (champ?.icon) icon.src = champ.icon;
    close();
  };
  const renderList = () => {
    const q = norm(input.value);
    items = state.options.champions.filter((c) => !q || norm(c.name).includes(q)).sort((x, y) =>
      (norm(y.name).startsWith(q) - norm(x.name).startsWith(q)) || x.name.localeCompare(y.name)).slice(0, 40);
    active = items.length ? 0 : -1;
    list.innerHTML = items.length
      ? items.map((c, i) => `<li role="option" id="opt-${side}-${i}" data-i="${i}" aria-selected="${i === active}">
          ${c.icon ? `<img src="${c.icon}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">` : ""}${esc(c.name)}</li>`).join("")
      : `<li class="empty-item">No hay ningún campeón con ese nombre</li>`;
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    input.setAttribute("aria-activedescendant", active >= 0 ? `opt-${side}-${active}` : "");
  };
  const move = (d) => {
    if (!items.length) return;
    active = (active + d + items.length) % items.length;
    list.querySelectorAll("li").forEach((li, i) => li.setAttribute("aria-selected", String(i === active)));
    list.children[active]?.scrollIntoView({ block: "nearest" });
    input.setAttribute("aria-activedescendant", `opt-${side}-${active}`);
  };

  input.addEventListener("focus", () => { input.select(); renderList(); });
  input.addEventListener("input", () => { state.selected[side] = null; icon.hidden = true; renderList(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); list.hidden ? renderList() : move(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
    else if (e.key === "Enter" && !list.hidden && active >= 0) { e.preventDefault(); choose(items[active]); }
    else if (e.key === "Escape") close();
  });
  list.addEventListener("mousedown", (e) => {
    const li = e.target.closest("li[data-i]");
    if (li) { e.preventDefault(); choose(items[+li.dataset.i]); }
  });
  input.addEventListener("blur", () => {
    setTimeout(close, 100);
    if (!state.selected[side]) {  // acepta el nombre escrito si coincide exactamente
      const exact = state.byName.get(norm(input.value));
      if (exact) choose(exact);
    }
  });
  return choose;
}

/* ------------------------------------------------------------------ consulta */
const role = () => document.querySelector('input[name="role"]:checked')?.value;

function readForm() {
  const { a, b } = state.selected;
  if (!a || !b) return { error: `Elige ${!a ? "tu campeón" : "el campeón rival"} de la lista.` };
  if (a.id === b.id) return { error: "Elige dos campeones distintos." };
  const params = new URLSearchParams({ a: a.id, b: b.id, role: role() });
  const add = (key, id) => { if ($(id).value) params.append(key, $(id).value); };
  add("patch", "patch"); add("platform", "platform"); add("tier_min", "tier-min"); add("tier_max", "tier-max");
  add("spells_a", "spell-a"); add("spells_b", "spell-b"); add("keystone_a", "keystone-a"); add("keystone_b", "keystone-b");
  return { params };
}

function countFilters() {
  const n = ["patch", "platform", "tier-min", "tier-max", "spell-a", "spell-b", "keystone-a", "keystone-b"].filter((id) => $(id).value).length;
  $("filters-count").hidden = !n;
  $("filters-count").textContent = n;
}

async function analyze(event) {
  event?.preventDefault();
  const { params, error } = readForm();
  showError(error);
  if (error) return;
  const btn = $("go");
  btn.disabled = true; btn.classList.add("busy"); $("progress").classList.add("run");
  try {
    const res = await fetch(`/api/matchup?${params}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "No se pudo analizar el enfrentamiento.");
    history.replaceState(null, "", `?${params}`);
    render(data);
  } catch (e) {
    showError(e.message === "Failed to fetch" ? "No hay conexión con el servidor. ¿Sigue en marcha 'uvicorn api:app'?" : e.message);
  } finally {
    btn.disabled = false; btn.classList.remove("busy"); $("progress").classList.remove("run");
  }
}

function showError(msg) {
  $("error").hidden = !msg;
  $("error").textContent = msg || "";
}

/* ------------------------------------------------------------------ informe */
const roleName = (id) => state.options.roles.find((x) => x.id === id.toLowerCase())?.name ?? id;

function render(r) {
  const A = r.champ_a, B = r.champ_b, nA = esc(r.names[A]), nB = esc(r.names[B]);
  state.charts.forEach((c) => c.destroy());
  state.charts = [];
  $("empty").hidden = true;
  const out = $("result");
  out.hidden = false;
  out.classList.remove("reveal");

  const wa = r.winrate_adjusted;
  const tiers = Object.entries(r.tiers).map(([t, n]) => `${tierName(t)} ${n}`).join(", ");
  const notices = [];
  if (!r.games) notices.push("Aún no hay partidas de este enfrentamiento con estos filtros: solo se muestra la parte teórica.");
  else if (!r.reliable) notices.push(`Solo hay ${r.games} partidas; se recomiendan al menos ${r.min_games}. Tómalo como orientativo.`);
  const missing = r.levels.find((l) => l.theory.available === false)?.theory.missing;
  if (missing) notices.push(`No hay datos de habilidades de ${missing.map((m) => esc(r.names[m] ?? m)).join(" y ")}: la parte teórica es neutra y manda el dato real.`);

  out.innerHTML = `
    <section class="arena" aria-label="Enfrentamiento">
      <div class="arena-bg"><div class="bg-a" style="background-image:url('${r.art[A].splash}')"></div><div class="bg-b" style="background-image:url('${r.art[B].splash}')"></div></div>
      <div class="fighter a">
        <div class="frame portrait"><div class="inner" style="background-image:url('${r.art[A].loading}')"></div></div>
        <div class="name">${nA}</div><div class="side">Tu campeón</div>
      </div>
      <div class="verdict">
        <div class="ring">
          <svg viewBox="0 0 200 200" aria-hidden="true">
            <circle class="frame-ring" cx="100" cy="100" r="96"/>
            <circle class="track" cx="100" cy="100" r="84"/>
            <circle class="arc" cx="100" cy="100" r="84" stroke-dasharray="0 528"/>
            <circle class="frame-ring" cx="100" cy="100" r="72"/>
          </svg>
          <div class="ring-value"><strong id="wr-number">${r.games ? "0" : "—"}</strong><span>${r.games ? "% de victorias" : "sin partidas"}</span></div>
        </div>
        <div class="caption">${r.games ? `Probabilidad estimada de que gane ${nA}, entre ${pct(wa.low)} y ${pct(wa.high)}` : "El análisis teórico está disponible más abajo"}</div>
      </div>
      <div class="fighter b">
        <div class="frame portrait"><div class="inner" style="background-image:url('${r.art[B].loading}')"></div></div>
        <div class="name">${nB}</div><div class="side">Rival</div>
      </div>
    </section>
    <p class="meta">${esc(roleName(r.role))}. Parches ${esc(r.patches.join(", "))}. ${r.games.toLocaleString("es-ES")} partidas${tiers ? ` (${esc(tiers)})` : ""}.
      ${r.games ? `Winrate bruto de ${nA}: ${pct(r.winrate_raw, 1)}.` : ""} Filtros: ${esc(r.filters)}.</p>
    ${notices.map((n) => `<p class="notice">${n}</p>`).join("")}

    <section class="section">
      <div class="section-head"><h2>Quién gana cada fase</h2><p>La barra se inclina hacia el campeón con ventaja.</p></div>
      <div class="frame"><div class="inner" id="phases">
        <div class="phase-legend"><span class="a">Ventaja de ${nA}</span><span class="b">Ventaja de ${nB}</span></div>
        ${phaseGroups(r)}
      </div></div>
    </section>

    <section class="section">
      <div class="section-head"><h2>Diferencia de oro</h2><p>Oro de ${nA} menos el de ${nB}, minuto a minuto, con su margen de error.</p></div>
      <div class="frame"><div class="inner">
        <div class="chart-box wide">${Object.keys(r.diffs).length ? `<canvas id="chart-gold" role="img" aria-label="Diferencia de oro por minuto"></canvas>` : `<p class="quiet">Hacen falta más partidas para dibujar esta curva.</p>`}</div>
        <p class="panel-sub chart-foot">Por encima de cero va por delante ${nA}; por debajo, ${nB}. Los tramos discontinuos se basan en menos de 10 partidas y son poco fiables; en los minutos finales solo cuentan las partidas que siguen en juego.</p>
      </div></div>
    </section>

    <section class="section">
      <div class="section-head"><h2>Duelos por nivel</h2><p>Probabilidad de que ${nA} gane un duelo igualado. En dorado, el modelo teórico; en azul, el resultado con partidas reales y su margen de error.</p></div>
      <div class="frame"><div class="inner">
        <div class="chart-box"><canvas id="chart-duels" role="img" aria-label="Probabilidad de ganar el duelo por nivel"></canvas></div>
      </div></div>
    </section>

    <section class="section">
      <div class="section-head"><h2>Fase de líneas</h2><p>Hasta el minuto 14. Medias por partida sobre ${r.games.toLocaleString("es-ES")} partidas.</p></div>
      <div class="frame"><div class="inner" id="lane">${laneRows(r)}</div></div>
    </section>

    <section class="section grid2">
      ${buildsPanel(r, A, "a")}
      ${buildsPanel(r, B, "b")}
    </section>

    <section class="section grid2">
      <div class="frame"><div class="inner">
        <h2 class="panel-title">Efecto del primer objeto</h2>
        <p class="panel-sub">Porcentaje de las muertes entre ambos que consigue ${nA} en cada situación.</p>
        ${itemRows(r, nA, nB)}
      </div></div>
      <div class="frame"><div class="inner">
        <h2 class="panel-title">Power spikes</h2>
        <p class="panel-sub">Momentos en los que la balanza se inclina con claridad.</p>
        ${r.spikes.length ? `<ul class="spikes">${r.spikes.map((s) => `<li>${esc(named(s, r))}</li>`).join("")}</ul>`
          : `<p class="quiet">Sin diferencias claras con los datos actuales. Aparecerán a medida que haya más partidas.</p>`}
      </div></div>
    </section>`;

  window.scrollTo({ top: 0 });
  requestAnimationFrame(() => {
    out.classList.add("reveal");
    animateBars(out);
    if (r.games) animateRing(wa.mean);
  });
  drawDuels(r);
  if (Object.keys(r.diffs).length) drawGold(r);
}

const named = (text, r) => text.replaceAll(r.champ_a, r.names[r.champ_a]).replaceAll(r.champ_b, r.names[r.champ_b]);

function animateBars(root) {
  root.querySelectorAll("[data-w]").forEach((el) => { el.style.width = el.dataset.w; });
  root.querySelectorAll(".phase-group").forEach((g) => g.classList.add("shown"));
}

function animateRing(p) {
  const arc = document.querySelector(".ring .arc"), num = $("wr-number"), C = 2 * Math.PI * 84, target = p * 100;
  arc.setAttribute("stroke-dasharray", `${(p * C).toFixed(1)} ${C.toFixed(1)}`);
  if (reduceMotion) { num.textContent = target.toFixed(0); return; }
  const t0 = performance.now(), dur = 1400;
  const step = (t) => {
    const k = Math.min((t - t0) / dur, 1), e = 1 - Math.pow(1 - k, 3);
    num.textContent = (target * e).toFixed(0);
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

/* Barra divergente: lean en [-1, 1]; negativo favorece a tu campeón (izquierda), positivo al rival. */
function phaseRow(label, lean, textA, textB, note) {
  if (lean == null) {
    return `<div class="phase nodata"><div class="phase-label">${label}</div><div class="half left"></div><div class="half right"></div><div class="phase-note">Sin datos todavía</div></div>`;
  }
  const w = `${Math.max(Math.abs(lean) * 100, 1.5).toFixed(1)}%`;
  const inside = Math.abs(lean) > 0.7 ? " inside" : "";
  const bar = (txt) => `<div class="bar" data-w="${w}"></div><span class="val${inside}" style="--w:${w}">${txt}</span>`;
  return `<div class="phase"><div class="phase-label">${label}</div>
    <div class="half left">${lean <= 0 ? bar(textA) : ""}</div><div class="half right">${lean > 0 ? bar(textB) : ""}</div>
    <div class="phase-note">${note}</div></div>`;
}

const probRow = (label, p, note) => (p == null ? phaseRow(label, null) : phaseRow(label, (0.5 - p) * 2, pct(p), pct(1 - p), note));

function phaseGroups(r) {
  const duels = r.levels.map((l) =>
    probRow(`Nivel ${l.level}`, l.combined.mean, `Teoría ${pct(l.theory.p_a)}. Reales ${l.solo_kills_a}-${l.solo_kills_b}`)).join("");
  const ranges = r.levels.map((l) => (l.range[0] === l.range[1] ? `${l.level}` : `${l.range[0]}-${l.range[1]}`)).join(", ");
  const dur = r.winrate_by_duration.map((d) => probRow(d.label.replace("<", "Menos de ").replace(">", "Más de "), d.n ? d.wr : null, `${d.n} partidas`)).join("");
  return `
    <div class="phase-group"><h3>Duelos igualados en los niveles clave</h3>
      <p class="group-note">Cada nivel combina la teoría con los kills en solitario reales entre ambos cuando tienen el mismo nivel. Tramos de niveles que agrupa cada uno: ${ranges}.</p>${duels}</div>
    <div class="phase-group"><h3>Según la duración de la partida</h3>${dur}</div>`;
}

function versusRow(label, a, b, fmt, higherIsBetter = true) {
  if (a == null || b == null) {
    return `<div class="versus-row"><span class="v a">—</span><span class="track-a"></span><span class="k">${label}</span><span class="track-b"></span><span class="v b">—</span></div>`;
  }
  const max = Math.max(a, b) || 1;
  const lead = a === b ? "" : ((a > b) === higherIsBetter ? " lead-a" : " lead-b");
  return `<div class="versus-row${lead}"><span class="v a">${fmt(a)}</span>
    <span class="track-a"><i data-w="${(a / max * 100).toFixed(1)}%"></i></span><span class="k">${label}</span>
    <span class="track-b"><i data-w="${(b / max * 100).toFixed(1)}%"></i></span><span class="v b">${fmt(b)}</span></div>`;
}

function laneRows(r) {
  const A = r.champ_a, B = r.champ_b, la = r.lane[A], lb = r.lane[B];
  return `<p class="lane-note">Solo cuentan los kills sobre el rival directo de calle. En solitario: sin ayuda de ningún aliado.
      Con ayuda: con participación de algún aliado, normalmente el jungla. Lane kill rate: porcentaje de partidas con al menos
      un kill sobre el rival, de cualquier tipo.</p>` + [
    versusRow("Lane kill rate", la.lane_kill_rate, lb.lane_kill_rate, (x) => pct(x)),
    versusRow("Kills en solitario por partida", la.solo_kills_pg, lb.solo_kills_pg, (x) => fix(x)),
    versusRow("Partidas con kill en solitario", la.solo_kill_rate, lb.solo_kill_rate, (x) => pct(x)),
    versusRow("Kills con ayuda por partida", la.assisted_kills_pg, lb.assisted_kills_pg, (x) => fix(x)),
    versusRow("Muertes con el jungla rival implicado", r.ganks[A], r.ganks[B], (x) => fix(x), false),
    versusRow("Placas de torre por partida", r.plates[A], r.plates[B], (x) => fix(x)),
    versusRow("Minuto del primer objeto", r.first_item_minute[A], r.first_item_minute[B], (x) => fix(x, 1), false),
  ].join("");
}

function itemRows(r, nA, nB) {
  const rows = [["Ninguno tiene objeto completo", r.item_spike.sin_objetos],
    [`Solo ${nA} lo tiene`, r.item_spike.solo_a_con_objeto], [`Solo ${nB} lo tiene`, r.item_spike.solo_b_con_objeto]];
  return `<table><thead><tr><th>Situación</th><th class="num">Muertes de ${nA}</th><th class="num">Casos</th></tr></thead><tbody>
    ${rows.map(([k, [s, n]]) => `<tr><td>${k}</td><td class="num">${pct(s)}</td><td class="num">${n}</td></tr>`).join("")}</tbody></table>`;
}

function buildsPanel(r, champ, side) {
  const wrClass = (w) => (w >= 0.53 ? "wr-good" : w <= 0.47 ? "wr-bad" : "");
  const rows = Object.entries(r.builds[champ]).map(([cat, list]) => `
    <tr class="build-cat"><td colspan="4">${esc(cat)}</td></tr>
    ${list.length ? list.map((e) => `<tr><td>${esc(e.label)}</td><td class="num">${pct(e.pick)}</td><td class="num ${wrClass(e.wr)}">${pct(e.wr)}</td><td class="num">${e.n}</td></tr>`).join("")
      : `<tr><td colspan="4" class="quiet">Sin datos todavía</td></tr>`}`).join("");
  return `<div class="frame builds ${side}"><div class="inner">
      <h2 class="panel-title">${esc(r.names[champ])}</h2>
      <p class="panel-sub">Configuraciones más usadas en este enfrentamiento.</p>
      <table><thead><tr><th>Opción</th><th class="num">Uso</th><th class="num">Victorias</th><th class="num">Partidas</th></tr></thead>
      <tbody>${rows}</tbody></table></div></div>`;
}

/* ------------------------------------------------------------------ gráficas */
function chartDefaults() {
  Chart.defaults.color = css("--muted");
  Chart.defaults.borderColor = "rgba(160, 155, 140, .12)";
  Chart.defaults.font.family = css("--body");
  Chart.defaults.locale = "es-ES";
  Chart.defaults.plugins.legend.labels.boxWidth = 14;
  Chart.defaults.plugins.tooltip.backgroundColor = css("--abyss");
  Chart.defaults.plugins.tooltip.borderColor = css("--gold-dim");
  Chart.defaults.plugins.tooltip.borderWidth = 1;
  Chart.defaults.plugins.tooltip.titleColor = css("--gold-hi");
  if (reduceMotion) Chart.defaults.animation = false;
}

const noBand = (item) => !item.text.startsWith("Margen");

function drawDuels(r) {
  const blue = css("--blue"), gold = css("--gold");
  state.charts.push(new Chart($("chart-duels"), {
    type: "line",
    data: {
      labels: r.levels.map((l) => `Nv ${l.level}`),
      datasets: [
        { label: "Margen superior", data: r.levels.map((l) => l.combined.high * 100), borderWidth: 0, pointRadius: 0, fill: "+1", backgroundColor: css("--blue-soft") },
        { label: "Margen inferior", data: r.levels.map((l) => l.combined.low * 100), borderWidth: 0, pointRadius: 0, fill: false },
        { label: "Con partidas reales", data: r.levels.map((l) => l.combined.mean * 100), borderColor: blue, backgroundColor: blue, borderWidth: 2.5, pointRadius: 4, pointStyle: "rectRot" },
        { label: "Teoría", data: r.levels.map((l) => l.theory.p_a * 100), borderColor: gold, backgroundColor: gold, borderDash: [5, 4], borderWidth: 1.5, pointRadius: 3, pointStyle: "rectRot" },
      ],
    },
    options: {
      maintainAspectRatio: false,
      scales: { y: { min: 0, max: 100, ticks: { stepSize: 25, callback: (v) => `${v} %` },
                     grid: { color: (c) => (c.tick.value === 50 ? css("--gold-dim") : "rgba(160,155,140,.12)") } } },
      plugins: { legend: { labels: { filter: noBand } },
                 tooltip: { filter: (c) => !c.dataset.label.startsWith("Margen"), callbacks: { label: (c) => ` ${c.dataset.label}: ${c.parsed.y.toFixed(0)} %` } } },
    },
  }));
}

const FEW_GAMES = 10;  // por debajo, el tramo de la curva se dibuja discontinuo

function drawGold(r) {
  const minutes = Object.keys(r.diffs).map(Number).sort((a, b) => a - b);
  const d = minutes.map((m) => r.diffs[m]);
  state.charts.push(new Chart($("chart-gold"), {
    type: "line",
    data: {
      labels: minutes.map((m) => `${m}`),
      datasets: [
        { label: "Margen superior", data: d.map((x) => x.gold + x.gold_ci), borderWidth: 0, pointRadius: 0, fill: "+1", backgroundColor: "rgba(200,170,110,.14)" },
        { label: "Margen inferior", data: d.map((x) => x.gold - x.gold_ci), borderWidth: 0, pointRadius: 0, fill: false },
        { label: "Diferencia de oro", data: d.map((x) => Math.round(x.gold)), borderColor: css("--gold"), backgroundColor: css("--gold"), borderWidth: 2.5, pointRadius: 3, pointHoverRadius: 6, pointStyle: "rectRot",
          segment: { borderColor: (c) => (c.p1.parsed.y >= 0 ? css("--blue") : css("--red")),
                     borderDash: (c) => (d[c.p1DataIndex].n < FEW_GAMES ? [5, 5] : undefined) } },
      ],
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { filter: noBand } },
        tooltip: {
          filter: (c) => !c.dataset.label.startsWith("Margen"),
          callbacks: {
            title: (items) => `Minuto ${items[0].label}`,
            label: (c) => ` ${c.parsed.y > 0 ? "+" : ""}${c.parsed.y.toLocaleString("es-ES")} oro para ${r.names[r.champ_a]}`,
            afterLabel: (c) => ` ${d[c.dataIndex].n} partidas`,
          },
        },
      },
      scales: {
        x: { title: { display: true, text: "Minuto" } },
        y: { title: { display: true, text: "Oro" }, grid: { color: (c) => (c.tick.value === 0 ? css("--gold-dim") : "rgba(160,155,140,.12)") } },
      },
    },
  }));
}

/* ------------------------------------------------------------------ arranque */
async function start() {
  chartDefaults();
  $("search").addEventListener("submit", analyze);
  $("filters-toggle").addEventListener("click", (e) => {
    const open = e.currentTarget.getAttribute("aria-expanded") !== "true";
    e.currentTarget.setAttribute("aria-expanded", String(open));
    $("filters").hidden = !open;
  });
  $("filters").addEventListener("change", countFilters);
  try {
    await loadOptions();
  } catch (e) {
    showError(e.message);
    return;
  }
  const choose = { a: setupPicker("a"), b: setupPicker("b") };
  const params = new URLSearchParams(location.search);
  const champ = (id) => state.byId.get((id || "").toLowerCase()) ?? null;
  if (champ(params.get("a")) && champ(params.get("b"))) {
    choose.a(champ(params.get("a")));
    choose.b(champ(params.get("b")));
    const r = document.querySelector(`input[name="role"][value="${params.get("role")}"]`);
    if (r) r.checked = true;
    const set = (id, key) => { if (params.get(key)) $(id).value = params.get(key); };
    set("patch", "patch"); set("platform", "platform"); set("tier-min", "tier_min"); set("tier-max", "tier_max");
    set("spell-a", "spells_a"); set("spell-b", "spells_b"); set("keystone-a", "keystone_a"); set("keystone-b", "keystone_b");
    countFilters();
    analyze();
  }
}
start();
