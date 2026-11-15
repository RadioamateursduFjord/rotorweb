/*
 * RotorWeb — carte boussole pour Home Assistant (Lovelace)
 * Version 1.7 — textes en français ou en anglais selon la langue de Home Assistant
 *
 * Installation : copier ce fichier dans /config/www/ de Home Assistant,
 * puis Paramètres → Tableaux de bord → ⋮ → Ressources → Ajouter :
 *   URL : /local/rotorweb-compass-card.js   Type : Module JavaScript
 *
 * Utilisation (YAML de la carte) :
 *   type: custom:rotorweb-compass-card
 *   # options facultatives :
 *   title: Rotor VE2ABC      # titre affiché
 *   node: rotorweb_ve2abc    # si plusieurs RotorWeb sont branchés
 *   compass_only: false      # true = seulement la boussole et l'arrêt d'urgence
 *   passes: 4                # nombre de prochains passages satellites affichés (0 = aucun)
 *
 * Les entités sont trouvées automatiquement grâce à l'attribut rotorweb_role.
 */
const RW_VERSION = "2.1";
// Textes de la carte : français ou anglais selon la langue de l'utilisateur Home Assistant
const RW_TXT = {
  fr: { rearm: "Réarmer", ovr: "Ignorer 15 min", missing: "Aucune entité RotorWeb trouvée. Active l'intégration Home Assistant dans RotorWeb (⚙ Réglages).",
    compass: "Boussole du rotor", rest: "Repos", estop: "ARRÊT D'URGENCE", operating: "En opération", block: "Bloquer port virtuel",
    wind: "Protection vent", presets: "Préréglages", pointgrid: "Pointer vers un grid", point: "Pointer", passes: "Prochains passages satellites",
    rearmq: "Réarmer le rotor ?\nVérifie que l'antenne et les alentours sont sécuritaires.",
    ovrq: (v, g) => `Vent ${v} km/h, rafales ${g} km/h.\nIgnorer le verrou vent pendant 15 minutes ?`,
    badgrid: "Grid invalide", offline: "hors ligne", conn: "Contrôleur connecté", noconn: "Contrôleur absent",
    boffline: "RotorWeb hors ligne", bestop: "ARRÊT D'URGENCE ACTIF", bnoconn: "Contrôleur non connecté", bwind: "VERROU VENT",
    bop: "EN OPÉRATION", boff: "Hors opération", to: "→ vers", nopresets: "Aucun préréglage (ajoute-les dans la page RotorWeb)",
    sched: "Horaire", dx: "Station DX", track: "Suivi", nextpass: "Prochain passage", windr: "Vent", gusts: "rafales",
    modes: ["Manuel", "Horaire", "Suivi"], W: "O" },
  en: { rearm: "Re-arm", ovr: "Override 15 min", missing: "No RotorWeb entity found. Enable the Home Assistant integration in RotorWeb (⚙ Settings).",
    compass: "Rotor compass", rest: "Rest", estop: "EMERGENCY STOP", operating: "Operating", block: "Block virtual port",
    wind: "Wind protection", presets: "Presets", pointgrid: "Point to a grid", point: "Point", passes: "Next satellite passes",
    rearmq: "Re-arm the rotor?\nCheck that the antenna and its surroundings are safe.",
    ovrq: (v, g) => `Wind ${v} km/h, gusts ${g} km/h.\nOverride the wind lock for 15 minutes?`,
    badgrid: "Invalid grid", offline: "offline", conn: "Controller connected", noconn: "Controller missing",
    boffline: "RotorWeb offline", bestop: "EMERGENCY STOP ACTIVE", bnoconn: "Controller not connected", bwind: "WIND LOCK",
    bop: "OPERATING", boff: "Not operating", to: "→ to", nopresets: "No presets (add them in the RotorWeb page)",
    sched: "Schedule", dx: "DX station", track: "Tracking", nextpass: "Next pass", windr: "Wind", gusts: "gusts",
    modes: ["Manual", "Schedule", "Tracking"], W: "W" },
};
const RW_NONE = ["Aucun", "Aucune", "None", "unknown", "unavailable", ""];

class RotorWebCompassCard extends HTMLElement {
  setConfig(config) {
    this._config = { compass_only: false, ...config };
    this._built = false;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    if (this._hass) this._render();
  }

