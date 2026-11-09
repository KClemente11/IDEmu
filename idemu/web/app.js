'use strict';
/* IDEmu – núcleo: estado global, roteador (hash) e tela "Ambientes". */
(function (IDE) {
  const { h, ic, api, post, toast, toastErr } = IDE;

  /* ------------------------------------------------------------------ estado global */
  IDE.state = { settings: { psdz_path: null }, envs: [], running: null, version: '', loaded: false };
  let refreshing = null;
  IDE.refreshState = function () {
    if (refreshing) return refreshing;
    refreshing = api('/api/state').then((s) => {
      IDE.state = Object.assign({ loaded: true }, s, { loaded: true });
      IDE.emit('state', IDE.state);
      return IDE.state;
    }).finally(() => { refreshing = null; });
    return refreshing;
  };
  IDE.envById = (id) => IDE.state.envs.find((e) => e.id === id) || null;

  /** Catálogo (cache curto; psdz_ok vem dele). */
  IDE.loadCatalog = async function (force) {
    if (!force && IDE.catalog && Date.now() - IDE.catalogAt < 8000) return IDE.catalog;
    const c = await api('/api/catalog');
    IDE.catalog = c; IDE.catalogAt = Date.now();
    return c;
  };

  /* ------------------------------------------------------------------ roteador */
  const ROUTES = { ambientes: 'envs', novo: 'wizard', execucao: 'run', coding: 'coding', estatisticas: 'stats' };
  let current = null, currentName = null;
  IDE.go = function (name) { if (location.hash !== '#/' + name) location.hash = '#/' + name; else route(); };
  function routeName() {
    const n = (location.hash.replace(/^#\/?/, '') || '').split('/')[0];
    return ROUTES[n] ? n : null;
  }
  function route() {
    let n = routeName();
    if (!n) n = IDE.state.running ? 'execucao' : 'ambientes';
    const view = ROUTES[n];
    if (current) { try { current.unmount && current.unmount(); } catch (e) { console.error(e); } current = null; }
    const root = document.getElementById('view');
    IDE.clear(root);
    IDE.clear(document.getElementById('modal-root'));      // diálogo aberto não sobrevive à troca de tela
    currentName = n;
    document.querySelectorAll('#nav a').forEach((a) => a.classList.toggle('active', a.dataset.route === n || (n === 'novo' && a.dataset.route === 'ambientes')));
    document.body.dataset.view = n;
    current = IDE.views[view].mount(root, (location.hash.replace(/^#\/?/, '').split('/')[1] || null)) || null;
    window.scrollTo(0, 0);
  }
  IDE.currentRoute = () => currentName;

  function updateChrome() {
    const nr = document.getElementById('nav-run');
    nr.hidden = !(IDE.state.running || currentName === 'execucao');
    const env = IDE.state.running ? IDE.envById(IDE.state.running) : null;
    document.getElementById('nav-run-name').textContent = env ? env.name : '';
    document.getElementById('nav-coding').hidden = !IDE.state.envs.length;
    const ls = document.getElementById('ui-lang'); if (ls.value !== IDE.lang()) ls.value = IDE.lang();
  }
  IDE.on('state', updateChrome);
  IDE.on('conn', (up) => {
    const c = document.getElementById('conn');
    c.classList.toggle('down', !up);
    document.getElementById('conn-text').textContent = IDE.t(up ? 'Conectado' : 'Reconectando…');
    c.title = IDE.t(up ? 'Conectado ao servidor do IDEmu' : 'Sem resposta do servidor. Tentando reconectar automaticamente.');
  });

  /* ------------------------------------------------------------------ tela: Ambientes */
  const BUILD_BADGE = {
    none: ['Não compilado', 'muted'], building: ['Compilando', 'info'], ready: ['Pronto', 'ok'], error: ['Erro no build', 'danger'],
  };
  const BRAND = { bmw: 'BMW', bmw_i: 'BMW i', bmw_m: 'BMW M', mini: 'MINI', rr: 'Rolls-Royce' };
  IDE.brandName = (b) => BRAND[b] || String(b || '').toUpperCase();

  function envsMount(root) {
    const page = h('div', { class: 'page' });
    const grid = h('div', { class: 'env-grid' });
    IDE.add(page,
      h('div', { class: 'page-head' },
        h('div', null, h('h1', null, 'Ambientes'),
          h('p', { class: 'sub' }, 'Cada ambiente é um carro virtual: modelo, arquivos SWFL e codificação. Compile, inicie e use.')),
        h('button', { class: 'btn primary lg', onclick: () => { IDE.wizard.reset(); IDE.go('novo'); } }, ic('plus', 18), 'Novo ambiente')),
      grid);
    root.appendChild(page);

    const cards = new Map();
    const sigOf = (e) => JSON.stringify([e.id, e.name, e.series, e.chassis, e.brand, e.model_name, e.coding, e.net, e.build.state, e.build.error, e.build.built_at, e.snapshot, e.fast_boot, e.files_ok, e.runtime_available,
      IDE.state.running === e.id, !!IDE.state.running, e.created]);

    function btn(cls, icon, label, fn, title) {
      const b = h('button', { class: 'btn ' + cls, type: 'button', title: title || label }, ic(icon, 16), label);
      b.addEventListener('click', () => fn(b));
      return b;
    }
    function huName(v) { const x = ((IDE.catalog && IDE.catalog.hu_variants) || []).find((y) => y.id === (v || 'professional')); return x ? x.name : 'Navigation Professional'; }
    function bootRow(e, running) {
      const sn = e.snapshot || {};
      if (e.kind === 'cic' || e.kind === 'mgu22' || sn.supported === false) return null;
      const cb = h('input', { type: 'checkbox', checked: e.fast_boot !== false, disabled: running, 'aria-label': 'Fast boot', onchange: async () => { try { await post('/api/env/' + e.id + '/update', { fast_boot: cb.checked }); await IDE.refreshState(); } catch (er) { toastErr(er); } } });
      const cold = h('button', { class: 'link', type: 'button', disabled: running || !!IDE.state.running || e.runtime_available === false, onclick: (ev) => startEnv(e, ev.currentTarget, true) }, 'Full boot');
      const del = sn.valid ? h('button', { class: 'link', type: 'button', disabled: running, onclick: async () => { try { await post('/api/env/' + e.id + '/snapshot/delete'); await IDE.refreshState(); } catch (er) { toastErr(er); } } }, 'Delete saved state') : null;
      return h('div', { class: 'env-boot' },
        h('label', { class: 'check' }, cb, h('span', null, 'Fast boot')),
        e.fast_boot === false ? null : (sn.valid ? IDE.badge(IDE.t('Ready · {size}', { size: IDE.fmtSize(sn.size) }), 'ok') : IDE.badge('Saved on next start', 'muted')),
        cold, del);
    }
    function cardEl(e) {
      const running = IDE.state.running === e.id;
      const otherRunning = !!IDE.state.running && !running;
      const bs = e.build.state;
      const [bt, bk] = running ? ['Em execução', 'live'] : (BUILD_BADGE[bs] || BUILD_BADGE.none);
      const c = e.coding || {}, n = e.net || {};
      const actions = [];
      if (running) {
        actions.push(btn('primary', 'play', 'Abrir execução', () => IDE.go('execucao')));
        actions.push(btn('danger-o', 'stop', 'Parar', (b) => stopEnv(e, b)));
      } else {
        const canStart = bs === 'ready' && !otherRunning && e.runtime_available !== false;
        const b = btn('success', 'play', 'Iniciar', (b) => startEnv(e, b),
          e.runtime_available === false ? 'Runtime unavailable on this host' :
            (bs !== 'ready' ? 'Compile o ambiente antes de iniciar' : (otherRunning ? 'Outro ambiente está em execução' : 'Iniciar o emulador')));
        b.disabled = !canStart;
        actions.push(b);
      }
      const bb = btn(bs === 'ready' || bs === 'error' ? '' : 'primary-o', 'wrench', bs === 'error' ? 'Tentar de novo' : (bs === 'ready' ? 'Recompilar' : 'Compilar'), (b) => buildEnv(e, b), 'Compilar (build) o ambiente');
      bb.disabled = bs === 'building' || running || e.files_ok === false;
      actions.push(bb);
      const bc = btn('', 'gear', 'Coding', () => IDE.go('coding/' + e.id), 'Edit the coding of this head unit');
      bc.disabled = bs !== 'ready' || e.kind === 'cic';
      if (e.kind === 'cic') bc.title = IDE.t('a edição de codificação ainda não existe para o iDrive 4');
      actions.push(bc);
      const bf = btn('', 'folder', 'Arquivos', () => IDE.sysFilesDialog(e), 'Ver os arquivos do sistema do iDrive, descompactados');
      bf.disabled = bs !== 'ready' && !!e.kind;
      const bv = btn('', 'target', 'VIN', () => IDE.vinDialog(e), 'Ajustar o ambiente ao carro pelo VIN'); bv.disabled = running || bs === 'building';
      actions.push(bf, bv);
      const bd = btn('', 'copy', 'Duplicar', () => dupEnv(e)); bd.disabled = running;
      const bx = btn('ghost-danger', 'trash', 'Excluir', () => delEnv(e)); bx.disabled = running;
      actions.push(bd, bx);
      const prog = h('div', { class: 'build-prog' + (bs === 'building' ? '' : ' hidden') },
        h('div', { class: 'bar' }, h('i', { class: 'js-pct', style: { width: (e.build.pct || 0) + '%' } })),
        h('div', { class: 'prog-txt' }, h('span', { class: 'js-step' }, e.build.step || 'Compilando…'), h('b', { class: 'js-pctn' }, (e.build.pct || 0) + '%')));
      return h('article', { class: 'card env-card' + (running ? ' is-running' : ''), 'data-id': e.id },
        h('header', { class: 'env-head' },
          h('div', { class: 'env-ico' }, ic('car', 24)),
          h('div', { class: 'env-title' }, h('h3', null, e.name),
            h('div', { class: 'env-sub' }, [e.chassis, IDE.brandName(e.brand), e.model_name].filter(Boolean).join(' · '))),
          IDE.badge(bt, bk)),
        h('dl', { class: 'kv' },
          h('div', null, h('dt', null, 'iDrive'), h('dd', null, IDE.genName(e.kind === 'cic' ? 'id4' : e.kind === 'mgu7' ? 'id7' : e.kind === 'mgu22' ? 'id8' : String(c.hmi_version || '').startsWith('id5') ? 'id5' : 'id6') + (e.kind === 'mgu7' ? ' · ' + IDE.t(e.role === 'rse' ? 'banco traseiro (RSE)' : 'tela central') : ''))),
          !e.kind ? h('div', null, h('dt', null, 'Head unit'), h('dd', null, huName(c.hu_variant))) : null,
          h('div', null, h('dt', null, 'Série'), h('dd', null, e.series || '–')),
          h('div', null, h('dt', null, 'VIN'), h('dd', { class: 'mono' }, c.vin || '–')),
          h('div', null, h('dt', null, 'Idioma / país'), h('dd', null, (c.language || '–') + ' · ' + (c.country || '–'))),
          !e.kind ? h('div', null, h('dt', null, 'Portas'), h('dd', { class: 'mono' }, 'SSH ' + n.ssh_port + ' · CAN ' + n.can_port + ' · GPS ' + n.gps_port)) : null,
          h('div', null, h('dt', null, 'Compilado em'), h('dd', null, IDE.fmtDate(e.build.built_at))),
          e.home ? h('div', null, h('dt', null, 'Pasta da VM'), h('dd', { class: 'mono wrapany', title: e.home + '/' + e.id }, e.home + '/' + e.id)) : null),
        prog,
        bs === 'ready' ? bootRow(e, running) : null,
        e.files_ok === false ? h('div', { class: 'note warn' }, ic('alert', 16),
          h('button', { class: 'link', type: 'button', onclick: () => document.getElementById('files-folder').click() }, 'Check required system files')) : null,
        bs === 'error' && e.build.error ? h('div', { class: 'note danger' }, ic('alert', 16), h('span', null, e.build.error)) : null,
        h('footer', { class: 'env-actions' }, actions));
    }
    function updateDyn(el, e) {
      const p = e.build.pct || 0;
      const i = el.querySelector('.js-pct'); if (i) i.style.width = p + '%';
      const s = el.querySelector('.js-step'); if (s) s.textContent = IDE.t(e.build.step || 'Compilando…');
      const n = el.querySelector('.js-pctn'); if (n) n.textContent = p + '%';
    }
    function renderEnvs() {
      const envs = IDE.state.envs;
      const ids = new Set(envs.map((e) => e.id));
      for (const [id, c] of cards) if (!ids.has(id)) { c.el.remove(); cards.delete(id); }
      let empty = grid.querySelector('.empty');
      if (!envs.length) {
        if (!empty) grid.appendChild(h('div', { class: 'empty' },
          h('div', { class: 'empty-ico' }, ic('car', 40)),
          h('h3', null, 'Nenhum ambiente ainda'),
          h('p', null, 'Crie o primeiro: escolha o modelo do carro, os arquivos SWFL e a codificação.'),
          h('button', { class: 'btn primary lg', onclick: () => { IDE.wizard.reset(); IDE.go('novo'); } }, ic('plus', 18), 'Criar primeiro ambiente')));
      } else if (empty) empty.remove();
      let prev = null;
      envs.forEach((e) => {
        const sig = sigOf(e);
        let c = cards.get(e.id);
        if (!c || c.sig !== sig) {
          const el = cardEl(e);
          if (c) c.el.replaceWith(el); else grid.appendChild(el);
          c = { el, sig }; cards.set(e.id, c);
        }
        updateDyn(c.el, e);
        if (prev ? prev.nextSibling !== c.el : grid.firstChild !== c.el) grid.insertBefore(c.el, prev ? prev.nextSibling : grid.firstChild);
        prev = c.el;
      });
    }

    async function startEnv(e, b, cold) {
      await IDE.busy(b, async () => {
        try { await post('/api/env/' + e.id + '/start', cold ? { cold: true } : {}); await IDE.refreshState().catch(() => {}); IDE.go('execucao'); } catch (er) { toastErr(er); }
      });
    }
    async function stopEnv(e, b) {
      if (!await IDE.confirm({ title: 'Parar o emulador', message: IDE.t('Parar o ambiente "{name}"? O estado do sistema convidado será perdido.', { name: e.name }), confirmLabel: 'Parar', danger: true, icon: 'stop' })) return;
      await IDE.busy(b, async () => {
        try { await post('/api/env/' + e.id + '/stop'); toast('Emulador parado.', 'success'); await IDE.refreshState().catch(() => {}); } catch (er) { toastErr(er); }
      });
    }
    async function buildEnv(e, b) {
      await IDE.busy(b, async () => {
        try { await post('/api/env/' + e.id + '/build'); toast(IDE.t('Build iniciado para "{name}".', { name: e.name }), 'info'); await IDE.refreshState().catch(() => {}); } catch (er) { toastErr(er); }
      });
    }
    async function dupEnv(e) {
      const name = await IDE.prompt({ title: 'Duplicar ambiente', message: 'Nome do novo ambiente:', value: IDE.t('{name} (cópia)', { name: e.name }), confirmLabel: 'Duplicar' });
      if (!name) return;
      try { await post('/api/env/' + e.id + '/duplicate', { name }); toast('Ambiente duplicado.', 'success'); await IDE.refreshState(); } catch (er) { toastErr(er); }
    }
    async function delEnv(e) {
      if (!await IDE.confirm({ title: 'Excluir ambiente', message: IDE.t('Excluir "{name}"? Os arquivos do ambiente serão removidos e isso não pode ser desfeito.', { name: e.name }), confirmLabel: 'Excluir', danger: true, icon: 'trash' })) return;
      try { await post('/api/env/' + e.id + '/delete'); toast('Ambiente excluído.', 'success'); await IDE.refreshState(); } catch (er) { toastErr(er); }
    }

    const off = IDE.on('state', () => { renderEnvs(); });
    renderEnvs();
    IDE.refreshState().catch(() => {});
    IDE.loadCatalog().then(() => { cards.clear(); IDE.clear(grid); renderEnvs(); }).catch(() => {});     // nomes dos tipos de head unit
    return { unmount() { off(); } };
  }
  IDE.views.envs = { mount: envsMount };

  /* ------------------------------------------------------------------ boot */
  window.addEventListener('hashchange', route);
  (async function init() {
    try { await IDE.refreshState(); } catch (e) { /* mostra a UI mesmo assim; o laço reconecta */ }
    IDE.setLang((IDE.state.settings && IDE.state.settings.ui_language) || 'en');
    document.title = IDE.t(document.title);
    document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = IDE.t(el.textContent.trim()); });
    document.querySelectorAll('aside [data-ic]').forEach((el) => { el.innerHTML = IDE.icon(el.dataset.ic, 15); });
    document.querySelectorAll('aside [title], aside [aria-label]').forEach((el) => {
      ['title', 'aria-label'].forEach((a) => { if (el.hasAttribute(a)) el.setAttribute(a, IDE.t(el.getAttribute(a))); });
    });
    const langSel = document.getElementById('ui-lang');
    IDE.LANGS.forEach((l) => langSel.appendChild(IDE.h('option', { value: l.code }, l.name)));
    langSel.value = IDE.lang();
    langSel.addEventListener('change', async () => {
      if (langSel.value === IDE.lang()) return;
      try { await post('/api/settings', { ui_language: langSel.value }); location.reload(); } catch (e) { toastErr(e); langSel.value = IDE.lang(); }
    });
    document.getElementById('files-folder').addEventListener('click', () => {
      IDE.modal({ title: 'System files', size: 'lg', body: IDE.filesSetup({ onChange: () => IDE.refreshState().catch(toastErr) }) });
    });
    document.getElementById('theme-btn').addEventListener('click', () => IDE.themePicker(false));
    route(); updateChrome();
    document.getElementById('tour-btn').addEventListener('click', () => IDE.tour());
    if (!IDE.pref.get('onboarded', false)) IDE.onboarding();
    else if (IDE.pref.get('tourPending', false)) { IDE.pref.set('tourPending', false); setTimeout(() => IDE.tour(), 300); }
    IDE.loop(() => IDE.refreshState(), () => (document.hidden ? 4000 : (currentName === 'execucao' ? 2500 : 1500)));
  })();
})(window.IDE);
