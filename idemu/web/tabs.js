'use strict';
/* IDEmu – abas da tela Execução: CAN, GPS, SSH e Logs. Cada aba: mount(host, ctx) -> {show, hide, onStatus, destroy}. */
(function (IDE) {
  const { h, ic, api, post, toast, toastErr } = IDE;
  IDE.tabDefs = {};

  const hex = (n) => (Number(n) >>> 0).toString(16).toUpperCase();
  const bytesFmt = (d) => String(d || '').replace(/\s+/g, '').replace(/(..)(?=.)/g, '$1 ');
  function debounce(fn, ms) { let t; return function () { const a = arguments; clearTimeout(t); t = setTimeout(() => fn.apply(null, a), ms); }; }
  function sub(host, defs, key, dflt) {
    const nav = h('div', { class: 'subtabs', role: 'tablist' }), panes = {};
    let cur = IDE.pref.get(key, dflt);
    if (!defs.some((d) => d[0] === cur)) cur = dflt;
    let visible = false;
    function sel(id) {
      if (panes[cur]) { panes[cur].api.hide(); panes[cur].el.hidden = true; }
      cur = id; IDE.pref.set(key, id);
      panes[id].el.hidden = false; if (visible) panes[id].api.show();
      nav.querySelectorAll('button').forEach((b) => b.classList.toggle('on', b.dataset.id === id));
    }
    defs.forEach(([id, label, make]) => {
      nav.appendChild(h('button', { type: 'button', class: 'subtab', 'data-id': id, onclick: () => sel(id) }, label));
      const el = h('div', { class: 'pane' }); el.hidden = true;
      panes[id] = { el, api: make(el) };
    });
    IDE.add(host, nav, ...defs.map((d) => panes[d[0]].el));
    sel(cur);
    return {
      show() { visible = true; panes[cur].api.show(); }, hide() { visible = false; panes[cur].api.hide(); },
      destroy() { Object.values(panes).forEach((p) => p.api.destroy && p.api.destroy()); },
      each(fn) { Object.values(panes).forEach((p) => fn(p.api)); },
    };
  }

  /* ====================================================================== CAN */
  IDE.tabDefs.can = {
    mount(host, ctx) {
      const s = sub(host, [['sig', 'Sinais', signalsPane], ['mon', 'Monitor', monitorPane], ['scn', 'Cenários', scenariosPane], ['rec', 'Gravar / injetar', recPane]], 'can.sub', 'sig');
      return { show: s.show, hide: s.hide, destroy: s.destroy, onStatus(st) { s.each((p) => p.onStatus && p.onStatus(st)); } };

      /* ---- sinais ---- */
      function signalsPane(el) {
        const rows = new Map(), lastSet = {};
        let stop = null, built = false;
        const notRun = h('div', { class: 'note warn hidden' }, ic('alert', 16), h('span', null, 'O emulador não está pronto: os sinais só podem ser alterados quando o sistema estiver em execução.'));
        const box = h('div', { class: 'sig-groups' });
        IDE.add(el, notRun, box);

        const send = (name, value) => {
          lastSet[name] = Date.now();
          api('/api/can/set', { body: { name, value } }).catch((e) => { toastErr(e); lastSet[name] = 0; });
        };
        function buildRow(sg) {
          const meta = h('div', { class: 'sg-meta' }, h('span', { class: 'sg-name' }, sg.label || sg.name),
            h('span', { class: 'sg-id mono' }, '0x' + hex(sg.can_id) + (sg.cycle_ms ? ' · ' + sg.cycle_ms + ' ms' : '')));
          let ctl, set;
          if (sg.kind === 'bool') {
            const cb = h('input', { type: 'checkbox', 'aria-label': sg.label || sg.name });
            const lab = h('span', { class: 'sw-lab' });
            cb.addEventListener('change', () => { lab.textContent = IDE.t(cb.checked ? 'Ligado' : 'Desligado'); send(sg.name, cb.checked ? 1 : 0); });
            set = (v) => { cb.checked = !!Number(v); lab.textContent = IDE.t(cb.checked ? 'Ligado' : 'Desligado'); };
            ctl = h('label', { class: 'switch' }, cb, h('span', { class: 'track' }), lab);
          } else if (sg.kind === 'enum') {
            const sel = h('select', { class: 'input sm', 'aria-label': sg.label || sg.name }, Object.keys(sg.enum || {}).map((k) => h('option', { value: k }, sg.enum[k])));
            sel.addEventListener('change', () => send(sg.name, Number(sel.value)));
            set = (v) => { sel.value = String(Math.round(Number(v))); };
            ctl = sel;
          } else {
            const step = sg.step || 1;
            const rng = h('input', { type: 'range', min: sg.min, max: sg.max, step, 'aria-label': sg.label || sg.name });
            const num = h('input', { type: 'number', class: 'input sm num', min: sg.min, max: sg.max, step });
            const dsend = debounce((v) => send(sg.name, v), 70);
            rng.addEventListener('input', () => { num.value = rng.value; lastSet[sg.name] = Date.now(); dsend(Number(rng.value)); });
            rng.addEventListener('pointerup', () => rng.blur());
            num.addEventListener('change', () => {
              let v = Number(num.value); if (isNaN(v)) return;
              v = Math.max(sg.min, Math.min(sg.max, v)); num.value = v; rng.value = v; send(sg.name, v);
            });
            set = (v) => { rng.value = v; num.value = v; };
            ctl = h('div', { class: 'sg-num' }, rng, num, h('span', { class: 'unit' }, sg.unit || ''));
          }
          set(sg.value);
          return { el: h('div', { class: 'sg-row' }, meta, ctl), set };
        }
        function build(d) {
          IDE.clear(box); rows.clear();
          (d.groups || []).forEach((g, gi) => {
            const body = h('div', { class: 'sg-list' });
            const det = h('details', { class: 'sg-group', open: IDE.pref.get('can.grp.' + g.name, true) },
              h('summary', null, ic('chevR', 14), h('span', null, g.name), h('span', { class: 'cnt' }, String((g.signals || []).length))), body);
            det.addEventListener('toggle', () => IDE.pref.set('can.grp.' + g.name, det.open));
            (g.signals || []).forEach((sg) => { const r = buildRow(sg); rows.set(sg.name, r); body.appendChild(r.el); });
            box.appendChild(det);
          });
          built = true;
        }
        async function fetchSignals() {
          const d = await api('/api/can/signals');
          notRun.classList.toggle('hidden', d.running !== false);
          if (!built) build(d);
          else (d.groups || []).forEach((g) => (g.signals || []).forEach((sg) => {
            const r = rows.get(sg.name);
            if (r && Date.now() - (lastSet[sg.name] || 0) > 1800 && !r.el.contains(document.activeElement)) r.set(sg.value);
          }));
        }
        return { show() { stop = IDE.loop(fetchSignals, 1200); }, hide() { if (stop) stop(); stop = null; }, destroy() { if (stop) stop(); } };
      }

      /* ---- monitor (candump) ---- */
      function monitorPane(el) {
        let since = null, paused = false, stop = null, total = 0;
        let buf = [], tokens = [];
        let auto = IDE.pref.get('can.auto', true);
        const list = h('div', { class: 'candump', role: 'log' });
        const count = h('span', { class: 'muted small' });
        const pauseBtn = h('button', { class: 'btn sm', type: 'button' });
        const filter = h('input', { class: 'input sm', type: 'search', placeholder: 'Filtrar por ID (ex.: 1A0, 130) ou nome', value: IDE.pref.get('can.filter', ''), 'aria-label': 'Filtrar por ID' });
        const autoCb = h('input', { type: 'checkbox', checked: auto, onchange: (e) => { auto = e.target.checked; IDE.pref.set('can.auto', auto); } });
        const clearBtn = h('button', { class: 'btn sm', type: 'button', onclick: () => { buf = []; IDE.clear(list); total = 0; upd(); } }, ic('trash', 14), 'Limpar');
        IDE.add(el, h('div', { class: 'toolbar' }, pauseBtn, clearBtn, filter, h('label', { class: 'check' }, autoCb, h('span', null, 'Rolar'))),
          h('div', { class: 'cd-head mono' }, h('span', { class: 't' }, 'tempo'), h('span', { class: 'd' }, 'dir'), h('span', { class: 'id' }, 'ID'), h('span', { class: 'l' }, '[n]'), h('span', { class: 'b' }, 'dados'), h('span', { class: 'n' }, 'sinal')),
          list, h('div', { class: 'cd-foot' }, count));
        function pauseLabel() { IDE.clear(pauseBtn); IDE.add(pauseBtn, ic(paused ? 'play' : 'pause', 14), paused ? 'Continuar' : 'Pausar'); pauseBtn.classList.toggle('warn', paused); }
        pauseBtn.addEventListener('click', () => { paused = !paused; pauseLabel(); if (!paused) since = null; if (paused) halt(); else go(); });
        const parse = () => { tokens = filter.value.split(/[\s,;]+/).filter(Boolean).map((t) => t.toUpperCase().replace(/^0X/, '')); };
        const match = (f) => !tokens.length || tokens.some((t) => String(f.id).toUpperCase().includes(t) || (f.name || '').toUpperCase().includes(t));
        const rowEl = (f) => h('div', { class: 'cf ' + (f.dir || '') },
          h('span', { class: 't', textContent: Number(f.t).toFixed(3) }), h('span', { class: 'd', textContent: f.dir || '' }), h('span', { class: 'id', textContent: String(f.id).toUpperCase() }),
          h('span', { class: 'l', textContent: '[' + f.dlc + ']' }), h('span', { class: 'b', textContent: bytesFmt(f.data) }), h('span', { class: 'n', textContent: f.name || '' }));
        function upd() { count.textContent = IDE.t('{total} quadros recebidos · {shown} exibidos', { total, shown: list.childElementCount }) + (paused ? ' · ' + IDE.t('pausado') : ''); }
        function add(frames) {
          const frag = document.createDocumentFragment();
          frames.forEach((f) => { total++; buf.push(f); if (match(f)) frag.appendChild(rowEl(f)); });
          if (buf.length > 1500) buf = buf.slice(-1000);
          list.appendChild(frag);
          while (list.childElementCount > 400) list.firstChild.remove();
          if (auto) list.scrollTop = list.scrollHeight;
          upd();
        }
        filter.addEventListener('input', debounce(() => {
          IDE.pref.set('can.filter', filter.value); parse(); IDE.clear(list);
          const frag = document.createDocumentFragment();
          buf.filter(match).slice(-400).forEach((f) => frag.appendChild(rowEl(f)));
          list.appendChild(frag); list.scrollTop = list.scrollHeight; upd();
        }, 150));
        async function poll() {
          if (since === null) { const d = await api('/api/can/frames?since=0&limit=1'); since = Math.max(0, (d.seq || 0) - 60); }
          for (let i = 0; i < 6; i++) {
            const d = await api('/api/can/frames?' + IDE.qs({ since, limit: 200 }));
            if (typeof d.seq === 'number' && d.seq < since) { since = Math.max(0, d.seq - 60); break; }
            const fr = d.frames || [];
            if (!fr.length) break;
            since = fr[fr.length - 1].seq; add(fr);
            if (fr.length < 200) break;
          }
        }
        function go() { if (!stop && !paused) stop = IDE.loop(poll, 350); }
        function halt() { if (stop) stop(); stop = null; upd(); }
        pauseLabel(); parse(); upd();
        return { show: go, hide: halt, destroy: halt };
      }

      /* ---- cenários ---- */
      function scenariosPane(el) {
        let stop = null, active = null;
        const box = h('div', { class: 'scn-list' });
        IDE.add(el, h('p', { class: 'help' }, 'Cenários geram sinais de CAN automaticamente (velocidade, rotação, marcha…). Só um fica ativo por vez.'), box);
        async function load() {
          const d = await api('/api/can/scenarios');
          active = d.active || null;
          IDE.clear(box);
          (d.scenarios || []).forEach((sc) => {
            const on = active === sc.id;
            const b = h('button', { class: 'btn sm ' + (on ? 'danger-o' : 'primary-o'), type: 'button' }, ic(on ? 'stop' : 'play', 14), on ? 'Parar' : 'Iniciar');
            b.addEventListener('click', () => IDE.busy(b, async () => {
              try { await post('/api/can/scenario', { id: on ? null : sc.id }); await load(); } catch (e) { toastErr(e); }
            }));
            box.appendChild(h('div', { class: 'scn' + (on ? ' on' : '') }, h('div', { class: 'scn-t' }, h('b', null, sc.name), on ? IDE.badge('Ativo', 'live') : null, h('div', { class: 'muted small' }, sc.desc || '')), b));
          });
          if (!(d.scenarios || []).length) box.appendChild(h('div', { class: 'placeholder' }, 'Nenhum cenário disponível.'));
        }
        return { show() { stop = IDE.loop(load, 2500); }, hide() { if (stop) stop(); stop = null; }, destroy() { if (stop) stop(); } };
      }

      /* ---- gravar / reproduzir / injetar ---- */
      function recPane(el) {
        let recording = false, stop = null;
        const recBtn = h('button', { class: 'btn', type: 'button' });
        const list = h('div', { class: 'rec-list' });
        const loopCb = h('input', { type: 'checkbox' });
        function recLabel() { IDE.clear(recBtn); IDE.add(recBtn, ic(recording ? 'stop' : 'record', 14), recording ? 'Parar gravação' : 'Gravar tráfego'); recBtn.classList.toggle('danger-o', recording); }
        recBtn.addEventListener('click', () => IDE.busy(recBtn, async () => {
          try {
            await post('/api/can/record', { on: !recording }); recording = !recording; recLabel();
            toast(recording ? 'Gravando o tráfego CAN…' : 'Gravação finalizada.', recording ? 'info' : 'success'); await load();
          } catch (e) { toastErr(e); }
        }));
        async function load() {
          const d = await api('/api/can/recordings');
          if (d && typeof d.recording === 'boolean') { recording = d.recording; recLabel(); }
          const arr = Array.isArray(d) ? d : (d.recordings || d.files || []);
          IDE.clear(list);
          if (!arr.length) list.appendChild(h('div', { class: 'placeholder' }, 'Nenhuma gravação ainda.'));
          arr.forEach((r) => {
            const file = typeof r === 'string' ? r : (r.file || r.name);
            const b = h('button', { class: 'btn sm', type: 'button' }, ic('play', 14), 'Reproduzir');
            b.addEventListener('click', () => IDE.busy(b, async () => {
              try { await post('/api/can/replay', { file, loop: loopCb.checked }); toast(IDE.t('Reproduzindo {file}.', { file }), 'info'); } catch (e) { toastErr(e); }
            }));
            list.appendChild(h('div', { class: 'rec-row' }, ic('file', 16), h('div', { class: 'rec-t' }, h('span', { class: 'mono' }, file),
              typeof r === 'object' ? h('span', { class: 'muted small' }, [r.frames != null ? IDE.t('{n} quadros', { n: r.frames }) : null, r.size != null ? IDE.fmtSize(r.size) : null, r.created ? IDE.fmtDate(r.created) : null].filter(Boolean).join(' · ')) : null), b));
          });
        }
        // injeção de quadro bruto
        const idIn = h('input', { class: 'input mono', type: 'text', placeholder: '1A0', maxlength: 8, 'aria-label': 'ID do quadro (hex)' });
        const dataIn = h('input', { class: 'input mono', type: 'text', placeholder: '00 11 22 33 44 55 66 77', 'aria-label': 'Dados (hex)' });
        const extCb = h('input', { type: 'checkbox' });
        const msg = h('div', { class: 'ferr' });
        const sendBtn = h('button', { class: 'btn primary', type: 'button' }, ic('send', 14), 'Enviar quadro');
        sendBtn.addEventListener('click', async () => {
          const id = idIn.value.trim().replace(/^0x/i, ''), data = dataIn.value.replace(/\s+/g, '');
          let err = '';
          if (!/^[0-9a-fA-F]{1,8}$/.test(id)) err = 'ID inválido: use de 1 a 8 dígitos hexadecimais.';
          else if (!extCb.checked && parseInt(id, 16) > 0x7FF) err = 'ID acima de 7FF: marque "Quadro estendido (29 bits)".';
          else if (data && !/^[0-9a-fA-F]*$/.test(data)) err = 'Os dados devem ser hexadecimais (0–9, A–F).';
          else if (data.length % 2) err = 'Informe os dados em bytes completos (número par de dígitos).';
          else if (data.length > 16) err = 'No máximo 8 bytes (16 dígitos hex).';
          msg.textContent = IDE.t(err); if (err) return;
          await IDE.busy(sendBtn, async () => {
            try { await post('/api/can/frame', { id: id.toUpperCase(), data: data.toUpperCase(), ext: extCb.checked }); toast(IDE.t('Quadro {id} enviado.', { id: id.toUpperCase() }), 'success'); } catch (e) { toastErr(e); }
          });
        });
        IDE.add(el,
          h('fieldset', null, h('legend', null, 'Gravação'),
            h('div', { class: 'row' }, recBtn, h('label', { class: 'check' }, loopCb, h('span', null, 'Repetir ao reproduzir'))), list),
          h('fieldset', null, h('legend', null, 'Injetar quadro bruto'),
            h('div', { class: 'inject' },
              h('div', { class: 'field' }, h('label', { class: 'lbl' }, 'ID (hex)'), idIn),
              h('div', { class: 'field grow' }, h('label', { class: 'lbl' }, 'Dados (hex, até 8 bytes)'), dataIn)),
            h('div', { class: 'row between' }, h('label', { class: 'check' }, extCb, h('span', null, 'Quadro estendido (29 bits)')), sendBtn), msg));
        recLabel();
        return { show() { stop = IDE.loop(load, 4000); }, hide() { if (stop) stop(); stop = null; }, destroy() { if (stop) stop(); } };
      }
    },
  };

  /* ====================================================================== GPS */
  IDE.tabDefs.gps = {
    mount(host) {
      const KM = 111320;
      const S = { st: null, follow: IDE.pref.get('gps.follow', true), mpp: IDE.pref.get('gps.mpp', 2), clat: null, clon: null, trail: [], route: null, ghost: null };
      let stop = null, W = 300, Hh = 300, dpr = 1, visible = false;
      const MODES = [['static', 'Parado'], ['route', 'Rota'], ['circle', 'Círculo'], ['manual', 'Manual']];

      const canvas = h('canvas', { class: 'gps-canvas', 'aria-label': 'Mapa simples do GPS' });
      const hud = h('div', { class: 'gps-hud mono' });
      const followBtn = h('button', { class: 'btn sm', type: 'button', title: 'Manter o carro no centro', onclick: () => { S.follow = !S.follow; IDE.pref.set('gps.follow', S.follow); if (S.follow) centerCar(); sync(); draw(); } }, ic('target', 14), 'Seguir');
      const fitBtn = h('button', { class: 'btn sm', type: 'button', title: 'Enquadrar a rota', onclick: fitRoute }, ic('layers', 14), 'Rota');
      const zin = h('button', { class: 'btn sm icon', type: 'button', title: 'Aproximar', onclick: () => zoom(1 / 1.4) }, ic('plus', 14));
      const zout = h('button', { class: 'btn sm icon', type: 'button', title: 'Afastar', onclick: () => zoom(1.4) }, ic('minus', 14));
      const mapBox = h('div', { class: 'gps-map' }, canvas, h('div', { class: 'gps-tools' }, followBtn, fitBtn, zin, zout),
        );
      const mapHint = h('div', { class: 'gps-hint muted small' }, 'Clique no mapa para teletransportar o carro · arraste para mover a vista · roda do mouse para zoom');

      /* ---- controles ---- */
      const modeBtns = {};
      const radiusIn = h('input', { class: 'input sm', type: 'number', min: 20, max: 20000, value: 300, 'aria-label': 'Raio do círculo (m)', style: { width: '84px' } });
      const modeRow = h('div', { class: 'seg' }, MODES.map(([m, l]) => (modeBtns[m] = h('button', { type: 'button', class: 'segb', onclick: () => setMode(m) }, l))));
      const fields = {};
      const FIELDS = [['lat', 'Latitude', '°', 'any'], ['lon', 'Longitude', '°', 'any'], ['alt', 'Altitude', 'm', 'any'], ['speed_kmh', 'Velocidade', 'km/h', 'any'], ['heading', 'Rumo', '°', 'any'], ['sats', 'Satélites', '', '1']];
      const applyBtn = h('button', { class: 'btn primary sm', type: 'button', disabled: true }, ic('check', 14), 'Aplicar');
      const grid = h('div', { class: 'gps-fields' }, FIELDS.map(([k, l, u, step]) => {
        const inp = h('input', { class: 'input sm mono', type: 'number', step, 'aria-label': l });
        inp.addEventListener('input', () => { inp.dataset.dirty = '1'; applyBtn.disabled = false; });
        inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') applyFields(); });
        fields[k] = inp;
        return h('div', { class: 'field' }, h('label', { class: 'lbl' }, IDE.t(l) + (u ? ' (' + u + ')' : '')), inp);
      }));
      const fixCb = h('input', { type: 'checkbox', onchange: () => post('/api/gps/set', { fix: fixCb.checked }).catch(toastErr) });
      const syncCb = h('input', { type: 'checkbox', onchange: () => post('/api/gps/set', { sync_can_speed: syncCb.checked }).catch(toastErr) });
      const hdopEl = h('span', { class: 'muted small mono' });
      applyBtn.addEventListener('click', applyFields);
      const routeInfo = h('div', { class: 'route-info' });
      const gpxIn = h('input', { type: 'file', accept: '.gpx,.xml,application/gpx+xml,text/xml', hidden: true });
      gpxIn.addEventListener('change', () => { const f = gpxIn.files && gpxIn.files[0]; gpxIn.value = ''; if (f) importGpx(f); });
      const nmea = h('pre', { class: 'nmea mono' });
      IDE.add(host, mapBox, h('div', { class: 'gps-meta' }, hud, mapHint),
        h('div', { class: 'gps-ctl' },
          h('div', { class: 'row between wrap' }, h('div', { class: 'lbl' }, 'Modo'), h('label', { class: 'check small' }, 'Raio', radiusIn, 'm')),
          modeRow, grid,
          h('div', { class: 'row between wrap' },
            h('div', { class: 'row' }, h('label', { class: 'check' }, fixCb, h('span', null, 'Sinal GPS (fix)')), h('label', { class: 'check' }, syncCb, h('span', null, 'Velocidade → CAN')), hdopEl),
            applyBtn),
          h('div', { class: 'lbl' }, 'Rota'),
          h('div', { class: 'row' }, h('button', { class: 'btn', type: 'button', onclick: () => gpxIn.click() }, ic('upload', 16), 'Importar rota GPX…'), gpxIn),
          routeInfo,
          h('div', { class: 'lbl' }, 'Últimas sentenças NMEA'), nmea));

      async function setMode(m) {
        try { const body = { mode: m }; if (m === 'circle') body.radius_m = Number(radiusIn.value) || 300; await post('/api/gps/mode', body); await poll(); } catch (e) { toastErr(e); }
      }
      async function applyFields() {
        const body = {};
        for (const k of Object.keys(fields)) {
          if (fields[k].dataset.dirty !== '1') continue;
          const v = fields[k].value;
          if (v === '' || isNaN(Number(v))) { toast(IDE.t('Valor inválido em "{k}".', { k }), 'error'); return; }
          body[k] = k === 'sats' ? parseInt(v, 10) : Number(v);
        }
        if (!Object.keys(body).length) return;
        if (body.lat != null && (body.lat < -90 || body.lat > 90)) return toast('Latitude deve estar entre -90 e 90.', 'error');
        if (body.lon != null && (body.lon < -180 || body.lon > 180)) return toast('Longitude deve estar entre -180 e 180.', 'error');
        try { await post('/api/gps/set', body); Object.values(fields).forEach((f) => { f.dataset.dirty = ''; }); applyBtn.disabled = true; if (body.lat != null || body.lon != null) S.trail = []; await poll(); if (body.lat != null || body.lon != null) { centerCar(); draw(); } } catch (e) { toastErr(e); }
      }
      function parseGpx(text) {
        const doc = new DOMParser().parseFromString(text, 'application/xml');
        if (doc.querySelector('parsererror')) return null;
        let nodes = doc.getElementsByTagName('trkpt');
        if (!nodes.length) nodes = doc.getElementsByTagName('rtept');
        if (!nodes.length) nodes = doc.getElementsByTagName('wpt');
        const pts = [];
        for (const n of nodes) { const la = parseFloat(n.getAttribute('lat')), lo = parseFloat(n.getAttribute('lon')); if (isFinite(la) && isFinite(lo)) pts.push([la, lo]); }
        return pts;
      }
      async function importGpx(file) {
        if (file.size > 20 * 1024 * 1024) return toast('Arquivo GPX muito grande (máx. 20 MB).', 'error');
        let text;
        try { text = await file.text(); } catch (e) { return toast('Não foi possível ler o arquivo.', 'error'); }
        const pts = parseGpx(text);
        if (!pts) return toast('O arquivo não é um GPX/XML válido.', 'error');
        if (pts.length < 2) return toast('O GPX precisa ter ao menos 2 pontos (trkpt, rtept ou wpt).', 'error');
        const name = file.name.replace(/\.[^.]+$/, '');
        try {
          await post('/api/gps/route', { name, gpx: text });
          S.route = { name, pts }; toast(IDE.t('Rota "{name}" importada: {n} pontos.', { name, n: pts.length }), 'success');
          fitRoute(); await poll();
        } catch (e) { toastErr(e); }
      }

      /* ---- projeção / desenho ---- */
      const cosLat = () => Math.cos((S.clat || 0) * Math.PI / 180);
      const toXY = (lat, lon) => [W / 2 + (lon - S.clon) * KM * cosLat() / S.mpp, Hh / 2 - (lat - S.clat) * KM / S.mpp];
      const toLL = (x, y) => [S.clat - (y - Hh / 2) * S.mpp / KM, S.clon + (x - W / 2) * S.mpp / (KM * cosLat())];
      function centerCar() { if (S.st) { S.clat = S.st.lat; S.clon = S.st.lon; } }
      function routePts() { const r = S.st && S.st.route; const sv = r && (r.coords || r.pts || r.points_xy); return Array.isArray(sv) ? sv : (S.route ? S.route.pts : null); }
      function fitRoute() {
        const pts = routePts();
        if (!pts || !pts.length) { toast('Importe uma rota GPX para enquadrá-la.', 'info'); return; }
        let a = 90, b = -90, c = 180, d = -180;
        pts.forEach((p) => { a = Math.min(a, p[0]); b = Math.max(b, p[0]); c = Math.min(c, p[1]); d = Math.max(d, p[1]); });
        S.clat = (a + b) / 2; S.clon = (c + d) / 2;
        const spanY = Math.max(20, (b - a) * KM), spanX = Math.max(20, (d - c) * KM * Math.cos(S.clat * Math.PI / 180));
        S.mpp = Math.max(spanX / (W * 0.82), spanY / (Hh * 0.82)); IDE.pref.set('gps.mpp', S.mpp);
        S.follow = false; IDE.pref.set('gps.follow', false); sync(); draw();
      }
      function zoom(f, mx, my) {
        if (S.clat == null) return;
        mx = mx == null ? W / 2 : mx; my = my == null ? Hh / 2 : my;
        const before = toLL(mx, my);
        S.mpp = Math.max(0.05, Math.min(20000, S.mpp * f));
        if (!S.follow) { const after = toLL(mx, my); S.clat += before[0] - after[0]; S.clon += before[1] - after[1]; }
        IDE.pref.set('gps.mpp', S.mpp); draw();
      }
      function sync() { followBtn.classList.toggle('on', S.follow); }
      function resize() {
        const r = canvas.getBoundingClientRect(); if (!r.width) return;
        dpr = window.devicePixelRatio || 1; W = r.width; Hh = r.height;
        canvas.width = Math.round(W * dpr); canvas.height = Math.round(Hh * dpr); draw();
      }
      const NICE = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000, 1000000];
      function draw() {
        if (!visible) return;
        const g = canvas.getContext('2d'); if (!g) return;
        g.setTransform(dpr, 0, 0, dpr, 0, 0);
        g.fillStyle = '#0a0e15'; g.fillRect(0, 0, W, Hh);
        if (S.clat == null) { g.fillStyle = '#6b7890'; g.font = '13px system-ui,sans-serif'; g.textAlign = 'center'; g.fillText(IDE.t('Aguardando posição do GPS…'), W / 2, Hh / 2); return; }
        const cl = cosLat();
        // grade
        const stepM = NICE.find((n) => n / S.mpp >= 64) || 1000000;
        const dLat = stepM / KM, dLon = stepM / (KM * cl);
        const tl = toLL(0, 0), br = toLL(W, Hh);
        const dec = (d) => Math.min(6, Math.max(2, Math.ceil(-Math.log10(d)) + 0));
        g.lineWidth = 1; g.font = '10px ui-monospace,Menlo,monospace';
        g.strokeStyle = '#18202e'; g.fillStyle = '#56627a'; g.textAlign = 'left';
        for (let la = Math.ceil(br[0] / dLat) * dLat; la <= tl[0]; la += dLat) {
          const y = Math.round(toXY(la, S.clon)[1]) + 0.5;
          g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke(); g.fillText(la.toFixed(dec(dLat)) + '°', 4, y - 3);
        }
        g.textAlign = 'center';
        for (let lo = Math.ceil(tl[1] / dLon) * dLon; lo <= br[1]; lo += dLon) {
          const x = Math.round(toXY(S.clat, lo)[0]) + 0.5;
          g.beginPath(); g.moveTo(x, 0); g.lineTo(x, Hh); g.stroke(); g.fillText(lo.toFixed(dec(dLon)) + '°', x, Hh - 4);
        }
        // rota
        const pts = routePts();
        if (pts && pts.length > 1) {
          g.strokeStyle = '#2f8cff'; g.lineWidth = 3; g.lineJoin = 'round'; g.globalAlpha = 0.85; g.beginPath();
          pts.forEach((p, i) => { const [x, y] = toXY(p[0], p[1]); if (i) g.lineTo(x, y); else g.moveTo(x, y); }); g.stroke(); g.globalAlpha = 1;
          const dot = (p, col) => { const [x, y] = toXY(p[0], p[1]); g.fillStyle = col; g.beginPath(); g.arc(x, y, 5, 0, 7); g.fill(); g.strokeStyle = '#0a0e15'; g.lineWidth = 2; g.stroke(); };
          dot(pts[0], '#34c58a'); dot(pts[pts.length - 1], '#ef5b5b');
        }
        // rastro
        if (S.trail.length > 1) {
          g.strokeStyle = 'rgba(240,180,64,.7)'; g.lineWidth = 2; g.beginPath();
          S.trail.forEach((p, i) => { const [x, y] = toXY(p[0], p[1]); if (i) g.lineTo(x, y); else g.moveTo(x, y); }); g.stroke();
        }
        // fantasma do clique
        if (S.ghost && Date.now() - S.ghost.t < 1500) {
          const [x, y] = toXY(S.ghost.lat, S.ghost.lon); g.strokeStyle = 'rgba(255,255,255,.7)'; g.lineWidth = 1.5; g.beginPath(); g.arc(x, y, 9, 0, 7); g.stroke();
        }
        // carro
        if (S.st) {
          const [x, y] = toXY(S.st.lat, S.st.lon);
          g.save(); g.translate(x, y); g.rotate((S.st.heading || 0) * Math.PI / 180);
          g.fillStyle = S.st.fix === false ? '#7a8499' : '#3dd68c'; g.strokeStyle = '#06080c'; g.lineWidth = 2;
          g.beginPath(); g.moveTo(0, -13); g.lineTo(9, 10); g.lineTo(0, 5); g.lineTo(-9, 10); g.closePath(); g.fill(); g.stroke(); g.restore();
        }
        // escala
        const barPx = stepM / S.mpp; g.strokeStyle = '#c7d0e0'; g.fillStyle = '#c7d0e0'; g.lineWidth = 2; g.textAlign = 'left'; g.font = '11px system-ui,sans-serif';
        g.beginPath(); g.moveTo(10, Hh - 22); g.lineTo(10 + barPx, Hh - 22); g.moveTo(10, Hh - 26); g.lineTo(10, Hh - 18); g.moveTo(10 + barPx, Hh - 26); g.lineTo(10 + barPx, Hh - 18); g.stroke();
        g.fillText(stepM >= 1000 ? (stepM / 1000) + ' km' : stepM + ' m', 14, Hh - 28);
      }
      /* interação */
      let pd = null;
      canvas.addEventListener('pointerdown', (e) => { if (e.button !== 0) return; canvas.setPointerCapture(e.pointerId); pd = { x: e.clientX, y: e.clientY, lx: e.clientX, ly: e.clientY, moved: false }; });
      canvas.addEventListener('pointermove', (e) => {
        if (!pd || S.clat == null) return;
        if (!pd.moved && Math.hypot(e.clientX - pd.x, e.clientY - pd.y) > 5) { pd.moved = true; if (S.follow) { S.follow = false; IDE.pref.set('gps.follow', false); sync(); } }
        if (pd.moved) { S.clat += (e.clientY - pd.ly) * S.mpp / KM; S.clon -= (e.clientX - pd.lx) * S.mpp / (KM * cosLat()); draw(); }
        pd.lx = e.clientX; pd.ly = e.clientY;
      });
      canvas.addEventListener('pointerup', async (e) => {
        const d = pd; pd = null;
        if (!d || d.moved || S.clat == null) return;
        const r = canvas.getBoundingClientRect(); const [lat, lon] = toLL(e.clientX - r.left, e.clientY - r.top);
        S.ghost = { lat, lon, t: Date.now() }; S.trail = []; draw();
        try { await post('/api/gps/jump', { lat, lon }); await poll(); } catch (er) { toastErr(er); }
      });
      canvas.addEventListener('pointercancel', () => { pd = null; });
      canvas.addEventListener('wheel', (e) => { e.preventDefault(); const r = canvas.getBoundingClientRect(); zoom(e.deltaY > 0 ? 1.18 : 1 / 1.18, e.clientX - r.left, e.clientY - r.top); }, { passive: false });
      let ro = null;
      if (window.ResizeObserver) { ro = new ResizeObserver(() => resize()); ro.observe(canvas); }

      /* ---- atualização ---- */
      function applyState(st) {
        const prev = S.st; S.st = st;
        if (S.clat == null || S.follow) centerCar();
        if (prev && Math.hypot((st.lat - prev.lat) * KM, (st.lon - prev.lon) * KM) > 150) S.trail = [];
        const last = S.trail[S.trail.length - 1];
        if (!last || Math.hypot((st.lat - last[0]) * KM, (st.lon - last[1]) * KM * cosLat()) > 1.5) { S.trail.push([st.lat, st.lon]); if (S.trail.length > 500) S.trail.shift(); }
        Object.keys(modeBtns).forEach((m) => modeBtns[m].classList.toggle('on', st.mode === m));
        for (const k of Object.keys(fields)) {
          const f = fields[k];
          if (f.dataset.dirty === '1' || document.activeElement === f) continue;
          const v = st[k]; f.value = v == null ? '' : (k === 'lat' || k === 'lon' ? Number(v).toFixed(6) : v);
        }
        if (document.activeElement !== fixCb) fixCb.checked = st.fix !== false;
        syncCb.checked = !!st.sync_can_speed;
        hdopEl.textContent = st.hdop != null ? 'HDOP ' + IDE.fmtNum(st.hdop, 1) : '';
        hud.textContent = (st.fix === false ? IDE.t('SEM FIX') : 'FIX') + ' · ' + IDE.fmtNum(st.speed_kmh, 0) + ' km/h · ' + IDE.fmtNum(st.heading, 0) + '° · ' + (st.sats != null ? st.sats + ' sat' : '');
        hud.classList.toggle('bad', st.fix === false);
        // rota
        IDE.clear(routeInfo);
        if (st.route) {
          const p = Math.round((st.route.progress || 0) * 100);
          IDE.add(routeInfo, h('div', { class: 'ri-top' }, ic('pin', 14), h('b', { textContent: st.route.name || IDE.t('rota') }), h('span', { class: 'muted small' }, (st.route.points != null ? IDE.t('{n} pontos', { n: st.route.points }) : '') + (st.route.length_km != null ? ' · ' + IDE.fmtNum(st.route.length_km, 1) + ' km' : ''))),
            h('div', { class: 'bar' }, h('i', { style: { width: p + '%' } })),
            !routePts() ? h('div', { class: 'muted small' }, 'A rota está carregada no servidor, mas o traçado só aparece quando ela é importada por esta tela.') : null);
        } else IDE.add(routeInfo, h('div', { class: 'muted small' }, 'Nenhuma rota carregada. Importe um arquivo GPX e use o modo "Rota".'));
        nmea.textContent = (st.nmea_tail || []).join('\n') || IDE.t('(sem dados NMEA)');
        draw();
      }
      async function poll() { applyState(await api('/api/gps/state')); }
      sync();
      return {
        show() { visible = true; resize(); if (!stop) stop = IDE.loop(poll, 500); },
        hide() { visible = false; if (stop) stop(); stop = null; },
        destroy() { if (stop) stop(); if (ro) ro.disconnect(); },
      };
    },
  };

  /* ====================================================================== Mapa */
  IDE.tabDefs.map = {
    mount(host) {
      let stop = null, cur = null, busy = false;
      const sel = h('select', { class: 'input' },
        h('option', { value: 'off' }, 'Desligado (só o cache local)'),
        h('option', { value: 'osm' }, 'OpenStreetMap (baixa da internet)'),
        h('option', { value: 'custom' }, 'Servidor próprio'));
      const url = h('input', { class: 'input mono', type: 'text', placeholder: 'https://server/z/x/y.png' });
      const urlRow = h('label', { class: 'field hidden' }, h('span', { class: 'lbl' }, 'Endereço dos blocos'), url);
      const zoom = h('input', { type: 'range', min: 2, max: 19, step: 1 });
      const zoomVal = h('b', { class: 'mono' });
      const headup = h('input', { type: 'checkbox' });
      const night = h('input', { type: 'checkbox' });
      const statBox = h('div', { class: 'muted small mono' });
      const errBox = h('div', { class: 'note danger hidden' });
      const send = async (body) => { busy = true; try { apply(await post('/api/map', body)); } catch (e) { toastErr(e); } busy = false; };
      function apply(d) {
        cur = d;
        const custom = d.source !== 'off' && d.source !== 'osm';
        if (document.activeElement !== sel) sel.value = custom ? 'custom' : d.source;
        urlRow.classList.toggle('hidden', !(custom || sel.value === 'custom'));
        if (custom && document.activeElement !== url) url.value = d.source;
        if (document.activeElement !== zoom) zoom.value = d.zoom;
        zoomVal.textContent = String(Math.round(d.zoom));
        headup.checked = d.headup; night.checked = d.night;
        statBox.textContent = IDE.t('Blocos: {n} baixados, {c} do cache, {f} falhas', { n: d.stats.downloaded, c: d.stats.cached, f: d.stats.failed });
        errBox.textContent = d.error ? IDE.t('Último erro de download: {e}', { e: d.error }) : '';
        errBox.classList.toggle('hidden', !d.error);
      }
      sel.addEventListener('change', () => { if (sel.value === 'custom') { urlRow.classList.remove('hidden'); if (/\{z\}/.test(url.value)) send({ source: url.value }); } else send({ source: sel.value }); });
      url.addEventListener('change', () => { if (/\{z\}/.test(url.value)) send({ source: url.value }); else toast('O endereço precisa ter {z}, {x} e {y}.'); });
      zoom.addEventListener('input', () => { zoomVal.textContent = zoom.value; });
      zoom.addEventListener('change', () => send({ zoom: Number(zoom.value) }));
      headup.addEventListener('change', () => send({ headup: headup.checked }));
      night.addEventListener('change', () => send({ night: night.checked }));
      IDE.add(host, h('div', { class: 'ssh' },
        h('label', { class: 'field' }, h('span', { class: 'lbl' }, 'Fonte do mapa'), sel), urlRow,
        h('p', { class: 'help' }, 'Com uma fonte ligada, o servidor de mapas recebe a região onde o GPS virtual está. Os blocos ficam guardados na pasta mapcache.'),
        h('label', { class: 'field' }, h('span', { class: 'lbl' }, 'Zoom'), h('div', { class: 'row gap' }, zoom, zoomVal)),
        h('label', { class: 'check' }, headup, h('span', null, 'Girar o mapa com o rumo do carro')),
        h('label', { class: 'check' }, night, h('span', null, 'Cores noturnas')),
        statBox, errBox,
        h('p', { class: 'help' }, 'Este mapa é desenhado pelo IDEmu. O motor de navegação da BMW não roda aqui: não há rotas nem busca de endereço.')));
      async function load() { if (!busy) apply(await api('/api/map')); }
      return { show() { stop = IDE.loop(load, 2000); }, hide() { if (stop) stop(); stop = null; }, destroy() { if (stop) stop(); } };
    },
  };

  /* ====================================================================== SSH */
  IDE.tabDefs.ssh = {
    mount(host) {
      let stop = null;
      const box = h('div', { class: 'ssh' });
      IDE.add(host, box);
      function render(d) {
        IDE.clear(box);
        const up = d.state === 'up';
        const cmdEl = h('code', { class: 'cmd' }, d.command || '');
        const copy = h('button', { class: 'btn primary', type: 'button' }, ic('copy', 16), 'Copiar');
        copy.addEventListener('click', async () => { const ok = await IDE.copyText(d.command || ''); toast(ok ? 'Comando copiado.' : 'Não foi possível copiar: selecione o texto manualmente.', ok ? 'success' : 'error'); });
        IDE.add(box,
          h('div', { class: 'ssh-state ' + (up ? 'up' : 'down') }, h('span', { class: 'dot' }), up ? 'SSH disponível' : 'SSH indisponível', d.note ? h('span', { class: 'muted small' }, ' · ' + IDE.t(d.note)) : null),
          h('div', { class: 'lbl' }, 'Comando para conectar'),
          h('div', { class: 'cmd-box' }, cmdEl, copy),
          h('dl', { class: 'kv one' },
            h('div', null, h('dt', null, 'Host'), h('dd', { class: 'mono' }, d.host)), h('div', null, h('dt', null, 'Porta'), h('dd', { class: 'mono' }, String(d.port))),
            h('div', null, h('dt', null, 'Usuário'), h('dd', { class: 'mono' }, d.user)), h('div', null, h('dt', null, 'Chave privada'), h('dd', { class: 'mono wrapany' }, d.key_path || '–'))),
          h('p', { class: 'help' }, 'Cole o comando em um terminal do seu computador. Se o sistema pedir confirmação da chave do host na primeira vez, responda "yes".'));
      }
      async function load() { render(await api('/api/ssh/info')); }
      return { show() { stop = IDE.loop(load, 3000); }, hide() { if (stop) stop(); stop = null; }, destroy() { if (stop) stop(); } };
    },
  };

  /* ====================================================================== Celular */
  IDE.tabDefs.phone = {
    mount(host) {
      let stop = null, busy = false;
      const box = h('div', { class: 'phone' });
      IDE.add(host, box);
      const copyBtn = (text) => h('button', { class: 'btn sm', type: 'button', onclick: async () => { const ok = await IDE.copyText(text); toast(ok ? 'Endereço copiado.' : 'Não foi possível copiar: selecione o texto manualmente.', ok ? 'success' : 'error'); } }, ic('copy', 14), 'Copiar');
      function urlRow(label, u) { return h('div', null, h('dt', null, label), h('dd', { class: 'mono wrapany' }, u, ' ', copyBtn(u))); }
      function render(d) {
        IDE.clear(box);
        const toggle = h('button', { class: 'btn ' + (d.running ? '' : 'primary'), type: 'button', disabled: busy, onclick: async () => {
          busy = true; load(); try { render(await post(d.running ? '/api/phone/stop' : '/api/phone/start')); } catch (e) { toastErr(e); } busy = false; load(); } }, d.running ? 'Desligar a conexão do celular' : 'Ligar a conexão do celular');
        IDE.add(box,
          h('p', { class: 'help' }, 'O celular entra pelo Wi-Fi, na mesma rede do Mac, e vira a tela, o toque, o rotor e os botões da head unit, e também o GPS do carro (a posição do celular move o GPS virtual). Bluetooth, CarPlay e Android Auto não existem na head unit emulada.'),
          h('div', { class: 'row' }, toggle));
        if (!d.running) return;
        IDE.add(box,
          h('div', { class: 'lbl' }, 'PIN'), h('div', { class: 'mono', style: 'font-size:34px;letter-spacing:.25em' }, d.pin),
          d.urls.length ? h('dl', { class: 'kv one' }, ...d.urls.map((u) => urlRow('Controle (HTTP)', u)), ...d.urls_https.map((u) => urlRow('Controle e GPS (HTTPS)', u)))
            : h('div', { class: 'note warn' }, ic('alert', 16), h('span', null, 'O Mac não está em nenhuma rede local: conecte-o ao Wi-Fi.')),
          h('p', { class: 'help' }, 'No celular, abra o endereço e digite o PIN. Para usar a localização do celular, abra o endereço HTTPS e aceite o aviso do certificado (ele é só seu); sem HTTPS o navegador do celular bloqueia a localização.'),
          d.error ? h('div', { class: 'note warn' }, ic('alert', 16), h('span', null, IDE.t(d.error))) : null,
          h('div', { class: 'ssh-state ' + (d.phones.length ? 'up' : 'down') }, h('span', { class: 'dot' }), d.phones.length ? IDE.t('{n} celular(es) conectado(s)', { n: d.phones.length }) : 'Nenhum celular conectado ainda'),
          d.gps ? h('p', { class: 'help' }, IDE.t('Última posição do celular: {lat}, {lon} ({kmh} km/h)', { lat: d.gps.lat, lon: d.gps.lon, kmh: d.gps.speed_kmh })) : null);
      }
      async function load() { try { render(await api('/api/phone')); } catch (e) { /* servidor reiniciando */ } }
      return { show() { stop = IDE.loop(load, 3000); }, hide() { if (stop) stop(); stop = null; }, destroy() { if (stop) stop(); } };
    },
  };

  /* ====================================================================== V850 */
  IDE.tabDefs.v850 = {
    mount(host) {
      let stop = null;
      const box = h('div', { class: 'ssh' });
      IDE.add(host, box);
      const CH = { 0: 'controle de fluxo do io-ipc', 1: 'watchdog do io-ipc', 5: 'interface do dev-spi (variante sem io-ipc)', 7: 'dev-navsens (sensores)', 25: 'ponte MOST/DSI', 26: 'watchdog / CSI_NBT', 27: 'touchComDevice', 28: '(sem cliente conhecido)' };
      function render(d) {
        IDE.clear(box);
        const up = !!d.connected, wd = (d.model && d.model.watchdog) || {}, fw = d.firmware || {};
        const fwRows = (fw.variants || []).map((v) => h('tr', null, h('td', { class: 'mono' }, v.family + ' ' + v.hwindex), h('td', null, v.device || ''), h('td', { class: 'mono' }, v.appl || ''), h('td', { class: 'mono' }, v.build || '')));
        const rows = Object.keys(d.channels || {}).map((c) => h('tr', null, h('td', { class: 'mono' }, c), h('td', null, CH[c] || ''), h('td', { class: 'mono' }, String(d.channels[c].from_guest)), h('td', { class: 'mono' }, String(d.channels[c].to_guest))));
        IDE.add(box,
          h('div', { class: 'ssh-state ' + (up ? 'up' : 'down') }, h('span', { class: 'dot' }), up ? 'V850 virtual conectado ao io-ipc' : 'V850 virtual desconectado'),
          h('dl', { class: 'kv one' },
            h('div', null, h('dt', null, 'Mensagens do guest'), h('dd', { class: 'mono' }, String(d.tx_msgs))), h('div', null, h('dt', null, 'Mensagens ao guest'), h('dd', { class: 'mono' }, String(d.rx_msgs))),
            h('div', null, h('dt', null, 'Batimentos do watchdog'), h('dd', { class: 'mono' }, String(wd.heartbeats || 0))), h('div', null, h('dt', null, 'Ciclo do watchdog'), h('dd', { class: 'mono' }, wd.cycle_ms ? wd.cycle_ms + ' ms' : '–'))),
          h('table', { class: 'tbl' }, h('thead', null, h('tr', null, h('th', null, 'Canal'), h('th', null, 'Uso'), h('th', null, 'Do guest'), h('th', null, 'Para o guest'))), h('tbody', null, rows)),
          fwRows.length ? h('div', { class: 'lbl' }, 'Firmware do IOC (PSdZData)') : null,
          fwRows.length ? h('table', { class: 'tbl' }, h('thead', null, h('tr', null, h('th', null, 'Revisão de hardware'), h('th', null, 'Dispositivo'), h('th', null, 'Aplicação'), h('th', null, 'Compilação'))), h('tbody', null, fwRows)) : null,
          h('div', { class: 'lbl' }, 'Últimas mensagens'),
          h('pre', { class: 'logbox' }, (d.recent || []).slice(-25).map((m) => (m.dir === 'from_guest' ? '<- ' : '-> ') + IDE.t('canal {n}', { n: m.chan }) + ' [' + m.len + '] ' + m.hex).join('\n') || IDE.t('(nenhuma)')),
          h('p', { class: 'help' }, 'O V850 é emulado no host: o io-ipc do sistema original conversa com ele por uma UART virtual. O canal 27 (toque) ainda não tem modelo — veja docs/V850.md e docs/V850_FIRMWARE.md.'));
      }
      async function load() { render(await api('/api/v850')); }
      return { show() { stop = IDE.loop(load, 1500); }, hide() { if (stop) stop(); stop = null; }, destroy() { if (stop) stop(); } };
    },
  };

  /* ====================================================================== Logs */
  IDE.tabDefs.logs = {
    mount(host, ctx) {
      let stop = null, last = '';
      const sel = h('select', { class: 'input sm', 'aria-label': 'Log' }, [['console', 'Console'], ['qemu', 'QEMU'], ['renderer', 'Renderizador'], ['v850', 'V850'], ['guest', 'Sistema convidado']].map(([v, l]) => h('option', { value: v }, l)));
      sel.value = IDE.pref.get('logs.name', 'console');
      const tail = h('select', { class: 'input sm', 'aria-label': 'Linhas' }, [100, 200, 500, 1000].map((n) => h('option', { value: n }, IDE.t('{n} linhas', { n }))));
      tail.value = String(IDE.pref.get('logs.tail', 200));
      const autoCb = h('input', { type: 'checkbox', checked: IDE.pref.get('logs.auto', true), onchange: () => { IDE.pref.set('logs.auto', autoCb.checked); restart(); } });
      const filter = h('input', { class: 'input sm', type: 'search', placeholder: 'Filtrar linhas…', 'aria-label': 'Filtrar' });
      const pre = h('pre', { class: 'logbox tall' });
      const status = h('span', { class: 'muted small' });
      const copyBtn = h('button', { class: 'btn sm', type: 'button', onclick: async () => { const ok = await IDE.copyText(pre.textContent); toast(ok ? 'Log copiado.' : 'Não foi possível copiar.', ok ? 'success' : 'error'); } }, ic('copy', 14), 'Copiar');
      const refBtn = h('button', { class: 'btn sm', type: 'button', onclick: () => load().catch(toastErr) }, ic('refresh', 14), 'Atualizar');
      IDE.add(host, h('div', { class: 'toolbar' }, sel, tail, filter), h('div', { class: 'toolbar' }, h('label', { class: 'check' }, autoCb, h('span', null, 'Atualizar sozinho')), refBtn, copyBtn, h('div', { class: 'spacer' }), status), pre);
      let lines = [];
      function paint() {
        const f = filter.value.trim().toLowerCase();
        const shown = f ? lines.filter((l) => l.toLowerCase().includes(f)) : lines;
        const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 30;
        const txt = shown.join('\n');
        if (txt !== last) { pre.textContent = txt || IDE.t('(vazio)'); last = txt; if (atBottom) pre.scrollTop = pre.scrollHeight; }
        status.textContent = IDE.t('{n} linhas', { n: shown.length });
      }
      async function load() {
        const d = await api('/api/logs?' + IDE.qs({ name: sel.value, tail: tail.value, env: ((ctx && ctx.status()) || {}).env || null }));
        lines = d.lines || []; paint();
      }
      function restart() { if (stop) stop(); stop = null; if (autoCb.checked && shown) stop = IDE.loop(load, 2000); else if (shown) load().catch(() => {}); }
      let shown = false;
      sel.addEventListener('change', () => { IDE.pref.set('logs.name', sel.value); last = ''; pre.scrollTop = 1e9; load().catch(toastErr); });
      tail.addEventListener('change', () => { IDE.pref.set('logs.tail', Number(tail.value)); load().catch(toastErr); });
      filter.addEventListener('input', paint);
      return {
        show() { shown = true; last = ''; restart(); setTimeout(() => { pre.scrollTop = pre.scrollHeight; }, 100); },
        hide() { shown = false; if (stop) stop(); stop = null; }, destroy() { if (stop) stop(); },
      };
    },
  };
})(window.IDE);