  static getStubConfig() { return {}; }
  getCardSize() { return this._config && this._config.compass_only ? 7 : 12; }
  getGridOptions() { return { columns: 12, min_columns: 6 }; }

  set hass(hass) {
    this._hass = hass;
    const e = this._findEntities(hass);
    const sig = JSON.stringify(Object.values(e).map(id => {
      const s = hass.states[id];
      return s ? [s.state, s.attributes.options, s.attributes.friendly_name] : null;
    }));
    if (sig !== this._sig) {
      this._sig = sig;
      this._ents = e;
      this._render();
    }
  }

  _findEntities(hass) {
    const found = {};
    let node = this._config && this._config.node;
    const ids = Object.keys(hass.states).sort();
    for (const id of ids) {
      const a = hass.states[id].attributes || {};
      if (!a.rotorweb_role) continue;
      if (!node) node = a.rotorweb_node;
      if (a.rotorweb_node !== node) continue;
      found[a.rotorweb_role] = id;
    }
    this._node = node;
    return found;
  }

  _st(role) {
    const id = this._ents && this._ents[role];
    return id ? this._hass.states[id] : undefined;
  }
  _val(role) { const s = this._st(role); return s ? s.state : undefined; }
  _num(role) {
    const v = parseFloat(this._val(role));
    return Number.isFinite(v) ? v : null;
  }
  _call(domain, service, role, data = {}) {
    const id = this._ents[role];
    if (!id) return;
    this._hass.callService(domain, service, { entity_id: id, ...data });
  }

