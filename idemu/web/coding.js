'use strict';
/* IDEmu – tela "Coding": parâmetros do CAFD da head unit, alterações pendentes, backups e flash. */
(function (IDE) {
  const { h, ic, api, post, toast, toastErr } = IDE;
  const t = (s, v) => IDE.t(s, v);
  const PAGE = 150;

  function mount(root, routeArg) {
    const eid = routeArg || IDE.state.running || (IDE.state.envs[0] && IDE.state.envs[0].id);
    const S = { data: null, pending: {}, cat: 'popular', query: '', shown: PAGE, dead: false };
    const page = h('div', { class: 'page wide coding-page' });
    root.appendChild(page);
    if (!eid) { page.appendChild(h('div', { class: 'placeholder' }, 'Create an environment first.')); return {}; }
    const env = () => IDE.envById(eid) || { id: eid, name: eid };

    const titleEl = h('h1', null, t('Coding'));
    const subEl = h('p', { class: 'sub' });
    const backupsBtn = h('button', { class: 'btn', type: 'button', onclick: openBackups }, ic('layers', 16), 'Backups');
    const exportBtn = h('button', { class: 'btn', type: 'button', onclick: exportCoding }, ic('upload', 16), 'Export');
    const fileIn = h('input', { type: 'file', accept: '.json,application/json', hidden: true, onchange: importCoding });
    const importBtn = h('button', { class: 'btn', type: 'button', onclick: () => fileIn.click() }, ic('file', 16), 'Import');
    const resetBtn = h('button', { class: 'btn ghost-danger', type: 'button', onclick: resetFactory }, ic('refresh', 16), 'Reset to factory');
    const search = h('input', { class: 'input', type: 'search', placeholder: 'Search parameters, e.g. video, language, compass', 'aria-label': 'Search parameters' });
    const side = h('nav', { class: 'cod-side', 'aria-label': 'Parameter groups' });
    const list = h('div', { class: 'cod-list' });
    const countEl = h('span', { class: 'muted small' });
    const pendEl = h('div', { class: 'cod-pend-t' });
    const discardBtn = h('button', { class: 'btn', type: 'button', onclick: () => { S.pending = {}; render(); } }, 'Discard');
    const flashBtn = h('button', { class: 'btn primary lg', type: 'button', onclick: confirmFlash }, ic('send', 18), 'Flash to head unit');
    const bar = h('div', { class: 'cod-bar card' }, pendEl, h('div', { class: 'spacer' }), discardBtn, flashBtn);

    IDE.add(page,
      h('div', { class: 'page-head' }, h('div', null, titleEl, subEl), h('div', { class: 'row' }, backupsBtn, exportBtn, importBtn, fileIn, resetBtn)),
      bar,
      h('div', { class: 'cod-grid' },
        h('aside', { class: 'cod-aside card' }, search, side),
        h('section', { class: 'cod-main card' }, h('div', { class: 'cod-head' }, h('b', { class: 'js-cat' }), countEl), list)));
    let qT;
    search.addEventListener('input', () => { clearTimeout(qT); qT = setTimeout(() => { S.query = search.value.trim().toLowerCase(); S.shown = PAGE; renderList(); }, 120); });

    const param = (n) => S.data.params.find((p) => p.name === n);
    const valueOf = (p) => (Object.prototype.hasOwnProperty.call(S.pending, p.name) ? S.pending[p.name] : p.value);
    const isChanged = (p) => Object.prototype.hasOwnProperty.call(S.pending, p.name);
    const differs = (p) => !p.virtual && p.factory != null && valueOf(p) !== p.factory;
    const optLabel = (p, v) => { const o = (p.options || []).find((x) => x.value === v); return o ? t(o.label) : (v == null ? '–' : String(v)); };

    function setValue(p, v) {
      if (v === p.value) delete S.pending[p.name]; else S.pending[p.name] = v;
      renderBar(); renderSide();
      const row = list.querySelector('[data-p="' + p.name + '"]');
      if (row) row.replaceWith(rowEl(p));
    }

    function control(p) {
      const v = valueOf(p), opts = p.options || [];
      const lbl = t(p.label);
      if (!p.virtual && opts.length === 2 && opts[0].value === 0 && opts[1].value === 1 && p.bits === 1) {
        const cb = h('input', { type: 'checkbox', checked: v === 1, 'aria-label': lbl, onchange: () => setValue(p, cb.checked ? 1 : 0) });
        return h('label', { class: 'switch' }, cb, h('span', { class: 'track' }), h('span', { class: 'sw-lab' }, optLabel(p, v)));
      }
      const known = opts.some((o) => o.value === v);
      if (opts.length) {
        const sel = h('select', { class: 'input sm', 'aria-label': lbl, onchange: () => { const raw = sel.value; if (raw === '__n') setValue(p, known ? v : v); else setValue(p, p.virtual ? raw : Number(raw)); } },
          !known && v != null ? h('option', { value: '__n', selected: true }, String(v)) : null,
          !known && v == null ? h('option', { value: '__n', selected: true }, '–') : null,
          opts.map((o) => h('option', { value: o.value, selected: o.value === v }, t(o.label))));
        if (p.bits >= 3 && !p.virtual) {
          const num = h('input', { class: 'input sm num', type: 'number', min: 0, max: p.max, value: v == null ? '' : v, 'aria-label': lbl + ' (' + t('number') + ')', onchange: () => { const n = Number(num.value); if (Number.isInteger(n) && n >= 0 && n <= p.max) setValue(p, n); else { toast(t('Value must be between 0 and {max}.', { max: p.max }), 'error'); num.value = v == null ? '' : v; } } });
          return h('div', { class: 'cod-ctl' }, sel, num);
        }
        return sel;
      }
      const num = h('input', { class: 'input sm num', type: 'number', min: 0, max: p.max, value: v == null ? '' : v, 'aria-label': lbl, onchange: () => { const n = Number(num.value); if (Number.isInteger(n) && n >= 0 && n <= p.max) setValue(p, n); else toast(t('Value must be between 0 and {max}.', { max: p.max }), 'error'); } });
      return num;
    }
    function rowEl(p) {
      const chg = isChanged(p), dif = differs(p);
      return h('div', { class: 'cod-row' + (chg ? ' chg' : ''), 'data-p': p.name },
        h('div', { class: 'cod-t' },
          h('div', { class: 'cod-name' }, h('b', null, t(p.label)), chg ? IDE.badge(t('Pending'), 'warn') : null),
          h('div', { class: 'cod-raw mono' }, p.virtual ? 'LANGUAGE_*' : p.name),
          p.desc ? h('div', { class: 'cod-desc muted small' }, t(p.desc)) : null),
        h('div', { class: 'cod-v' }, control(p),
          h('div', { class: 'cod-fac small muted' },
            p.virtual ? null : (p.factory == null ? t('Factory value unknown') : t('Factory: {v}', { v: optLabel(p, p.factory) })),
            dif ? h('button', { class: 'link', type: 'button', onclick: () => setValue(p, p.factory) }, t('Use factory value')) : null,
            chg ? h('button', { class: 'link', type: 'button', onclick: () => { delete S.pending[p.name]; renderBar(); renderSide(); const r = list.querySelector('[data-p="' + p.name + '"]'); if (r) r.replaceWith(rowEl(p)); } }, t('Undo')) : null)));
    }
    function matches(p) {
      const q = S.query;
      if (q) return p.name.toLowerCase().includes(q) || t(p.label).toLowerCase().includes(q) || (p.desc && t(p.desc).toLowerCase().includes(q));
      if (S.cat === 'popular') return !!p.popular;
      if (S.cat === 'coded') return p.coded && !p.virtual;
      if (S.cat === 'pending') return isChanged(p);
      if (S.cat === 'all') return true;
      if (S.cat.startsWith('pop:')) return p.popular === S.cat.slice(4);
      return p.group === S.cat;
    }
    function catLabel() {
      if (S.query) return t('Search results');
      if (S.cat === 'popular') return t('Popular');
      if (S.cat === 'coded') return t('Coded in this car');
      if (S.cat === 'pending') return t('Pending changes');
      if (S.cat === 'all') return t('All parameters');
      if (S.cat.startsWith('pop:')) return t(S.cat.slice(4));
      const g = S.data.groups.find((x) => x.id === S.cat); return g ? t(g.label) : S.cat;
    }
    function renderList() {
      IDE.clear(list);
      page.querySelector('.js-cat').textContent = catLabel();
      let items = S.data.params.filter(matches);
      if (S.cat === 'popular' && !S.query) {
        const ord = {}; S.data.popular_order.forEach((n, i) => { ord[n] = i; });
        items.sort((a, b) => ord[a.name] - ord[b.name]);
        let last = null; const frag = document.createDocumentFragment();
        items.forEach((p) => { if (p.popular !== last) { last = p.popular; frag.appendChild(h('div', { class: 'cod-sect' }, t(last))); } frag.appendChild(rowEl(p)); });
        list.appendChild(frag);
        countEl.textContent = t(items.length === 1 ? '1 parameter' : '{n} parameters', { n: items.length });
        return;
      }
      countEl.textContent = t(items.length === 1 ? '1 parameter' : '{n} parameters', { n: items.length });
      if (!items.length) { list.appendChild(h('div', { class: 'placeholder' }, S.cat === 'pending' && !S.query ? t('No pending changes.') : t('Nothing matches this search.'))); return; }
      const frag = document.createDocumentFragment();
      items.slice(0, S.shown).forEach((p) => frag.appendChild(rowEl(p)));
      list.appendChild(frag);
      if (items.length > S.shown) list.appendChild(h('button', { class: 'btn cod-more', type: 'button', onclick: () => { S.shown += PAGE; renderList(); } }, t('Show more ({n} left)', { n: items.length - S.shown })));
    }
    function renderSide() {
      IDE.clear(side);
      const item = (id, label, icon, n) => h('button', { type: 'button', class: 'cod-cat' + (S.cat === id && !S.query ? ' on' : ''), onclick: () => { S.cat = id; S.query = ''; search.value = ''; S.shown = PAGE; renderSide(); renderList(); } },
        icon ? ic(icon, 15) : null, h('span', null, label), n != null ? h('span', { class: 'cnt' }, String(n)) : null);
      const P = S.data.params, np = Object.keys(S.pending).length;
      IDE.add(side, item('popular', t('Popular'), 'target', P.filter((p) => p.popular).length));
      S.data.popular_groups.forEach((g) => side.appendChild(item('pop:' + g, t(g), null, P.filter((p) => p.popular === g).length)));
      IDE.add(side, h('div', { class: 'cod-sep' }), item('pending', t('Pending changes'), 'alert', np), item('coded', t('Coded in this car'), 'check', P.filter((p) => p.coded && !p.virtual).length), item('all', t('All parameters'), 'menu', P.length), h('div', { class: 'cod-sep lbl' }, t('CAFD groups')));
      S.data.groups.forEach((g) => side.appendChild(item(g.id, t(g.label), null, P.filter((p) => p.group === g.id).length)));
    }
    function renderBar() {
      const n = Object.keys(S.pending).length;
      IDE.clear(pendEl);
      IDE.add(pendEl, n ? h('b', null, t(n === 1 ? '1 change pending' : '{n} changes pending', { n })) : h('span', { class: 'muted' }, t('No pending changes.')),
        h('span', { class: 'muted small' }, S.data.running ? t('Flashing restarts the head unit.') : t('Saved now and applied the next time you start this car.')));
      flashBtn.disabled = !n; discardBtn.disabled = !n;
    }
    function render() { renderBar(); renderSide(); renderList(); }
    function renderHead() {
      const e = env();
      titleEl.textContent = t('Coding');
      subEl.textContent = [e.name, e.chassis, e.coding && e.coding.vin].filter(Boolean).join(' · ');
    }

    /* ---------- flash ---------- */
    function changesTable() {
      return h('div', { class: 'cod-summary' }, Object.keys(S.pending).map((n) => { const p = param(n); return h('div', { class: 'cod-sum-row' }, h('div', null, h('b', null, t(p.label)), h('div', { class: 'mono small muted' }, p.virtual ? 'LANGUAGE_*' : n)), h('div', { class: 'cod-sum-v' }, h('span', { class: 'muted' }, optLabel(p, p.value)), ic('chevR', 14), h('b', null, optLabel(p, S.pending[n])))); }));
    }
    async function confirmFlash() {
      const risky = Object.keys(S.pending).some((n) => ['BAUREIHE', 'HMI_BRAND', 'HMI_ID_VERSION', 'DISPLAY_SIZE_RESOLUTION', 'CID_DISPLAY_RES'].includes(n));
      IDE.modal({
        title: t('Flash the coding?'), size: 'md',
        body: h('div', null,
          h('p', { class: 'confirm-msg' }, S.data.running ? t('A backup is made first. The head unit restarts and takes about 45 seconds to come back.') : t('A backup is made first. This car is off, so the change applies the next time it starts.')),
          risky ? h('div', { class: 'note warn' }, ic('alert', 16), h('span', null, t('You are changing a value that defines the car or the interface. The head unit may stop starting; if that happens, restore the backup.'))) : null,
          changesTable()),
        actions: [{ label: t('Cancel') }, { label: t('Flash'), kind: 'primary', icon: 'send', onClick: () => startFlash({ changes: S.pending }) }],
      });
    }
    async function startFlash(body) {
      try { await post('/api/env/' + eid + '/coding/flash', body); } catch (e) { toastErr(e); return; }
      S.pending = {}; flashProgress();
    }
    function flashProgress() {
      const stepsEl = h('ol', { class: 'cod-steps' });
      const msg = h('div');
      let closeOk = false;
      const m = IDE.modal({ title: t('Flashing'), size: 'md', persistent: true, body: h('div', null, stepsEl, msg), onClose: () => { closeOk = true; } });
      const stop = IDE.loop(async () => {
        const j = await api('/api/env/' + eid + '/coding/flash');
        if (closeOk || !document.body.contains(m.el)) { stop(); return; }      // diálogo fechado ou tela trocada
        IDE.clear(stepsEl);
        (j.steps || []).forEach((s, i) => stepsEl.appendChild(h('li', { class: i < j.step ? 'done' : (i === j.step && j.state === 'running' ? 'cur' : (j.state === 'error' && i === j.step ? 'err' : '')) }, i < j.step ? ic('check', 15) : (i === j.step && j.state === 'running' ? h('span', { class: 'spinner sm' }) : h('span', { class: 'cod-dot' })), t(s))));
        if (j.state === 'running') return;
        stop(); IDE.clear(msg);
        if (j.state === 'done') {
          IDE.add(msg, h('div', { class: 'note ok' }, ic('check', 16), h('span', null, j.restarted ? (j.verified ? t('Done. The HMI read {n} coding rows after restarting.', { n: j.rows_read }) : t('Done.')) : t('Saved. It applies the next time you start this car.'))));
          (j.warnings || []).forEach((w) => msg.appendChild(h('div', { class: 'note warn' }, ic('alert', 16), h('span', null, w))));
          const b = [h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, t('Close'))];
          if (j.restarted) b.push(h('button', { class: 'btn primary', type: 'button', onclick: () => { m.close(); IDE.go('execucao'); } }, ic('play', 16), t('Open head unit')));
          msg.appendChild(h('div', { class: 'row end cod-done' }, b));
        } else {
          IDE.add(msg, h('div', { class: 'note danger' }, ic('alert', 16), h('span', null, t(j.error || 'The flash failed.'))));
          const b = [h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, t('Close'))];
          if (j.backup) b.push(h('button', { class: 'btn primary', type: 'button', onclick: () => { m.close(); startFlash({ restore: j.backup }); } }, ic('refresh', 16), t('Restore the backup')));
          msg.appendChild(h('div', { class: 'row end cod-done' }, b));
        }
        await load();
        await IDE.refreshState().catch(() => {});
      }, 500);
    }

    /* ---------- backups / importar / exportar ---------- */
    function openBackups() {
      const body = h('div');
      const m = IDE.modal({ title: t('Coding backups'), size: 'md', body });
      function paint() {
        IDE.clear(body);
        const mk = h('button', { class: 'btn', type: 'button', onclick: async () => { try { const r = await post('/api/env/' + eid + '/coding/backup', { note: 'Manual backup' }); S.data.backups = r.backups; toast(t('Backup created.'), 'success'); paint(); } catch (e) { toastErr(e); } } }, ic('plus', 16), t('Create backup now'));
        body.appendChild(h('p', { class: 'help' }, t('A backup is created automatically before every flash. The 30 most recent are kept.')));
        body.appendChild(h('div', { class: 'row' }, mk));
        if (!S.data.backups.length) body.appendChild(h('div', { class: 'placeholder' }, t('No backups yet.')));
        S.data.backups.forEach((b) => body.appendChild(h('div', { class: 'rec-row' }, ic('file', 16),
          h('div', { class: 'rec-t' }, h('b', null, IDE.fmtDate(b.created ? new Date(b.created * 1000).toISOString() : '')), h('span', { class: 'muted small' }, t(b.note || '') + ' · ' + t('{n} coded parameters', { n: b.changed }))),
          h('button', { class: 'btn sm', type: 'button', onclick: async () => {
            if (!await IDE.confirm({ title: t('Restore this backup?'), message: S.data.running ? t('The head unit restarts with this coding.') : t('This coding applies the next time you start this car.'), confirmLabel: t('Restore') })) return;
            m.close(); startFlash({ restore: b.id });
          } }, ic('refresh', 14), t('Restore')))));
      }
      paint();
    }
    function exportCoding() {
      const e = env();
      const data = { idemu_coding: 1, chassis: e.chassis, vin: e.coding && e.coding.vin, language: e.coding && e.coding.language, extra: (e.coding && e.coding.extra) || {} };
      const a = h('a', { href: URL.createObjectURL(new Blob([JSON.stringify(data, null, 1)], { type: 'application/json' })), download: (e.id || 'coding') + '-coding.json' });
      document.body.appendChild(a); a.click(); a.remove();
      toast(t('Coding exported.'), 'success');
    }
    async function importCoding() {
      const f = fileIn.files && fileIn.files[0]; fileIn.value = '';
      if (!f) return;
      try {
        const j = JSON.parse(await f.text());
        if (!j || !j.idemu_coding || typeof j.extra !== 'object') throw new Error('x');
        let n = 0, skip = 0;
        Object.keys(j.extra).forEach((name) => {
          const p = param(name); if (!p) { skip++; return; }
          let v = j.extra[name];
          if (typeof v === 'string') { const o = p.options.find((x) => x.raw === v); v = o ? o.value : null; }
          if (typeof v !== 'number' || v === p.value) { if (v == null) skip++; return; }
          S.pending[name] = v; n++;
        });
        const lp = param('language');
        if (j.language && lp && j.language !== lp.value) { S.pending.language = j.language; n++; }
        S.cat = 'pending'; render();
        toast(t('{n} changes imported. Review and flash them.', { n }) + (skip ? ' ' + t('{n} ignored.', { n: skip }) : ''), n ? 'success' : 'info');
      } catch (e) { toast(t('This file is not an IDEmu coding export.'), 'error'); }
    }
    async function resetFactory() {
      if (!await IDE.confirm({ title: t('Reset to factory?'), message: t('Removes every parameter coded by hand and keeps only what defines this car (model, language, display). A backup is made first.'), confirmLabel: t('Reset'), danger: true, icon: 'refresh' })) return;
      startFlash({ reset: true });
    }

    async function load() {
      const d = await api('/api/env/' + eid + '/coding');
      if (S.dead) return;
      S.data = d; renderHead(); render();
    }
    list.appendChild(h('div', { class: 'loading' }, t('Reading the coding…')));
    renderHead();
    load().then(() => { if (S.data.flash && S.data.flash.state === 'running') flashProgress(); }).catch((e) => { IDE.clear(list); list.appendChild(h('div', { class: 'note danger' }, ic('alert', 16), h('span', null, e.message))); });
    const offState = IDE.on('state', () => { if (S.data) { const r = !!IDE.state.running && IDE.state.running === eid; if (r !== S.data.running) { S.data.running = r; renderBar(); } } renderHead(); });
    return { unmount() { S.dead = true; offState(); } };
  }
  IDE.views.coding = { mount };
})(window.IDE);
