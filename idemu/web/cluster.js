'use strict';
/* IDEmu – aba "Cluster e HUD" (iDrive 5/6): painel de instrumentos e HUD desenhados com os sinais do CAN virtual, o GPS virtual e o que o HMI manda
   ao Kombi e ao HUD por MOST (GET /api/cluster, idemu/cluster.py). */
(function (IDE) {
  const { h, ic, api } = IDE;
  const SVGNS = 'http://www.w3.org/2000/svg';

  /* ---- geometria ---- */
  const SWEEP = 270, START = -135;                            // ângulo em graus, no sentido horário a partir do topo
  const pol = (cx, cy, r, deg) => { const a = (deg - 90) * Math.PI / 180; return [cx + r * Math.cos(a), cy + r * Math.sin(a)]; };
  const f1 = (n) => Math.round(n * 10) / 10;
  function arc(cx, cy, r, d0, d1) {
    const [x0, y0] = pol(cx, cy, r, d0), [x1, y1] = pol(cx, cy, r, d1);
    return ['M', f1(x0), ' ', f1(y0), 'A', r, ' ', r, ' 0 ', d1 - d0 > 180 ? 1 : 0, ' 1 ', f1(x1), ' ', f1(y1)].join('');
  }
  function dial(cx, cy, r, max, major, minorPer, labelFn, redFrom) {
    let s = `<circle cx="${cx}" cy="${cy}" r="${r + 14}" fill="#05070b" stroke="#2a313d" stroke-width="3"/><circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#1b212b" stroke-width="2"/>`;
    if (redFrom != null) s += `<path d="${arc(cx, cy, r - 6, START + SWEEP * redFrom / max, START + SWEEP)}" fill="none" stroke="#d6281c" stroke-width="10"/>`;
    const n = Math.round(max / major) * minorPer;
    for (let i = 0; i <= n; i++) {
      const v = i * major / minorPer, d = START + SWEEP * v / max, big = i % minorPer === 0;
      const [x0, y0] = pol(cx, cy, r - (big ? 24 : 14), d), [x1, y1] = pol(cx, cy, r - 2, d);
      s += `<line x1="${f1(x0)}" y1="${f1(y0)}" x2="${f1(x1)}" y2="${f1(y1)}" stroke="${big ? '#f2f4f7' : '#8d96a5'}" stroke-width="${big ? 4 : 2}"/>`;
      if (big) { const [tx, ty] = pol(cx, cy, r - 50, d); s += `<text x="${f1(tx)}" y="${f1(ty + 9)}" text-anchor="middle" font-size="26" font-weight="600" fill="#e8ebf0">${labelFn(v)}</text>`; }
    }
    return s + `<g class="needle" data-needle="${cx}"><polygon points="${cx - 5},${cy + 28} ${cx + 5},${cy + 28} ${cx + 2},${cy - r + 8} ${cx - 2},${cy - r + 8}" fill="#ff5a1f"/></g><circle cx="${cx}" cy="${cy}" r="14" fill="#11151c" stroke="#ff5a1f" stroke-width="3"/>`;
  }
  const arrowPath = (kind) => ({
    left: '<path d="M0 64V0Q0 -30 -34 -30H-44" fill="none" stroke="currentColor" stroke-width="22" stroke-linecap="butt"/><polygon points="-40,-62 -86,-30 -40,2" fill="currentColor"/>',
    right: '<path d="M0 64V0Q0 -30 34 -30H44" fill="none" stroke="currentColor" stroke-width="22" stroke-linecap="butt"/><polygon points="40,-62 86,-30 40,2" fill="currentColor"/>',
    uturn: '<path d="M34 64V-12Q34 -52 0 -52Q-34 -52 -34 -12V20" fill="none" stroke="currentColor" stroke-width="22"/><polygon points="-62,16 -6,16 -34,64" fill="currentColor"/>',
    straight: '<path d="M0 64V-22" fill="none" stroke="currentColor" stroke-width="22"/><polygon points="-40,-18 40,-18 0,-70" fill="currentColor"/>',
  }[kind] || '');

  const CLUSTER_SVG = `<svg viewBox="0 0 1280 480" xmlns="${SVGNS}" role="img" aria-label="Instrument cluster" class="cl-svg">
    <rect width="1280" height="480" rx="26" fill="#020306"/>
    <rect x="3" y="3" width="1274" height="474" rx="24" fill="none" stroke="#202732" stroke-width="3"/>
    ${dial(325, 275, 185, 260, 20, 2, (v) => v)}
    ${dial(955, 275, 185, 8, 1, 2, (v) => v, 6.5)}
    <text x="325" y="446" text-anchor="middle" font-size="19" fill="#8d96a5">km/h</text>
    <text x="955" y="446" text-anchor="middle" font-size="17" fill="#8d96a5">x1000 min⁻¹</text>
    <text id="cl-speed" x="325" y="412" text-anchor="middle" font-size="64" font-weight="700" fill="#fff">0</text>
    <g id="cl-tl" fill="#34c58a"><polygon id="cl-tl-l" points="60,52 28,76 60,100" class="tell"/><polygon id="cl-tl-r" points="1220,52 1252,76 1220,100" class="tell"/></g>
    <g id="cl-pills"></g>
    <text id="cl-clock" x="640" y="130" text-anchor="middle" font-size="40" font-weight="600" fill="#f2f4f7">--:--</text>
    <text id="cl-out" x="640" y="160" text-anchor="middle" font-size="22" fill="#8d96a5">--</text>
    <text id="cl-gear" x="640" y="268" text-anchor="middle" font-size="110" font-weight="700" fill="#fff">P</text>
    <text id="cl-mode" x="640" y="304" text-anchor="middle" font-size="22" fill="#ff8a4d"></text>
    <rect x="560" y="330" width="160" height="12" rx="6" fill="#161b24"/><rect id="cl-fuel" x="560" y="330" width="80" height="12" rx="6" fill="#f2b84b"/>
    <path d="M530 331h10v14h-10zM540 335l5 3v7" fill="none" stroke="#8d96a5" stroke-width="2"/>
    <rect x="560" y="356" width="160" height="12" rx="6" fill="#161b24"/><rect id="cl-temp" x="560" y="356" width="80" height="12" rx="6" fill="#4aa8ff"/>
    <path d="M532 372v-14M537 372v-14" stroke="#8d96a5" stroke-width="2" fill="none"/><circle cx="534.5" cy="373" r="4" fill="#8d96a5"/>
    <text id="cl-range" x="640" y="410" text-anchor="middle" font-size="22" fill="#e8ebf0"></text>
    <text id="cl-odo" x="640" y="444" text-anchor="middle" font-size="22" fill="#8d96a5"></text>
  </svg>`;

  const HUD_SVG = `<svg viewBox="0 0 800 300" xmlns="${SVGNS}" role="img" aria-label="Head-up display" class="hud-svg">
    <defs><linearGradient id="hud-bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0d1218"/><stop offset="1" stop-color="#010203"/></linearGradient></defs>
    <rect width="800" height="300" rx="18" fill="url(#hud-bg)"/>
    <path d="M300 300L388 150M500 300L412 150" stroke="#16202b" stroke-width="3" fill="none"/><path d="M400 300V150" stroke="#16202b" stroke-width="2" stroke-dasharray="14 18" fill="none"/>
    <g class="hud-ink">
      <text id="hud-speed" x="190" y="170" text-anchor="middle" font-size="140" font-weight="700" fill="#a6ffd0">0</text>
      <text x="190" y="214" text-anchor="middle" font-size="26" fill="#a6ffd0" opacity=".75">km/h</text>
      <g id="hud-arrow" transform="translate(470 126)" style="color:#a6ffd0"></g>
      <text id="hud-dist" x="470" y="250" text-anchor="middle" font-size="36" font-weight="600" fill="#a6ffd0"></text>
      <text id="hud-street" x="470" y="284" text-anchor="middle" font-size="22" fill="#a6ffd0" opacity=".85"></text>
      <text id="hud-src" x="470" y="34" text-anchor="middle" font-size="15" fill="#a6ffd0" opacity=".45"></text>
      <text id="hud-gear" x="690" y="130" text-anchor="middle" font-size="84" font-weight="700" fill="#a6ffd0">P</text>
      <polygon id="hud-tl-l" points="640,205 612,225 640,245" fill="#a6ffd0" class="tell"/><polygon id="hud-tl-r" points="740,205 768,225 740,245" fill="#a6ffd0" class="tell"/>
    </g>
  </svg>`;

  const WARN = {
    belt_driver: ['Cinto', 'red'], belt_passenger: ['Cinto (passageiro)', 'red'], parking_brake: ['Freio de mão', 'red'], door: ['Porta aberta', 'red'], trunk: ['Porta-malas', 'red'], hood: ['Capô', 'red'],
    coolant_hot: ['Motor quente', 'red'], coolant_cold: ['Motor frio', 'info'], fuel_low: ['Combustível', 'amber'], tire_low: ['Pneus', 'amber'], high_beam: ['Farol alto', 'blue'], low_beam: ['Farol baixo', 'green'],
  };
  const PILL_FILL = { red: '#c4281d', amber: '#d89a1c', blue: '#2f7de1', green: '#2aa874', info: '#4a5565' };
  const GEAR = { 0: 'P', 1: 'R', 2: 'N', 3: 'D' };
  const MODE = { 0: 'Comfort', 1: 'Sport', 2: 'Eco Pro', 3: 'Sport+' };
  /* NavBridge virtual feed: the same maneuver polygons its worker sends to the HUDTerminal (worker.cpp makeArrow, 6WA-sized
     coordinates, roughly x 65..173, y 20..120), drawn around the HUD arrow anchor. */
  const NB_ARROWS = {
    STRAIGHT: [[3, [[110, 120], [130, 120], [130, 65], [151, 65], [120, 20], [89, 65], [110, 65]]]],
    LEFT: [[3, [[110, 120], [130, 120], [130, 50], [90, 50], [90, 70], [110, 70]]], [3, [[90, 38], [65, 60], [90, 82]]]],
    RIGHT: [[3, [[110, 120], [130, 120], [130, 70], [150, 70], [150, 50], [110, 50]]], [3, [[148, 38], [173, 60], [148, 82]]]],
    UTURN: [[2, [[120, 120], [137, 120], [137, 50], [111, 35], [93, 45], [93, 66], [111, 66]]], [3, [[111, 83], [83, 66], [111, 49]]]],
  };
  const nbArrow = (turn) => '<g transform="scale(1.05) translate(-120 -70)">' + (NB_ARROWS[turn] || []).map(([type, pts]) => {
    const d = pts.map((p) => p.join(',')).join(' ');
    return type === 3 ? '<polygon points="' + d + '" fill="currentColor"/>' : '<polyline points="' + d + '" fill="none" stroke="currentColor" stroke-width="12" stroke-linejoin="round"/>';
  }).join('') + '</g>';
  const km = (m) => (m >= 1000 ? IDE.fmtNum(m / 1000, m >= 10000 ? 0 : 1) + ' km' : Math.round(m / 10) * 10 + ' m');

  IDE.tabDefs.cluster = {
    mount(host) {
      let stop = null, pillKey = '', last = null;
      const clWrap = h('div', { class: 'cl-wrap' }), hudWrap = h('div', { class: 'cl-wrap hud' });
      clWrap.innerHTML = CLUSTER_SVG; hudWrap.innerHTML = HUD_SVG;
      const note = h('div', { class: 'note warn hidden' }, ic('alert', 16), h('span', { class: 'cl-note' }));
      const fsBtn = (el, label) => h('button', { class: 'btn sm', type: 'button', onclick: () => { try { el.requestFullscreen(); } catch (e) { /* sem tela cheia */ } } }, ic('expand', 14), label);
      const huList = h('pre', { class: 'logbox cl-hu' });
      const huSum = h('summary', null, 'Mensagens do HMI para o cluster e o HUD');
      const plugList = h('pre', { class: 'logbox cl-hu' });
      const plugSum = h('summary', null, 'Plugin HUD output (NavBridge, Wayglass)');
      // NavBridge virtual feed: sends a maneuver to its listener in the guest (POST /api/plugins/navbridge -> agent.sh -> navbridge-inject-qnx)
      const nbTurn = h('select', { class: 'input sm', 'aria-label': 'Turn' }, ['STRAIGHT', 'LEFT', 'RIGHT', 'UTURN'].map((t) => h('option', { value: t }, t)));
      const nbDist = h('input', { class: 'input sm num', type: 'text', value: '250', maxlength: 8, style: 'width:70px', 'aria-label': 'Distance' });
      const nbUnit = h('select', { class: 'input sm', 'aria-label': 'Unit' }, ['m', 'km', 'mi', 'ft', 'yd'].map((u) => h('option', { value: u }, u)));
      const nbStreet = h('input', { class: 'input sm', type: 'text', value: 'MAIN STREET', maxlength: 32, 'aria-label': 'Street' });
      const nbSend = (cmd, btn) => IDE.busy(btn, async () => { try { await IDE.post('/api/plugins/navbridge', { cmd }); IDE.toast('Sent to NavBridge.', 'success'); } catch (e) { IDE.toastErr(e); } });
      const nbShow = h('button', { class: 'btn sm primary', type: 'button' }, 'Show');
      nbShow.addEventListener('click', () => nbSend(['SHOW', nbTurn.value, nbDist.value.trim(), nbUnit.value, nbStreet.value.trim().toUpperCase()].join('|'), nbShow));
      const nbClear = h('button', { class: 'btn sm', type: 'button' }, 'Clear');
      nbClear.addEventListener('click', () => nbSend('CLEAR', nbClear));
      const nbBox = h('div', { class: 'uds-test' }, h('b', null, 'NavBridge'), nbTurn, nbDist, nbUnit, nbStreet, nbShow, nbClear);
      const box = h('div', { class: 'cluster' },
        h('p', { class: 'help' }, 'O cluster e o HUD mostram o carro virtual: velocidade, rotação, câmbio, luzes e alertas vêm do CAN; a posição vem do GPS. Mude os sinais na aba CAN e veja o painel reagir. A próxima curva é calculada pela rota do GPS virtual: o iDrive emulado não tem motor de navegação, então o HMI não manda manobras ao cluster.'),
        note,
        h('div', { class: 'cl-head' }, h('b', null, 'Cluster (Kombi)'), fsBtn(clWrap, 'Tela cheia')), clWrap,
        h('div', { class: 'cl-head' }, h('b', null, 'HUD'), fsBtn(hudWrap, 'Tela cheia')), hudWrap,
        h('details', { class: 'cl-det' }, huSum, huList),
        h('details', { class: 'cl-det' }, plugSum, h('p', { class: 'help' }, 'Start NavBridge in Virtual feed mode on the head unit, then send maneuvers from here. It clears itself 15 s after the last SHOW.'), nbBox, plugList));
      IDE.add(host, box);
      const $ = (id) => box.querySelector('#' + id);
      const needles = {};
      box.querySelectorAll('[data-needle]').forEach((g) => { needles[g.dataset.needle] = g; });
      const setNeedle = (cx, deg) => { const g = needles[cx]; if (g) g.setAttribute('transform', ['rotate(', f1(deg), ' ', cx, ' 275)'].join('')); };

      function drawPills(ws) {
        const key = ws.map((w) => w.id).join(',');
        if (key === pillKey) return;
        pillKey = key;
        const g = $('cl-pills'); g.textContent = '';
        ws.slice(0, 8).forEach((w, i) => {
          const [label, lvl] = WARN[w.id] || [w.id, w.level], x = 340 + (i % 4) * 150, y = 12 + Math.floor(i / 4) * 36;
          const r = document.createElementNS(SVGNS, 'rect'); r.setAttribute('x', x); r.setAttribute('y', y); r.setAttribute('width', 140); r.setAttribute('height', 28); r.setAttribute('rx', 8); r.setAttribute('fill', PILL_FILL[lvl] || PILL_FILL.info);
          const t = document.createElementNS(SVGNS, 'text'); t.setAttribute('x', x + 70); t.setAttribute('y', y + 20); t.setAttribute('text-anchor', 'middle'); t.setAttribute('font-size', 16); t.setAttribute('font-weight', 600); t.setAttribute('fill', '#fff');
          t.textContent = IDE.t(label); g.appendChild(r); g.appendChild(t);
        });
      }
      function render(d) {
        const v = d.signals || {}, on = (v.terminal_state || 0) >= 65, spd = Math.max(0, v.vehicle_speed || 0), rpm = Math.max(0, v.engine_rpm || 0);
        setNeedle(325, START + SWEEP * Math.min(spd, 260) / 260); setNeedle(955, START + SWEEP * Math.min(rpm / 1000, 8) / 8);
        $('cl-speed').textContent = Math.round(spd);
        const gear = GEAR[Math.round(v.gear_position || 0)] || '-', mode = IDE.t(MODE[Math.round(v.driving_mode || 0)] || '');
        $('cl-gear').textContent = gear; $('cl-mode').textContent = mode;
        $('cl-gear').setAttribute('fill', gear === 'R' ? '#ff6b5e' : '#fff');
        const t = new Date(); $('cl-clock').textContent = String(t.getHours()).padStart(2, '0') + ':' + String(t.getMinutes()).padStart(2, '0');
        $('cl-out').textContent = IDE.fmtNum(v.outside_temp || 0, 0) + ' °C';
        const fp = Math.max(0, Math.min(100, d.fuel_pct || 0)); $('cl-fuel').setAttribute('width', 160 * fp / 100); $('cl-fuel').setAttribute('fill', fp < 12 ? '#e5502f' : '#f2b84b');
        const ct = Math.max(40, Math.min(130, v.coolant_temp || 0)); $('cl-temp').setAttribute('width', 160 * (ct - 40) / 90); $('cl-temp').setAttribute('fill', ct >= 115 ? '#e5502f' : '#4aa8ff');
        $('cl-range').textContent = IDE.t('Autonomia {n} km', { n: d.range_km || 0 });
        $('cl-odo').textContent = IDE.fmtNum(v.odometer || 0, 0) + ' km';
        const hz = !!v.hazard, tl = hz || !!v.turn_left, tr = hz || !!v.turn_right;
        ['cl-tl-l', 'hud-tl-l'].forEach((id) => $(id).classList.toggle('on', tl)); ['cl-tl-r', 'hud-tl-r'].forEach((id) => $(id).classList.toggle('on', tr));
        drawPills(d.warnings || []);
        // HUD
        $('hud-speed').textContent = Math.round(spd); $('hud-gear').textContent = gear;
        const g = d.gps, tu = g && g.turn, arrow = $('hud-arrow'), dist = $('hud-dist'), pl = d.plugins || {}, nb = pl.navbridge;
        $('hud-street').textContent = ''; $('hud-src').textContent = '';
        if (nb && nb.status === 'SHOW') {
          arrow.innerHTML = nbArrow(String(nb.turn || '').toUpperCase());
          dist.textContent = (nb.distance || '') + ' ' + (nb.unit || '');
          $('hud-street').textContent = nb.street || ''; $('hud-src').textContent = 'NavBridge';
        } else if (tu) { arrow.innerHTML = arrowPath(tu.dir); dist.textContent = km(tu.dist_m); }
        else if (g && g.route && g.remaining_m != null) { arrow.innerHTML = arrowPath('straight'); dist.textContent = km(g.remaining_m); }
        else { arrow.innerHTML = ''; dist.textContent = ''; }
        const hu = d.hu || [];
        huList.textContent = hu.length ? hu.map((m) => m.dev + ' ' + m.name + '  op=' + m.op + '  x' + m.n + '  ' + IDE.t('há {s} s', { s: m.age }) + '  ' + m.hex).join('\n') : IDE.t('O HMI ainda não mandou nada ao cluster nem ao HUD.');
        huSum.textContent = IDE.t('Mensagens do HMI para o cluster e o HUD') + ' (' + hu.length + ')';
        const plText = [nb ? 'NavBridge state (' + IDE.t('há {s} s', { s: nb.age }) + '): ' + Object.keys(nb).filter((k) => k !== 'age').map((k) => k + '=' + nb[k]).join('  ') : null,
          pl.navbridge_log ? 'NavBridge last-run.log:' + '\n' + pl.navbridge_log : null, pl.navbridge_inject ? 'navbridge-inject:' + '\n' + pl.navbridge_inject : null, pl.wayglass_status ? 'Wayglass nbt-hud-guide.status:' + '\n' + pl.wayglass_status : null].filter(Boolean).join('\n\n');
        plugList.textContent = plText || IDE.t('No plugin has written HUD output yet.');
      }
      async function load() {
        try { last = await api('/api/cluster'); note.classList.add('hidden'); render(last); }
        catch (e) { note.classList.remove('hidden'); note.querySelector('.cl-note').textContent = IDE.t(e.message); }
      }
      return { show() { stop = IDE.loop(load, 200); }, hide() { if (stop) stop(); stop = null; }, destroy() { if (stop) stop(); } };
    },
  };
})(window.IDE);
