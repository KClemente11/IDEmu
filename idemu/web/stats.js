'use strict';
/* IDEmu – "Estatísticas avançadas": o gerenciador de tarefas da VM (CPU, memória, GPU, FPS, tempo de quadro, armazenamento). */
(function (IDE) {
  const { h, ic, api } = IDE;
  const C = { cpu: '#0a84ff', cpu2: '#64d2ff', ram: '#5e8bb8', ram2: '#9fb7d3', gpu: '#2fb4d8', gpu2: '#8fd8ee', fps: '#7a8ca3', ft: '#4f6d94', ft2: '#9fb3cc', sto: '#64d2ff' };
  const WINDOWS = [[60, '1 min'], [300, '5 min'], [900, '15 min']];
  const nf = (v, d) => (v == null || isNaN(v) ? '–' : Number(v).toLocaleString(IDE.locale(), { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 }));
  const fmtMb = (mb) => (mb == null ? '–' : mb >= 1024 ? nf(mb / 1024, 2) + ' GB' : nf(mb, 0) + ' MB');
  const fmtB = (b) => IDE.fmtSize(b);
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

  /** Define cada métrica: séries do gráfico, escala, texto do bloco e fatos da lateral. */
  const METRICS = {
    cpu: { title: 'CPU da VM', icon: 'cpu', color: C.cpu, unit: '%', floor: 100, step: 100,
      series: [{ k: 'cpu_qemu', label: 'VM (QEMU)', color: C.cpu, fill: true }, { k: 'cpu_gl', label: 'Renderizador', color: C.cpu2 }],
      fmt: (v) => nf(v, 0) + '%', cur: (s) => s.cpu_qemu, sub: 'Cada 100% equivale a um núcleo do Mac ocupado.',
      facts: (s, d, st) => [['VM (QEMU)', nf(s.cpu_qemu, 0), '%'], ['Renderizador', nf(s.cpu_gl, 0), '%'], ['Média da janela', nf(avg(d, 'cpu_qemu'), 0), '%'], ['Pico da janela', nf(maxOf(d, 'cpu_qemu'), 0), '%'],
        ['Núcleos do Mac', nf(st.cores), ''], ['Capacidade máxima', nf(st.cores * 100), '%'], ['PID do QEMU', st.qemu_pid || '–', ''], ['Tempo ligado', IDE.fmtDur(s.up), '']] },
    ram: { title: 'Memória', icon: 'layers', color: C.ram, unit: 'MB', floor: 0, step: 512, limit: (st) => st.guest_ram_mb, limitLabel: 'Teto da RAM do convidado',
      series: [{ k: 'rss_qemu', label: 'RAM da VM (QEMU)', color: C.ram, fill: true }, { k: 'rss_gl', label: 'Renderizador', color: C.ram2 }],
      fmt: (v) => fmtMb(v), cur: (s) => s.rss_qemu, sub: 'RAM residente (RSS) do processo da VM, medida no Mac.',
      facts: (s, d, st) => [['RAM da VM', fmtMb(s.rss_qemu), ''], ['Teto do convidado', fmtMb(st.guest_ram_mb), ''], ['Uso do teto', nf(100 * s.rss_qemu / st.guest_ram_mb, 0), '%'], ['Renderizador', fmtMb(s.rss_gl), ''],
        ['Pico da janela', fmtMb(maxOf(d, 'rss_qemu')), ''], ['RAM total do Mac', fmtMb(st.host_ram_mb), ''], ['VM no total do Mac', nf(100 * s.rss_qemu / st.host_ram_mb, 1), '%'], ['Memória virtual', fmtMb(s.vsz_qemu), '']],
      note: 'A RAM residente passa do teto de 2 GB do convidado porque inclui as imagens do sistema carregadas na RAM, os buffers do emulador e o código traduzido. O teto é o que a VM enxerga (opção -m do QEMU).' },
    gpu: { title: 'GPU', icon: 'target', color: C.gpu, unit: '%', floor: 100, step: 25, fixedMax: 100,
      series: [{ k: 'gpu', label: 'Uso do dispositivo', color: C.gpu, fill: true }, { k: 'gpu_render', label: 'Renderizador', color: C.gpu2 }],
      fmt: (v) => nf(v, 0) + '%', cur: (s) => s.gpu, sub: 'Uso da GPU do Mac inteiro: o macOS não informa o uso por processo.',
      facts: (s, d, st) => [['Uso do dispositivo', nf(s.gpu, 0), '%'], ['Renderizador', nf(s.gpu_render, 0), '%'], ['Tiler', nf(s.gpu_tiler, 0), '%'], ['Média da janela', nf(avg(d, 'gpu'), 0), '%'],
        ['Pico da janela', nf(maxOf(d, 'gpu'), 0), '%'], ['Memória em uso', fmtMb(s.gpu_mem_mb), ''], ['GPU', st.gpu || '–', '']] },
    fps: { title: 'Quadros por segundo', icon: 'activity', color: C.fps, unit: 'fps', floor: 30, step: 10,
      series: [{ k: 'fps', label: 'FPS', color: C.fps, fill: true }],
      fmt: (v) => nf(v, 0) + ' fps', cur: (s) => s.fps, sub: 'Quadros que o renderizador entregou. Com a tela parada, o valor cai a zero.',
      facts: (s, d) => [['Agora', nf(s.fps, 0), 'fps'], ['Média da janela', nf(avg(d, 'fps'), 1), 'fps'], ['Máximo', nf(maxOf(d, 'fps'), 0), 'fps'], ['Mínimo', nf(minOf(d, 'fps'), 0), 'fps'],
        ['1% piores', nf(low1(d, 'fps'), 0), 'fps']] },
    ft: { title: 'Tempo de quadro', icon: 'pause', color: C.ft, unit: 'ms', floor: 50, step: 10,
      series: [{ k: 'ft_avg', label: 'Média', color: C.ft, fill: true }, { k: 'ft_p95', label: 'Percentil 95', color: C.ft2 }, { k: 'ft_max', label: 'Máximo', color: C.cpu2, dash: true }],
      fmt: (v) => nf(v, 1) + ' ms', cur: (s) => s.ft_avg, sub: 'Intervalo entre quadros consecutivos, em cada segundo. Menor é melhor.',
      facts: (s, d) => [['Média agora', nf(s.ft_avg, 1), 'ms'], ['Percentil 95', nf(s.ft_p95, 1), 'ms'], ['Pior quadro', nf(s.ft_max, 1), 'ms'], ['Média da janela', nf(avg(d, 'ft_avg', true), 1), 'ms'],
        ['Pior da janela', nf(maxOf(d, 'ft_max'), 1), 'ms']] },
    sto: { title: 'Armazenamento', icon: 'folder', color: C.sto, storage: true },
  };
  const ORDER = ['cpu', 'ram', 'gpu', 'fps', 'ft', 'sto'];
  const PART_COLORS = ['#0a84ff', '#5e8bb8', '#2fb4d8', '#7a8ca3', '#9fb7d3', '#4f6d94', '#b4bcc8'];

  function vals(d, k, skipZero) { return d.map((s) => s[k]).filter((v) => v != null && (!skipZero || v > 0)); }
  function avg(d, k, skipZero) { const v = vals(d, k, skipZero); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; }
  function maxOf(d, k) { const v = vals(d, k); return v.length ? Math.max.apply(null, v) : null; }
  function minOf(d, k) { const v = vals(d, k); return v.length ? Math.min.apply(null, v) : null; }
  function low1(d, k) { const v = vals(d, k).sort((a, b) => a - b); return v.length ? v[Math.floor(v.length * 0.01)] : null; }
  function niceMax(m, floor, step) { return Math.max(floor || 0, Math.ceil((m * 1.05 || 1) / step) * step); }

  /** Desenha um gráfico de linhas/áreas no estilo do gerenciador de tarefas. opts: {w:[t0,t1], max, series:[{data:[[t,v]],color,fill,dash}], limit, mini, hover} */
  function drawChart(cv, o) {
    const dpr = window.devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
    if (!W || !H) return null;
    if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
    const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
    const pad = o.mini ? { l: 0, r: 0, t: 2, b: 2 } : { l: 50, r: 12, t: 12, b: 8 };
    const pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;
    const [t0, t1] = o.w, X = (t) => pad.l + (t - t0) / (t1 - t0) * pw, Y = (v) => pad.t + ph - Math.min(1, Math.max(0, v / o.max)) * ph;
    if (!o.mini) {
      g.font = '11px ' + css('--sans'); g.textBaseline = 'middle'; g.textAlign = 'right';
      const n = 4;
      for (let i = 0; i <= n; i++) {
        const v = o.max * i / n, y = Y(v);
        g.strokeStyle = css('--line'); g.lineWidth = 1; g.beginPath(); g.moveTo(pad.l, Math.round(y) + .5); g.lineTo(W - pad.r, Math.round(y) + .5); g.stroke();
        g.fillStyle = css('--faint'); g.fillText(o.axis(v), pad.l - 8, Math.min(H - 8, Math.max(8, y)));
      }
      const span = t1 - t0, stepT = span <= 60 ? 10 : span <= 300 ? 60 : 180;
      for (let t = Math.ceil(t0 / stepT) * stepT; t < t1; t += stepT) {
        const x = Math.round(X(t)) + .5; g.strokeStyle = css('--line'); g.beginPath(); g.moveTo(x, pad.t); g.lineTo(x, pad.t + ph); g.stroke();
      }
    }
    g.save(); g.beginPath(); g.rect(pad.l, 0, pw, H); g.clip();
    if (o.limit != null) {
      const y = Y(o.limit); g.strokeStyle = css('--danger'); g.setLineDash([6, 4]); g.lineWidth = 1.2; g.beginPath(); g.moveTo(pad.l, y); g.lineTo(W - pad.r, y); g.stroke(); g.setLineDash([]);
      if (!o.mini) { g.fillStyle = css('--danger-t'); g.textAlign = 'left'; g.font = '600 11px ' + css('--sans'); g.fillText(o.limitLabel + ': ' + o.axis(o.limit), pad.l + 8, Math.max(10, y - 9)); }
    }
    o.series.forEach((s, si) => {
      const pts = s.data.filter((p) => p[1] != null && p[0] >= t0 - 2 && p[0] <= t1 + 2);
      if (pts.length < 2) return;
      g.beginPath(); pts.forEach((p, i) => { const x = X(p[0]), y = Y(p[1]); if (i) g.lineTo(x, y); else g.moveTo(x, y); });
      if (s.fill) {
        const grad = g.createLinearGradient(0, pad.t, 0, pad.t + ph); grad.addColorStop(0, s.color + (o.mini ? '77' : '55')); grad.addColorStop(1, s.color + '05');
        g.save(); g.lineTo(X(pts[pts.length - 1][0]), pad.t + ph); g.lineTo(X(pts[0][0]), pad.t + ph); g.closePath(); g.fillStyle = grad; g.fill(); g.restore();
        g.beginPath(); pts.forEach((p, i) => { const x = X(p[0]), y = Y(p[1]); if (i) g.lineTo(x, y); else g.moveTo(x, y); });
      }
      g.strokeStyle = s.color; g.lineWidth = o.mini ? 1.4 : (si ? 1.5 : 2); g.lineJoin = 'round'; g.setLineDash(s.dash ? [4, 3] : []); g.stroke(); g.setLineDash([]);
    });
    g.restore();
    if (o.hover != null && !o.mini) {
      const x = Math.round(X(o.hover)) + .5; g.strokeStyle = css('--line3'); g.lineWidth = 1; g.beginPath(); g.moveTo(x, pad.t); g.lineTo(x, pad.t + ph); g.stroke();
      o.series.forEach((s) => { const p = nearest(s.data, o.hover); if (p && p[1] != null) { g.fillStyle = s.color; g.beginPath(); g.arc(X(p[0]), Y(p[1]), 4, 0, 7); g.fill(); g.strokeStyle = css('--bg'); g.lineWidth = 1.5; g.stroke(); } });
    }
    return { X, pad, pw };
  }
  function nearest(data, t) { let best = null, bd = 1e9; for (let i = data.length - 1; i >= 0; i--) { const d = Math.abs(data[i][0] - t); if (d < bd) { bd = d; best = data[i]; } else if (data[i][0] < t) break; } return best; }

  function mount(root) {
    const S = { data: [], last: 0, static: {}, storage: null, running: false, env: null, state: 'stopped', sel: IDE.pref.get('stats.sel', 'cpu'), win: IDE.pref.get('stats.win', 60), hover: null, paused: false };
    if (!METRICS[S.sel]) S.sel = 'cpu';
    const bar = h('div', { class: 'st-bar card' });
    const list = h('div', { class: 'st-list card' });
    const main = h('div', { class: 'st-main card' });
    root.appendChild(h('div', { class: 'page wide st-page' },
      h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'Estatísticas avançadas'), h('p', { class: 'sub' }, 'O gerenciador de tarefas da VM: processador, memória, GPU, quadros e armazenamento em tempo real.'))),
      bar, h('div', { class: 'st-grid' }, list, main)));

    const tiles = {}; let chartCv = null, tip = null, factsEl = null, bigEl = null, legendEl = null, axL = null, axR = null, builtFor = null;

    function now() { const last = S.data[S.data.length - 1]; return Math.max(last ? last.t : 0, Date.now() / 1000 - 1); }
    const win = () => { const t1 = now(); return [t1 - S.win, t1]; };
    const dataFor = (m) => m.series.map((s) => ({ color: s.color, fill: s.fill, dash: s.dash, label: s.label, data: S.data.map((x) => [x.t, x[s.k]]) }));
    const visible = () => { const [a] = win(); return S.data.filter((x) => x.t >= a); };
    const lastS = () => S.data[S.data.length - 1] || {};

    function renderBar() {
      IDE.clear(bar);
      const env = S.env ? IDE.envById(S.env) : null;
      const [bt, bk] = S.running ? (S.state === 'booting' ? ['Iniciando', 'info'] : ['Em execução', 'live']) : ['Parado', 'muted'];
      IDE.add(bar,
        h('div', { class: 'env-ico', style: { width: '38px', height: '38px', 'border-radius': '11px' } }, ic('car', 20)),
        h('div', { class: 'st-env' }, h('b', null, env ? env.name : (S.env || IDE.t('Nenhum ambiente'))), h('span', null, S.running ? IDE.t('Ligado há {t}', { t: IDE.fmtDur(lastS().up || 0) }) + (S.static.boot_kind ? ' · ' + S.static.boot_kind : '') : IDE.t('Inicie um ambiente para ver os gráficos ao vivo'))),
        IDE.badge(bt, bk), h('div', { class: 'spacer' }),
        h('div', { class: 'st-win', role: 'group', 'aria-label': 'Janela' }, WINDOWS.map(([sec, label]) => h('button', { type: 'button', class: S.win === sec ? 'on' : '', onclick: () => { S.win = sec; IDE.pref.set('stats.win', sec); renderBar(); draw(); } }, label))),
        h('button', { class: 'btn', type: 'button', onclick: () => { S.paused = !S.paused; renderBar(); } }, ic(S.paused ? 'play' : 'pause', 16), S.paused ? 'Retomar' : 'Pausar'),
        S.running ? null : h('a', { class: 'btn primary', href: '#/ambientes' }, ic('play', 16), 'Ir para Ambientes'));
    }

    function buildList() {
      IDE.clear(list);
      ORDER.forEach((id) => {
        const m = METRICS[id];
        const cv = h('canvas', { width: 148, height: 76 });
        const tv = h('span', { class: 'tv' }, '–');
        const b = h('button', { type: 'button', class: 'st-tile' + (S.sel === id ? ' on' : ''), style: { '--c': m.color }, onclick: () => { S.sel = id; IDE.pref.set('stats.sel', id); S.hover = null; refreshTiles(); buildMain(); draw(); } },
          h('span', { class: 'tt' }, h('i'), IDE.t(m.title)), tv, cv);
        tiles[id] = { b, cv, tv }; list.appendChild(b);
      });
    }
    function refreshTiles() { ORDER.forEach((id) => tiles[id].b.classList.toggle('on', S.sel === id)); }

    function buildMain() {
      IDE.clear(main); builtFor = S.sel;
      const m = METRICS[S.sel]; main.style.setProperty('--c', m.color);
      bigEl = h('div', { class: 'st-big' });
      IDE.add(main, h('div', { class: 'st-head' }, h('div', null, h('h2', null, m.title), h('div', { class: 'st-sub' }, m.sub || '')), bigEl));
      if (m.storage) { factsEl = h('div'); main.appendChild(factsEl); chartCv = null; return; }
      chartCv = h('canvas'); tip = h('div', { class: 'st-tip', hidden: true });
      const box = h('div', { class: 'st-chart' }, chartCv, tip);
      axL = h('span'); axR = h('span', null, IDE.t('agora'));
      legendEl = h('div', { class: 'st-legend' }, m.series.map((s) => h('span', { style: { '--c': s.color } }, h('i'), IDE.t(s.label))),
        m.limit ? h('span', { style: { '--c': css('--danger') } }, h('i'), IDE.t(m.limitLabel)) : null);
      factsEl = h('dl', { class: 'st-facts' });
      IDE.add(main, box, h('div', { class: 'st-ax' }, axL, axR), legendEl, factsEl, m.note ? h('div', { class: 'st-note' }, ic('info', 14), h('span', null, m.note)) : null);
      box.addEventListener('mousemove', (e) => { const r = chartCv.getBoundingClientRect(); const [t0, t1] = win(); const x = Math.min(Math.max(e.clientX - r.left - 50, 0), r.width - 62); S.hover = t0 + x / (r.width - 62) * (t1 - t0); draw(); showTip(r, e.clientX - r.left); });
      box.addEventListener('mouseleave', () => { S.hover = null; tip.hidden = true; draw(); });
    }
    function showTip(rect, px) {
      const m = METRICS[S.sel]; if (S.hover == null) return;
      const ser = dataFor(m); const rows = ser.map((s) => { const p = nearest(s.data, S.hover); return p && p[1] != null ? '<div><span style="color:' + s.color + '">●</span> ' + IDE.esc(IDE.t(s.label)) + ': <b>' + IDE.esc(m.fmt(p[1])) + '</b></div>' : ''; }).join('');
      const p0 = nearest(ser[0].data, S.hover);
      const ago = p0 ? Math.max(0, Math.round(now() - p0[0])) : 0;
      tip.innerHTML = '<div style="color:var(--faint)">' + IDE.esc(ago ? IDE.t('há {n} s', { n: ago }) : IDE.t('agora')) + '</div>' + rows; tip.hidden = false;
      tip.style.left = (px > rect.width / 2 ? Math.max(8, px - tip.offsetWidth - 14) : px + 14) + 'px';
    }

    function draw() {
      const w = win(), vis = visible(), last = lastS(), m = METRICS[S.sel];
      // blocos da esquerda
      ORDER.forEach((id) => {
        const mm = METRICS[id], t = tiles[id]; if (!t) return;
        if (mm.storage) {
          const st = S.storage; t.tv.textContent = st ? fmtB(st.total) : '–';
          drawStack(t.cv, st); return;
        }
        t.tv.textContent = S.data.length ? mm.fmt(mm.cur(last)) : '–';
        let max = mm.fixedMax || niceMax(Math.max.apply(null, mm.series.flatMap((s) => vals(vis, s.k)).concat([0])), mm.floor, mm.step);
        if (mm.limit) max = Math.max(max, mm.limit(S.static) * 1.12);
        drawChart(t.cv, { w, max, mini: true, limit: mm.limit ? mm.limit(S.static) : null, series: dataFor(mm).map((s, i) => (i ? Object.assign(s, { fill: false }) : s)).slice(0, 1).map((s) => Object.assign(s, { fill: true })), axis: String });
      });
      if (builtFor !== S.sel) buildMain();
      if (m.storage) { drawStorage(); return; }
      const ser = dataFor(m);
      let max = m.fixedMax || niceMax(Math.max.apply(null, m.series.flatMap((s) => vals(vis, s.k)).concat([0])), m.floor, m.step);
      const lim = m.limit ? m.limit(S.static) : null; if (lim != null) max = Math.max(max, lim * 1.12);
      if (chartCv) drawChart(chartCv, { w, max, series: ser, limit: lim, limitLabel: m.limitLabel ? IDE.t(m.limitLabel) : '', axis: (v) => (m.unit === 'MB' ? (v >= 1024 ? nf(v / 1024, 1) + ' GB' : nf(v, 0)) : nf(v, v < 10 && m.unit !== '%' ? 1 : 0) + (m.unit === '%' ? '%' : '')), hover: S.hover });
      if (axL) axL.textContent = IDE.t('{n} s atrás', { n: S.win });
      bigEl.innerHTML = '';
      if (S.data.length) { const v = m.cur(last); const txt = m.fmt(v); const mt = /^([\d.,]+)\s*(.*)$/.exec(txt); bigEl.appendChild(document.createTextNode(mt ? mt[1] : txt)); if (mt && mt[2]) bigEl.appendChild(h('small', null, mt[2])); } else bigEl.textContent = '–';
      if (factsEl && m.facts && S.data.length) { IDE.clear(factsEl); m.facts(last, vis, S.static).forEach(([k, v, u]) => factsEl.appendChild(h('div', null, h('dt', null, k), h('dd', null, String(v), u ? h('small', null, ' ' + u) : null)))); }
    }

    function drawStack(cv, st) {
      const dpr = window.devicePixelRatio || 1, W = cv.clientWidth || 74, H = cv.clientHeight || 38; cv.width = W * dpr; cv.height = H * dpr;
      const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
      if (!st || !st.total) return;
      let x = 0; const y = H / 2 - 5;
      g.fillStyle = css('--sunken'); g.beginPath(); g.roundRect(0, y, W, 10, 5); g.fill();
      st.parts.forEach((p, i) => { const w = Math.max(2, W * p.bytes / st.total); g.fillStyle = PART_COLORS[i % PART_COLORS.length]; g.fillRect(x, y, w, 10); x += w; });
    }
    function drawStorage() {
      const st = S.storage; IDE.clear(factsEl);
      if (!st) { bigEl.textContent = '–'; factsEl.appendChild(h('div', { class: 'st-idle' }, h('p', null, 'Sem dados de armazenamento para este ambiente.'))); return; }
      const big = fmtB(st.total).split(' '); bigEl.textContent = ''; bigEl.appendChild(document.createTextNode(big[0])); bigEl.appendChild(h('small', null, big[1] || ''));
      const parts = st.parts.slice().sort((a, b) => b.bytes - a.bytes);
      const col = (p) => PART_COLORS[st.parts.indexOf(p) % PART_COLORS.length];
      const pctFree = Math.round(100 * st.disk_free / st.disk_total);
      IDE.add(factsEl,
        h('div', { class: 'st-sub', style: { margin: '2px 0 4px', color: 'var(--muted)' } }, IDE.t('Ambiente {id}', { id: S.env || '' })),
        h('div', { class: 'st-stack' }, parts.map((p) => h('i', { style: { width: (100 * p.bytes / st.total) + '%', '--c': col(p) }, title: IDE.t(p.label) + ' · ' + fmtB(p.bytes) }))),
        h('div', { class: 'st-parts' }, parts.map((p) => h('div', { class: 'st-part', style: { '--c': col(p) } }, h('i'), h('span', null, p.label), h('b', null, fmtB(p.bytes))))),
        h('dl', { class: 'st-facts' },
          h('div', null, h('dt', null, 'Total do ambiente'), h('dd', null, fmtB(st.total))),
          h('div', null, h('dt', null, 'Livre no disco do Mac'), h('dd', null, fmtB(st.disk_free), h('small', null, ' · ' + pctFree + '%'))),
          h('div', null, h('dt', null, 'Tamanho do disco'), h('dd', null, fmtB(st.disk_total)))),
        h('div', { class: 'st-note' }, ic('info', 14), h('span', null, 'O estado do boot rápido (snapshot) guarda a RAM da VM e costuma ser a maior parte. Apague-o em Ambientes se precisar de espaço.')));
    }

    async function poll() {
      if (S.paused) return;
      const d = await api('/api/stats?' + IDE.qs({ since: S.last || 0, env: IDE.state.running || (S.env || '') }));
      S.static = d.static || S.static; S.running = d.running; S.state = d.state; S.env = d.env || d.storage_env || S.env; S.storage = d.storage || S.storage;
      if (d.samples && d.samples.length) {
        if (S.last && d.samples[0].t < S.last - 5) S.data = [];
        S.data = S.data.concat(d.samples).slice(-900); S.last = S.data[S.data.length - 1].t;
      } else if (!d.running && S.data.length && d.state === 'stopped') { /* mantém o histórico da última execução */ }
      renderBar(); draw();
      if (!S.running) idleHint();
    }
    function idleHint() { /* sem gráficos vivos: o armazenamento continua útil */ }

    buildList(); buildMain(); renderBar();
    const stopLoop = IDE.loop(poll, () => (document.hidden ? 4000 : 1000));
    const onResize = () => draw(); window.addEventListener('resize', onResize);
    return { unmount() { stopLoop(); window.removeEventListener('resize', onResize); } };
  }
  IDE.views.stats = { mount };
})(window.IDE);
