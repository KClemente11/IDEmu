'use strict';
/* IDEmu – primeira abertura: configurações iniciais (idioma, tema, pasta de arquivos) e tour pelo app.
   IDE.onboarding() abre o assistente; IDE.tour() roda só o tour (botão "Tour…" da barra lateral). */
(function (IDE) {
  const { h, ic, post, toastErr } = IDE;

  /* ------------------------------------------------------------------ assistente de configurações iniciais */
  IDE.onboarding = function () {
    let step = 0, langChanged = false, finished = false;
    const startLang = IDE.lang(), startTheme = IDE.themeId();
    const body = h('div', { class: 'ob' });
    let grid = null;
    const STEPS = ['lang', 'theme', 'files', 'done'];

    const modal = IDE.modal({
      title: 'Bem-vindo ao IDEmu', size: 'lg', persistent: true, body,
      onClose: () => { if (!finished) finish(false); },
    });

    function dots() { return h('div', { class: 'ob-dots', 'aria-hidden': 'true' }, ...STEPS.map((_, i) => h('i', { class: i === step ? 'on' : (i < step ? 'past' : '') }))); }
    function nav(next, opts) {
      opts = opts || {};
      const back = step > 0 ? h('button', { class: 'btn', type: 'button', onclick: () => go(step - 1) }, 'Voltar') : h('span');
      const nx = h('button', { class: 'btn primary', type: 'button', onclick: next }, opts.label || 'Avançar');
      return h('div', { class: 'ob-foot' }, back, dots(), nx);
    }
    function go(n) { step = n; render(); }

    function render() {
      IDE.clear(body);
      const id = STEPS[step];
      modal.setTitle(id === 'done' ? 'Tudo pronto!' : 'Bem-vindo ao IDEmu');
      if (id === 'lang') {
        const cur = IDE.lang();
        body.appendChild(h('p', { class: 'ob-lead' }, 'Vamos deixar tudo pronto em poucos passos. Você pode mudar qualquer coisa depois.'));
        body.appendChild(h('h3', null, 'Idioma'));
        body.appendChild(h('p', { class: 'muted small' }, 'Escolha o idioma da interface.'));
        body.appendChild(h('div', { class: 'lang-grid' }, ...IDE.LANGS.map((l) => {
          const b = h('button', { type: 'button', class: 'lang-opt' + (l.code === cur ? ' on' : ''), 'aria-pressed': l.code === cur ? 'true' : 'false', lang: l.code }, l.name);
          b.addEventListener('click', async () => {
            if (l.code === IDE.lang()) return;
            try { await post('/api/settings', { ui_language: l.code }); } catch (e) { toastErr(e); return; }
            IDE.setLang(l.code); langChanged = l.code !== startLang; render();
          });
          return b;
        })));
        body.appendChild(nav(() => go(1)));
      } else if (id === 'theme') {
        grid = IDE.themeGrid(IDE.themeId());
        body.appendChild(h('h3', null, 'Tema'));
        body.appendChild(h('p', { class: 'muted small' }, 'Você pode mudar isso depois no botão Tema, na barra lateral.'));
        body.appendChild(grid.el);
        body.appendChild(nav(() => { IDE.pref.set('theme', grid.value()); go(2); }));
      } else if (id === 'files') {
        body.appendChild(h('h3', null, 'Arquivos do sistema (opcional)'));
        body.appendChild(h('p', { class: 'muted small' }, 'Se você já baixou os arquivos de software da BMW (SWFL), escolha-os um a um ou deixe o app procurar numa pasta. Dá para fazer isso depois, em "Pasta de arquivos…".'));
        body.appendChild(IDE.filesSetup({}));
        body.appendChild(nav(() => go(3), { label: 'Avançar' }));
      } else {
        body.appendChild(h('div', { class: 'ob-done' }, h('div', { class: 'ob-badge' }, ic('check', 34)),
          h('h3', null, 'Quer um tour rápido pelo app?'),
          h('p', { class: 'muted' }, 'Leva menos de um minuto e mostra onde fica cada coisa.')));
        body.appendChild(h('div', { class: 'ob-foot' }, h('button', { class: 'btn', type: 'button', onclick: () => go(2) }, 'Voltar'), dots(),
          h('div', { class: 'ob-end' },
            h('button', { class: 'btn', type: 'button', onclick: () => finish(false) }, 'Pular o tour'),
            h('button', { class: 'btn primary', type: 'button', onclick: () => finish(true) }, 'Fazer o tour'))));
      }
    }

    function finish(tour) {
      if (finished) return; finished = true;
      if (IDE.pref.get('theme', null) == null) IDE.pref.set('theme', IDE.themeId());
      IDE.applyTheme(IDE.themeId());
      IDE.pref.set('onboarded', true);
      modal.close();
      if (langChanged || startLang !== IDE.lang()) { IDE.pref.set('tourPending', !!tour); location.reload(); return; }
      if (tour) setTimeout(() => IDE.tour(), 250);
    }
    render();
  };

  /* ------------------------------------------------------------------ tour com destaque */
  const TOUR = [
    { sel: '.brand', title: 'Bem-vindo ao IDEmu', text: 'O IDEmu emula a central multimídia de carros BMW (iDrive). Este menu leva você a cada tela do app.' },
    { sel: '#nav a[data-route="ambientes"]', title: 'Ambientes', text: 'Cada ambiente é um carro virtual: modelo, arquivos de software e codificação. Aqui você cria, liga, duplica e apaga ambientes. Com um ligado, a tela "Head unit" aparece no menu, com o display, o rotor e os botões.' },
    { sel: '.page-head .btn.primary', title: 'Novo ambiente', text: 'Comece por aqui: escolha a geração (iDrive 5, 6, 7 ou 8), o carro e os arquivos, e o IDEmu monta tudo.', route: 'ambientes' },
    { sel: 'a[data-route="estatisticas"]', title: 'Estatísticas avançadas', text: 'Veja desempenho, barramentos e dados do sistema em tempo real.' },
    { sel: '#files-folder', title: 'Pasta de arquivos', text: 'Aponte onde estão os arquivos de software da BMW (PSdZData). Os ambientes usam esses arquivos para montar o sistema.' },
    { sel: '#ui-lang', title: 'Idioma', text: 'Troque o idioma da interface a qualquer hora.' },
    { sel: '#theme-btn', title: 'Tema', text: 'Escolha entre Cupertino, Next Big Thing (iDrive 6) e Bavarian OS (iDrive 8).' },
    { sel: '#tour-btn', title: 'Pronto!', text: 'Para ver este tour de novo, use o botão "Tour…" na barra lateral. Bom proveito!' },
  ];
  let active = null;
  IDE.tour = function () {
    if (active) active.stop();
    if (IDE.currentRoute && IDE.currentRoute() !== 'ambientes') IDE.go('ambientes');
    const steps = TOUR.slice();
    let i = -1;
    const mask = h('div', { class: 'tour-mask' }), spot = h('div', { class: 'tour-spot' });
    const tTitle = h('b'), tText = h('p'), tCount = h('span', { class: 'muted small' });
    const bSkip = h('button', { class: 'btn ghost sm', type: 'button' }, 'Pular');
    const bBack = h('button', { class: 'btn sm', type: 'button' }, 'Voltar');
    const bNext = h('button', { class: 'btn primary sm', type: 'button' }, 'Avançar');
    const pop = h('div', { class: 'tour-pop', role: 'dialog', 'aria-live': 'polite' }, tTitle, tText, h('div', { class: 'tour-foot' }, tCount, h('div', { class: 'tour-btns' }, bSkip, bBack, bNext)));
    const root = document.body;
    function visible(el) { return el && el.getClientRects().length && !el.hidden; }
    function target(s) { const el = document.querySelector(s.sel); return visible(el) ? el : null; }
    function place() {
      const s = steps[i], el = target(s); if (!el) return;
      const r = el.getBoundingClientRect(), pad = 6;
      Object.assign(spot.style, { left: (r.left - pad) + 'px', top: (r.top - pad) + 'px', width: (r.width + pad * 2) + 'px', height: (r.height + pad * 2) + 'px' });
      const pw = pop.offsetWidth, ph = pop.offsetHeight, vw = innerWidth, vh = innerHeight;
      let x = r.right + 16, y = r.top + r.height / 2 - ph / 2;
      if (x + pw > vw - 12) { x = Math.max(12, r.left + r.width / 2 - pw / 2); y = r.bottom + 16; if (y + ph > vh - 12) y = r.top - ph - 16; }
      pop.style.left = Math.max(12, Math.min(x, vw - pw - 12)) + 'px'; pop.style.top = Math.max(12, Math.min(y, vh - ph - 12)) + 'px';
    }
    function show(n, dir) {
      // pula passos cujo alvo não existe/está oculto
      while (n >= 0 && n < steps.length && !target(steps[n])) n += dir;
      if (n < 0) n = 0;
      if (n >= steps.length) { stop(); return; }
      i = n;
      const s = steps[i], el = target(s);
      el.scrollIntoView({ block: 'nearest' });
      tTitle.textContent = IDE.t(s.title); tText.textContent = IDE.t(s.text);
      const total = steps.filter(target).length, num = steps.slice(0, i + 1).filter(target).length;
      tCount.textContent = IDE.t('Passo {n} de {total}', { n: num, total });
      const last = !steps.slice(i + 1).some(target);
      bNext.textContent = IDE.t(last ? 'Concluir' : 'Avançar'); bBack.style.visibility = steps.slice(0, i).some(target) ? '' : 'hidden';
      requestAnimationFrame(place);
    }
    function onKey(e) { if (e.key === 'Escape') stop(); else if (e.key === 'ArrowRight' || e.key === 'Enter') { e.preventDefault(); bNext.click(); } else if (e.key === 'ArrowLeft') bBack.click(); }
    function stop() { if (!active) return; active = null; window.removeEventListener('resize', place); document.removeEventListener('keydown', onKey, true); mask.remove(); spot.remove(); pop.remove(); }
    bSkip.addEventListener('click', stop); bBack.addEventListener('click', () => show(i - 1, -1));
    bNext.addEventListener('click', () => show(i + 1, 1));
    window.addEventListener('resize', place); document.addEventListener('keydown', onKey, true);
    root.append(mask, spot, pop);
    active = { stop };
    setTimeout(() => show(0, 1), 80);
  };
})(window.IDE);