  get T() { const l = ((this._hass && this._hass.language) || "fr").toLowerCase().startsWith("en") ? "en" : "fr"; return RW_TXT[l]; }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._built) this._build();
    this._update();
  }

  _build() {
    const root = this.shadowRoot, T = this.T;
    root.innerHTML = `
      <style>${RotorWebCompassCard.styles}</style>
      <ha-card>
        <div class="head">
          <svg class="rwlogo" viewBox="0 0 100 100" aria-hidden="true"><path d="M50 50 L66.9 13.75 A40 40 0 0 1 86.25 33.1 Z" fill="#2ea043" fill-opacity=".3"/><circle cx="50" cy="50" r="40" fill="none" stroke="#388bfd" stroke-width="7"/><g transform="rotate(-45 50 50)"><path d="M50 50H84M62 38V62M76 42V58" stroke="#388bfd" stroke-width="7" stroke-linecap="round" fill="none"/></g><circle cx="50" cy="50" r="7" fill="#2ea043"/></svg>
          <div class="title"></div>
          <span class="chip status"></span>
        </div>
        <div class="banner"><span class="dot"></span><span class="btxt"></span>
          <button class="small rearm hidden">${T.rearm}</button>
          <button class="small override hidden">${T.ovr}</button>
        </div>
        <div class="missing hidden">${T.missing}</div>
        <div class="modes full">
          <button data-idx="0">${T.modes[0]}</button>
          <button data-idx="1">${T.modes[1]}</button>
          <button data-idx="2">${T.modes[2]}</button>
        </div>
        <svg class="compass" viewBox="-128 -128 256 256" role="img" aria-label="${T.compass}"></svg>
        <div class="readout"><span class="az">---</span>°<div class="sub"></div></div>
        <div class="row">
          <button class="stop">STOP</button>
          <button class="rest full">${T.rest}</button>
          <button class="estop">${T.estop}</button>
        </div>
        <div class="full">
          <div class="toggles">
            <label class="tg"><input type="checkbox" data-role="operation"><i></i><span>${T.operating}</span></label>
            <label class="tg red"><input type="checkbox" data-role="bloquer_virtuel"><i></i><span>${T.block}</span></label>
            <label class="tg"><input type="checkbox" data-role="protection_vent"><i></i><span>${T.wind}</span></label>
          </div>
          <div class="section">${T.presets}</div>
          <div class="chips"></div>
          <div class="section">${T.pointgrid}</div>
          <div class="row grid">
            <input class="gridin" placeholder="JN18du" maxlength="8" autocapitalize="characters" spellcheck="false">
            <button class="gridgo primary">${T.point}</button>
          </div>
          <div class="info"></div>
          <div class="passbox hidden"><div class="section">${T.passes}</div><table class="passes"></table></div>
        </div>
      </ha-card>`;

    // Boussole
    const svg = root.querySelector(".compass");
    let s = `<circle r="118" class="face"/><path class="beam" d="M0,0 L-42,-104 A112,112 0 0,1 42,-104 Z"/>`;
    for (let d = 0; d < 360; d += 5) {
      const a = d * Math.PI / 180, L = d % 30 === 0, r1 = L ? 100 : (d % 10 === 0 ? 106 : 110), r2 = 116;
      s += `<line class="tk${L ? " l" : ""}" x1="${(Math.sin(a) * r1).toFixed(1)}" y1="${(-Math.cos(a) * r1).toFixed(1)}" x2="${(Math.sin(a) * r2).toFixed(1)}" y2="${(-Math.cos(a) * r2).toFixed(1)}"/>`;
    }
    const card = { 0: "N", 90: "E", 180: "S", 270: T.W };
    for (let d = 0; d < 360; d += 30) {
      const a = d * Math.PI / 180, r = card[d] ? 86 : 89;
      s += `<text class="lbl${card[d] ? " cardinal" : ""}" x="${(Math.sin(a) * r).toFixed(1)}" y="${(-Math.cos(a) * r).toFixed(1)}">${card[d] || d}</text>`;
    }
    s += `<g class="target hidden"><path d="M0,-117 L-7,-127 L7,-127 Z"/></g>`;
    s += `<g class="needle"><line class="tail" x1="0" y1="0" x2="0" y2="26"/><line class="ndl" x1="0" y1="0" x2="0" y2="-96"/><circle class="hub" r="6"/></g>`;
    svg.innerHTML = s;
    svg.addEventListener("click", ev => {
      const r = svg.getBoundingClientRect();
      const x = ev.clientX - (r.left + r.width / 2), y = ev.clientY - (r.top + r.height / 2);
      const deg = Math.round((Math.atan2(x, -y) * 180 / Math.PI + 360) % 360) % 360;
      this._call("number", "set_value", "cible", { value: deg });
      this._flash(`→ ${deg}°`);
    });

    // Actions
    // Les options du mode suivent la langue de la station : on les prend dans l'entité (ordre Manuel, Horaire, Suivi)
    root.querySelectorAll(".modes button").forEach(b =>
      b.addEventListener("click", () => {
        const ms = this._st("mode"), opts = ms ? ms.attributes.options || [] : [];
        if (opts[+b.dataset.idx]) this._call("select", "select_option", "mode", { option: opts[+b.dataset.idx] });
      }));
    root.querySelector(".stop").addEventListener("click", () => this._call("button", "press", "stop"));
    root.querySelector(".rest").addEventListener("click", () => this._call("button", "press", "repos"));
    root.querySelector(".estop").addEventListener("click", () => this._call("button", "press", "arret_urgence"));
    root.querySelector(".rearm").addEventListener("click", () => {
      if (confirm(T.rearmq)) this._call("button", "press", "rearmer");
    });
    root.querySelector(".override").addEventListener("click", () => {
      const v = this._val("vent"), g = this._val("rafales");
      if (confirm(T.ovrq(v, g))) this._call("button", "press", "ignorer_vent");
    });
    root.querySelectorAll(".toggles input").forEach(cb =>
      cb.addEventListener("change", () => this._call("switch", cb.checked ? "turn_on" : "turn_off", cb.dataset.role)));
    const go = () => {
      const g = root.querySelector(".gridin").value.trim().toUpperCase();
      if (!/^[A-R]{2}[0-9]{2}([A-X]{2}([0-9]{2})?)?$/.test(g)) { this._flash(T.badgrid); return; }
      this._call("text", "set_value", "grid", { value: g });
      this._flash(`→ ${g}`);
    };
    root.querySelector(".gridgo").addEventListener("click", go);
    root.querySelector(".gridin").addEventListener("keydown", ev => { if (ev.key === "Enter") go(); });

    this._needle = null;
    this._target = null;
    this._built = true;
  }

  _flash(txt) {
    const sub = this.shadowRoot.querySelector(".sub");
    sub.textContent = txt;
    clearTimeout(this._flashT);
    this._flashT = setTimeout(() => { this._flashT = null; this._update(); }, 2500);
  }

  static _cont(prev, deg) { return prev === null ? deg : prev + ((((deg - prev) % 360) + 540) % 360 - 180); }

  _update() {
    const R = this.shadowRoot, c = this._config, T = this.T;
    const has = this._ents && this._ents.azimut;
    R.querySelector(".missing").classList.toggle("hidden", !!has);
    R.querySelectorAll(".full").forEach(el => el.classList.toggle("hidden", !!c.compass_only || !has));
    if (!has) return;

    const azS = this._st("azimut");
    const offline = azS.state === "unavailable";
    const fname = (azS.attributes.friendly_name || "RotorWeb").replace(/\s*Azimut$/i, "");
    R.querySelector(".title").textContent = c.title || fname;

    const k3ng = this._val("k3ng") === "on";
    const status = R.querySelector(".status");
    status.textContent = offline ? T.offline : (k3ng ? T.conn : T.noconn);
    status.className = "chip status " + (offline || !k3ng ? "bad" : "ok");

    // Bandeau
    const estop = this._val("urgence") === "on", wind = this._val("verrou_vent") === "on";
    const op = this._val("operation") === "on", mode = this._val("mode") || T.modes[0];
    const b = R.querySelector(".banner"), t = R.querySelector(".btxt");
    R.querySelector(".rearm").classList.toggle("hidden", !estop || offline);
    R.querySelector(".override").classList.toggle("hidden", !wind || estop || offline || !this._ents.ignorer_vent);
    if (offline) { b.className = "banner disc"; t.textContent = T.boffline; }
    else if (estop) { b.className = "banner estop"; t.textContent = T.bestop; }
    else if (!k3ng) { b.className = "banner disc"; t.textContent = T.bnoconn; }
    else if (wind) { b.className = "banner wind"; t.textContent = `${T.bwind} — ${this._val("vent")} / ${this._val("rafales")} km/h`; }
    else if (op) { b.className = "banner op"; t.textContent = `${T.bop} · ${mode}`; }
    else { b.className = "banner off"; t.textContent = T.boff; }

    // Boussole
    const az = this._num("azimut"), dest = this._num("destination");
    if (az !== null) {
      this._needle = RotorWebCompassCard._cont(this._needle, az);
      R.querySelector(".needle").style.transform = `rotate(${this._needle}deg)`;
      R.querySelector(".beam").style.transform = `rotate(${this._needle}deg)`;
    }
    const tg = R.querySelector(".target");
    if (dest !== null) {
      this._target = RotorWebCompassCard._cont(this._target, dest);
      tg.classList.remove("hidden");
      tg.style.transform = `rotate(${this._target}deg)`;
    } else tg.classList.add("hidden");
    R.querySelector(".az").textContent = az === null ? "---" : String(Math.round(az)).padStart(3, "0");
    if (!this._flashT) {
      R.querySelector(".sub").textContent = dest !== null ? `${T.to} ${Math.round(dest)}°` : " ";
    }

    // Modes
    const mst = this._st("mode"), mopts = mst ? mst.attributes.options || [] : [];
    R.querySelectorAll(".modes button").forEach(bt => {
      if (mopts[+bt.dataset.idx]) bt.textContent = mopts[+bt.dataset.idx];
      bt.classList.toggle("on", mopts.indexOf(mode) === +bt.dataset.idx);
    });

    // Interrupteurs
    R.querySelectorAll(".toggles input").forEach(cb => {
      cb.checked = this._val(cb.dataset.role) === "on";
      cb.disabled = offline;
    });

    // Préréglages
    const ps = this._st("preset");
    const opts = ps ? (ps.attributes.options || []).filter(o => o !== "—") : [];
    const chips = R.querySelector(".chips");
    const key = opts.join("|");
    if (chips.dataset.key !== key) {
      chips.dataset.key = key;
      chips.innerHTML = "";
      if (!opts.length) chips.innerHTML = `<span class="muted">${T.nopresets}</span>`;
      opts.forEach(o => {
        const btn = document.createElement("button");
        btn.className = "chipbtn";
        btn.textContent = o;
        btn.addEventListener("click", () => { this._call("select", "select_option", "preset", { option: o }); this._flash(`→ ${o}`); });
        chips.appendChild(btn);
      });
    }

    // Infos
    const rows = [];
    const plage = this._val("plage"), dx = this._val("dx"), v = this._val("vent"), g = this._val("rafales");
    const ok = x => x && !RW_NONE.includes(x);
    if (ok(plage)) rows.push([T.sched, plage]);
    if (ok(dx)) rows.push([T.dx, dx]);
    const sv = this._val("suivi"), np = this._val("prochain_passage");
    if (ok(sv)) rows.push([T.track, sv]);
    if (ok(np)) rows.push([T.nextpass, np]);
    if (ok(v)) rows.push([T.windr, `${v} km/h · ${T.gusts} ${g} km/h`]);
    R.querySelector(".info").innerHTML = rows.map(r => `<span>${r[0]}</span><div>${RotorWebCompassCard._esc(r[1])}</div>`).join("");

    // Prochains passages satellites (attribut « passes » de l'entité Prochain bon passage satellite)
    const ps2 = this._st("passage_sat"), list = ps2 && Array.isArray(ps2.attributes.passes) ? ps2.attributes.passes : [];
    const n = c.passes === undefined ? 4 : +c.passes, now = Date.now() / 1000;
    const show = list.filter(p => p.los > now).slice(0, n);
    R.querySelector(".passbox").classList.toggle("hidden", !show.length || !n);
    const hm = ts => { const d = new Date(ts * 1000); return (d.toDateString() === new Date().toDateString() ? "" : d.toLocaleDateString(undefined, { weekday: "short" }) + " ") + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); };
    R.querySelector(".passes").innerHTML = show.map(p => `<tr class="${p.aos <= now ? "now" : ""}"><td>${p.aos <= now ? "▶" : hm(p.aos)}</td><td><b>${RotorWebCompassCard._esc(p.name)}</b><br><small>${RotorWebCompassCard._esc(p.freq || "")}</small></td><td>${p.max_el}°</td></tr>`).join("");

    R.querySelectorAll("button:not(.estop):not(.stop)").forEach(bt => { bt.disabled = offline; });
  }

  static _esc(s) { return String(s).replace(/[&<>"]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch])); }
}

RotorWebCompassCard.styles = `
  :host { --rw-accent: var(--primary-color, #03a9f4); --rw-ok: var(--success-color, #43a047);
          --rw-bad: var(--error-color, #db4437); --rw-warn: var(--warning-color, #ffa600);
          --rw-line: var(--divider-color, rgba(127,127,127,.3)); --rw-muted: var(--secondary-text-color, #888); }
  ha-card { padding: 16px; }
  .hidden { display: none !important; }
  .head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
  .title { font-size: 18px; font-weight: 600; flex: 1; }
  .rwlogo { width: 26px; height: 26px; flex: none; }
  .chip { font-size: 12px; padding: 3px 10px; border-radius: 99px; border: 1px solid var(--rw-line); color: var(--rw-muted); }
  .chip.ok { color: var(--rw-ok); border-color: var(--rw-ok); } .chip.bad { color: var(--rw-bad); border-color: var(--rw-bad); }
  .banner { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 12px; font-weight: 600;
            border: 1px solid var(--rw-line); margin-bottom: 12px; font-size: 14px; }
  .banner .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--rw-muted); flex: none; }
  .banner .btxt { flex: 1; }
  .banner.op { border-color: var(--rw-ok); } .banner.op .dot { background: var(--rw-ok); box-shadow: 0 0 8px var(--rw-ok); }
  .banner.disc { border-color: var(--rw-warn); } .banner.disc .dot { background: var(--rw-warn); }
  .banner.wind, .banner.estop { border-color: var(--rw-bad); background: color-mix(in srgb, var(--rw-bad) 14%, transparent); }
  .banner.wind .dot, .banner.estop .dot { background: var(--rw-bad); }
  .banner.estop { animation: pulse 1.2s infinite; }
  @keyframes pulse { 50% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--rw-bad) 30%, transparent); } }
  .missing { color: var(--rw-muted); font-size: 14px; padding: 8px 0; }
  button { font: inherit; color: var(--primary-text-color); background: var(--secondary-background-color, rgba(127,127,127,.12));
           border: 1px solid var(--rw-line); border-radius: 10px; padding: 10px 12px; cursor: pointer; }
  button:disabled { opacity: .45; cursor: not-allowed; }
  button.small { padding: 5px 10px; font-size: 13px; }
  button.primary { background: var(--rw-accent); border-color: var(--rw-accent); color: var(--text-primary-color, #fff); font-weight: 600; }
  .modes { display: flex; gap: 4px; padding: 4px; border: 1px solid var(--rw-line); border-radius: 12px; margin-bottom: 8px; }
  .modes button { flex: 1; border: 0; background: none; font-weight: 600; color: var(--rw-muted); padding: 8px 4px; }
  .modes button.on { background: var(--rw-accent); color: var(--text-primary-color, #fff); }
  .compass { width: 100%; max-width: 320px; display: block; margin: 4px auto 0; cursor: crosshair; }
  .compass .face { fill: var(--secondary-background-color, rgba(127,127,127,.08)); stroke: var(--rw-line); stroke-width: 1.5; }
  .compass .tk { stroke: var(--rw-muted); stroke-width: .8; } .compass .tk.l { stroke: var(--primary-text-color); stroke-width: 1.6; }
  .compass .lbl { fill: var(--rw-muted); font-size: 9px; text-anchor: middle; dominant-baseline: central; }
  .compass .lbl.cardinal { fill: var(--primary-text-color); font-size: 13px; font-weight: 700; }
  .compass .ndl { stroke: var(--rw-accent); stroke-width: 4; stroke-linecap: round; }
  .compass .tail { stroke: var(--rw-muted); stroke-width: 2; stroke-linecap: round; }
  .compass .hub { fill: var(--rw-accent); } .compass .beam { fill: var(--rw-accent); opacity: .14; }
  .compass .target path { fill: var(--rw-warn); }
  .needle, .beam, .target { transition: transform .45s ease-out; }
  .readout { text-align: center; }
  .readout .az { font-size: 40px; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1.1; }
  .readout { font-size: 26px; font-weight: 700; }
  .readout .sub { font-size: 14px; font-weight: 400; color: var(--rw-muted); min-height: 1.3em; }
  .row { display: flex; gap: 8px; margin-top: 10px; }
  .row > * { flex: 1; }
  .stop { background: var(--rw-warn); border-color: var(--rw-warn); color: #111; font-weight: 700; }
  .estop { background: var(--rw-bad); border-color: var(--rw-bad); color: #fff; font-weight: 800; flex: 1.4; }
  .toggles { margin-top: 14px; border-top: 1px solid var(--rw-line); }
  .tg { display: flex; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--rw-line); cursor: pointer; }
  .tg span { flex: 1; } .tg input { display: none; }
  .tg i { position: relative; width: 44px; height: 24px; border-radius: 99px; background: var(--rw-line); flex: none; order: 2; transition: .2s; }
  .tg i:before { content: ""; position: absolute; left: 3px; top: 3px; width: 18px; height: 18px; border-radius: 50%; background: #fff; transition: .2s; }
  .tg input:checked + i { background: var(--rw-ok); } .tg.red input:checked + i { background: var(--rw-bad); }
  .tg input:checked + i:before { transform: translateX(20px); }
  .section { font-size: 12px; text-transform: uppercase; letter-spacing: .08em; color: var(--rw-muted); margin: 14px 0 6px; font-weight: 600; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chipbtn { padding: 6px 12px; border-radius: 99px; font-size: 14px; }
  .muted { color: var(--rw-muted); font-size: 13px; }
  .grid { margin-top: 0; }
  .grid input { flex: 2; font: inherit; padding: 9px 12px; border-radius: 10px; border: 1px solid var(--rw-line);
                background: transparent; color: var(--primary-text-color); text-transform: uppercase; min-width: 0; }
  .passes { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 4px; }
  .passes td { padding: 5px 4px; border-bottom: 1px solid var(--rw-line); vertical-align: top; }
  .passes td:last-child { text-align: right; font-weight: 600; }
  .passes small { color: var(--rw-muted); }
  .passes tr.now td { color: var(--rw-ok); }
  .info { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; margin-top: 14px; font-size: 14px; }
  .info span { color: var(--rw-muted); }
`;

customElements.define("rotorweb-compass-card", RotorWebCompassCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "rotorweb-compass-card",
  name: "RotorWeb — Boussole",
  description: "Contrôle du rotor : boussole, modes, arrêt d'urgence, préréglages, grid",
  preview: false,
});
console.info(`%c ROTORWEB-COMPASS-CARD %c v${RW_VERSION} `, "background:#2f81f7;color:#fff;font-weight:700", "");
