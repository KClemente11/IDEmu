'use strict';
/* IDEmu – ferramentas do ambiente: decodificador de VIN (assistente e ambientes prontos) e navegador dos arquivos do sistema do iDrive. */
(function (IDE) {
  const { h, ic, api, post, toast, toastErr } = IDE;
  const GEN_NAME = { id4: 'iDrive 4', id5: 'iDrive 5', id6: 'iDrive 6', id7: 'iDrive 7', id8: 'iDrive 8' };
  IDE.genName = (g) => GEN_NAME[g] || '–';

  /* ------------------------------------------------------------------ VIN */
  /** Painel "Preencher pelo VIN": campo + resultado. o.onUse(decode) mostra o botão "Usar este carro"; o.value = VIN inicial. */
  IDE.vinPanel = function (o) {
    o = o || {};
    const input = h('input', { class: 'input mono vin-in', type: 'text', maxlength: 17, spellcheck: 'false', autocapitalize: 'characters', value: o.value || '',
      placeholder: 'WBA8E9C50GK000001', 'aria-label': 'VIN' });
    const count = h('span', { class: 'count' }, (o.value || '').length + '/17');
    const go = h('button', { class: 'btn primary', type: 'button' }, ic('target', 16), 'Decodificar');
    const out = h('div', { class: 'vin-out' });
    let last = null, timer = null;
    function norm() { const v = input.value.toUpperCase().replace(/[^A-Z0-9]/g, ''); if (v !== input.value) input.value = v; count.textContent = v.length + '/17'; return v; }
    input.addEventListener('input', () => { const v = norm(); if (v.length === 17) decode(); });
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); decode(); } });
    go.addEventListener('click', () => decode());
    async function decode() {
      const v = norm();
      if (v.length !== 17) { show(h('div', { class: 'note warn' }, ic('alert', 16), h('span', null, IDE.t('O VIN precisa ter 17 caracteres (tem {n}).', { n: v.length })))); return; }
      clearTimeout(timer);
      await IDE.busy(go, async () => {
        try {
          const d = await api('/api/vin/decode?vin=' + encodeURIComponent(v));
          last = d; render(d);
          if (d.table && d.table.state === 'building') timer = setTimeout(decode, 2500);     // tabela de tipos sendo montada: tenta de novo sozinho
        } catch (e) { show(h('div', { class: 'note danger' }, ic('alert', 16), h('span', null, e.message))); }
      });
    }
    function show(el) { IDE.clear(out); if (el) out.appendChild(el); }
    function render(d) {
      if (d.table && d.table.state === 'building') {
        show(h('div', { class: 'note info' }, h('div', { class: 'spinner' }), h('span', null, IDE.t('Montando a tabela de tipos a partir da sua PSdZData ({pct}%). Só na primeira vez.', { pct: d.table.pct || 0 }))));
        return;
      }
      const row = (k, v) => (v ? h('div', null, h('dt', null, k), h('dd', null, v)) : null);
      const sug = d.env || {};
      const gen = d.generation;
      const box = h('div', { class: 'vin-card' },
        h('div', { class: 'vin-head' }, h('div', { class: 'env-ico' }, ic('car', 22)),
          h('div', null, h('b', null, d.found ? [d.chassis, d.chassis_name && d.chassis_name !== d.chassis ? d.chassis_name : null].filter(Boolean).join(' – ') : IDE.t('Tipo {t} não encontrado', { t: d.type_key })),
            h('div', { class: 'muted small' }, [IDE.brandName(d.brand), d.model_year ? IDE.t('ano-modelo {y}', { y: d.model_year }) : null, d.maker].filter(Boolean).join(' · '))),
          gen ? IDE.badge(GEN_NAME[gen], 'ok') : IDE.badge('Geração desconhecida', 'muted')),
        h('dl', { class: 'kv' },
          row('Carroceria', d.body), row('Motor', d.engine), row('Tração', d.drive), row('Câmbio', d.gearbox),
          row('Volante', d.steering ? IDE.t('à {side}', { side: IDE.t(d.steering) }) : null), row('Mercado', d.market),
          row('Código do tipo', d.type_key), row('Série (PSdZData)', d.series || d.kis_series)),
        (d.notes || []).map((n) => h('div', { class: 'note info' }, ic('info', 16), h('span', null, n))),
        d.check_digit_ok === false && d.us ? h('div', { class: 'note warn' }, ic('alert', 16), h('span', null, 'O dígito verificador (9º caractere) não confere. Confira se o VIN foi digitado certo.')) : null,
        h('p', { class: 'muted small' }, 'O VIN não traz a lista de opcionais do carro: o tipo de head unit (Professional, Business ou EntryNav) você escolhe a seguir.'),
        o.onUse && gen ? h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'button', onclick: () => o.onUse(d) }, ic('check', 16), o.useLabel || 'Usar este carro')) : null);
      show(box);
      if (o.onDecoded) o.onDecoded(d, sug);
    }
    const el = h('div', { class: 'vin-panel' },
      h('div', { class: 'row tight' }, input, go), h('div', { class: 'row between' }, h('span', { class: 'muted small' }, o.hint || 'Os 17 caracteres do chassi, no documento do carro ou no para-brisa.'), count), out);
    el.decode = decode; el.last = () => last;
    if (o.value && o.value.length === 17) setTimeout(decode, 0);
    return el;
  };

  /** Diálogo "Carro pelo VIN" de um ambiente pronto: decodifica e aplica (chassi, ano, HMI, mercado; tipo de head unit no iDrive 5/6). */
  IDE.vinDialog = function (env) {
    const nbt = !env.kind;
    let variant = (env.coding || {}).hu_variant || 'professional';
    const varBox = nbt ? IDE.huVariantPicker(() => variant, (v) => { variant = v; }) : null;
    const panel = IDE.vinPanel({ value: (env.coding || {}).vin || '' });
    const m = IDE.modal({
      title: IDE.t('Carro pelo VIN – {name}', { name: env.name }), size: 'lg',
      body: h('div', { class: 'stack' },
        h('p', { class: 'help' }, nbt ? 'Digite o VIN do seu carro: o IDEmu acerta o chassi, o ano, a versão do HMI e o mercado da head unit para ficar igual à do carro. A codificação nova vale na próxima partida.'
          : 'Digite o VIN do seu carro: ele fica gravado na codificação e o IDEmu mostra o carro e a central que ele usa.'),
        panel, nbt ? h('h3', null, 'Tipo de head unit') : null, varBox),
      actions: [{ label: 'Cancelar' }, { label: 'Aplicar ao ambiente', kind: 'primary', icon: 'check', closes: false, onClick: async (api_, b) => {
        const d = panel.last();
        if (!d) { await panel.decode(); return false; }
        await IDE.busy(b, async () => {
          try {
            const r = await post('/api/env/' + env.id + '/vin', { vin: d.vin, hu_variant: nbt ? variant : undefined });
            (r.notes || []).forEach((n) => toast(n, 'info'));
            toast('Ambiente atualizado pelo VIN.', 'success'); await IDE.refreshState().catch(() => {}); m.close();
          } catch (e) { toastErr(e); }
        });
        return false;
      } }],
    });
    return m;
  };

  /** Escolha do tipo de head unit (iDrive 5/6). get() -> id atual; set(id) ao clicar. */
  IDE.huVariantPicker = function (get, set) {
    const wrap = h('div', { class: 'hu-grid', role: 'radiogroup', 'aria-label': 'Tipo de head unit' });
    function draw() {
      IDE.clear(wrap);
      const list = (IDE.catalog && IDE.catalog.hu_variants) || [];
      if (!list.length) { IDE.loadCatalog().then(() => { if ((IDE.catalog.hu_variants || []).length) draw(); }).catch(() => {}); return; }
      list.forEach((v) => {
        const on = get() === v.id;
        wrap.appendChild(h('button', { type: 'button', class: 'opt hu-opt' + (on ? ' sel' : ''), role: 'radio', 'aria-checked': on ? 'true' : 'false', onclick: () => { set(v.id); draw(); } },
          h('span', { class: 'opt-main' }, h('b', null, v.name), h('span', null, v.sub)), on ? ic('check', 16) : null));
      });
    }
    draw();
    return wrap;
  };

  /* ------------------------------------------------------------------ arquivos do sistema */
  IDE.sysFilesDialog = function (env) {
    const S = { path: '', dead: false, st: null };
    const crumbs = h('div', { class: 'sf-crumbs' });
    const list = h('div', { class: 'sf-list', role: 'list' });
    const info = h('div', { class: 'sf-info' });
    const preview = h('pre', { class: 'sf-preview mono', hidden: true });
    const body = h('div', { class: 'sf' }, info, crumbs, list, preview);
    const m = IDE.modal({ title: IDE.t('Arquivos do sistema – {name}', { name: env.name }), size: 'xl', body, onClose: () => { S.dead = true; } });
    const base = '/api/env/' + env.id + '/files';

    async function refresh() {
      let st;
      try { st = await api(base + '/status'); } catch (e) { toastErr(e); return; }
      if (S.dead) return; S.st = st;
      IDE.clear(info);
      if (st.state === 'extracting') {
        IDE.add(info, h('div', { class: 'sf-prog' }, h('div', { class: 'row between' }, h('b', null, IDE.t(st.step || 'Extraindo…')), h('b', null, (st.pct || 0) + '%')), h('div', { class: 'bar big' }, h('i', { style: { width: (st.pct || 0) + '%' } })),
          h('p', { class: 'muted small' }, IDE.t('Fonte: {src}. Pode levar alguns minutos e alguns GB de disco.', { src: IDE.t(st.source || '') }))));
        IDE.clear(list); IDE.clear(crumbs); setTimeout(refresh, 1000); return;
      }
      if (st.state !== 'ready') {
        IDE.add(info, h('div', { class: 'sf-empty' }, h('div', { class: 'empty-ico' }, ic('folder', 36)),
          h('h3', null, 'Ver os arquivos do sistema'),
          h('p', null, IDE.t('O IDEmu descompacta os pacotes do firmware em arquivos normais, numa pasta que você navega aqui ou abre no Finder. Fonte: {src}.', { src: IDE.t(st.source || '') })),
          st.error ? h('div', { class: 'note danger' }, ic('alert', 16), h('span', null, st.error)) : null,
          h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'button', onclick: (e) => extract(e.currentTarget) }, ic('folder', 16), 'Extrair arquivos')),
          h('p', { class: 'muted small mono wrapany' }, st.path)));
        IDE.clear(list); IDE.clear(crumbs); return;
      }
      IDE.add(info, h('div', { class: 'row between sf-bar' },
        h('span', { class: 'muted small' }, IDE.t('{n} arquivos · {size}', { n: IDE.fmtNum ? IDE.fmtNum(st.files, 0) : st.files, size: IDE.fmtSize(st.bytes) })),
        h('span', { class: 'row tight' },
          h('button', { class: 'btn sm', type: 'button', onclick: () => reveal(S.path) }, ic('folder', 14), 'Mostrar no Finder'),
          h('button', { class: 'btn sm ghost-danger', type: 'button', onclick: removeAll }, ic('trash', 14), 'Apagar a extração'))));
      load(S.path);
    }
    async function extract(b) {
      await IDE.busy(b, async () => { try { await post(base + '/extract'); } catch (e) { toastErr(e); } });
      refresh();
    }
    async function removeAll() {
      if (!await IDE.confirm({ title: 'Apagar a extração', message: IDE.t('Apagar a pasta com os arquivos extraídos ({size})? Os pacotes originais e o ambiente não mudam.', { size: IDE.fmtSize((S.st || {}).bytes || 0) }), confirmLabel: 'Apagar', danger: true, icon: 'trash' })) return;
      try { await post(base + '/remove'); S.path = ''; refresh(); } catch (e) { toastErr(e); }
    }
    async function reveal(p) { try { await post(base + '/reveal', { path: p }); } catch (e) { toastErr(e); } }
    async function load(p) {
      let r;
      try { r = await api(base + '?path=' + encodeURIComponent(p || '')); } catch (e) { toastErr(e); return; }
      if (S.dead) return;
      S.path = r.path; preview.hidden = true;
      IDE.clear(crumbs);
      const parts = r.path ? r.path.split('/') : [];
      crumbs.appendChild(h('button', { class: 'link', type: 'button', onclick: () => load('') }, ic('folder', 14), IDE.t('raiz')));
      parts.forEach((n, i) => { crumbs.appendChild(h('span', { class: 'muted' }, ' / ')); crumbs.appendChild(h('button', { class: 'link', type: 'button', onclick: () => load(parts.slice(0, i + 1).join('/')) }, n)); });
      IDE.clear(list);
      if (r.parent != null) list.appendChild(h('button', { class: 'sf-row', type: 'button', onclick: () => load(r.parent) }, ic('back', 16), h('span', { class: 'sf-n' }, '..'), h('span'), h('span')));
      if (!r.entries.length) list.appendChild(h('div', { class: 'muted small sf-none' }, 'Pasta vazia.'));
      r.entries.forEach((e) => {
        const rel = (r.path ? r.path + '/' : '') + e.name;
        const row = h('div', { class: 'sf-row' + (e.dir ? ' dir' : ''), role: 'listitem' },
          ic(e.dir ? 'folder' : e.link != null ? 'link' : 'file', 16),
          e.dir ? h('button', { class: 'link sf-n', type: 'button', onclick: () => load(rel) }, e.name) : h('span', { class: 'sf-n mono' }, e.name, e.link != null ? h('span', { class: 'muted' }, ' → ' + e.link) : null),
          h('span', { class: 'muted small mono' }, e.dir || e.link != null ? '' : IDE.fmtSize(e.size)),
          h('span', { class: 'sf-act' }, e.dir || e.link != null ? null : [
            h('button', { class: 'icon-btn', type: 'button', title: IDE.t('Ver'), 'aria-label': IDE.t('Ver'), onclick: () => view(rel, e) }, ic('expand', 14)),
            h('a', { class: 'icon-btn', href: base + '/raw?path=' + encodeURIComponent(rel), title: IDE.t('Baixar'), 'aria-label': IDE.t('Baixar'), download: e.name }, ic('upload', 14)),
            h('button', { class: 'icon-btn', type: 'button', title: IDE.t('Mostrar no Finder'), 'aria-label': IDE.t('Mostrar no Finder'), onclick: () => reveal(rel) }, ic('folder', 14))]));
        list.appendChild(row);
      });
    }
    async function view(rel, e) {
      if (e.size > 2 * 1024 * 1024) { toast('Arquivo grande: use Baixar ou Mostrar no Finder.', 'info'); return; }
      try {
        const r = await fetch(base + '/raw?inline=1&path=' + encodeURIComponent(rel), { cache: 'no-store' });
        if (!r.ok) throw new Error(IDE.t('Erro {status} do servidor.', { status: r.status }));
        const ct = r.headers.get('Content-Type') || '';
        if (ct.startsWith('image/')) {
          const url = URL.createObjectURL(await r.blob());
          IDE.modal({ title: e.name, size: 'lg', body: h('img', { src: url, class: 'sf-img', alt: e.name }), onClose: () => URL.revokeObjectURL(url) });
          return;
        }
        const buf = new Uint8Array(await r.arrayBuffer());
        const bin = ct.startsWith('application/octet-stream') && buf.slice(0, 4096).some((c) => c === 0);
        preview.textContent = bin ? hexdump(buf.slice(0, 4096)) + (buf.length > 4096 ? '\n…' : '') : new TextDecoder('utf-8').decode(buf.slice(0, 256 * 1024));
        preview.hidden = false; preview.scrollIntoView({ block: 'nearest' });
      } catch (er) { toastErr(er); }
    }
    function hexdump(b) {
      let s = '';
      for (let i = 0; i < b.length; i += 16) {
        const row = Array.from(b.slice(i, i + 16));
        s += i.toString(16).padStart(8, '0') + '  ' + row.map((x) => x.toString(16).padStart(2, '0')).join(' ').padEnd(48) + '  ' + row.map((x) => (x >= 32 && x < 127 ? String.fromCharCode(x) : '.')).join('') + '\n';
      }
      return s;
    }
    refresh();
    return m;
  };
})(window.IDE);
