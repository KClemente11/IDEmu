'use strict';
/* IDEmu – temas da interface: Cupertino (padrão), Next Big Thing (iDrive 6 e anteriores) e Bavarian OS (iDrive 8 e posteriores).
   O tema fica em localStorage ("idemu.theme") e em <html data-theme>. Na primeira abertura aparece um pop-up para escolher. */
(function (IDE) {
  const { h } = IDE;
  const THEMES = [
    { id: 'cupertino', name: 'Cupertino', desc: 'Visual limpo e translúcido, como o macOS. É o tema atual.', cls: 'tp-cup' },
    { id: 'nbt', name: 'Next Big Thing', desc: 'Inspirado no iDrive 6 e anteriores: preto brilhante, laranja e vermelho, efeito aqua e molduras cromadas.', cls: 'tp-nbt' },
    { id: 'bavarian', name: 'Bavarian OS', desc: 'Inspirado no iDrive 8 e posteriores: preto profundo, raios vermelhos, botões chanfrados e tipografia leve.', cls: 'tp-bav' },
  ];
  IDE.themeId = () => { const t = IDE.pref.get('theme', null); return THEMES.some((x) => x.id === t) ? t : 'cupertino'; };
  IDE.applyTheme = function (id) {
    if (id === 'cupertino') document.documentElement.removeAttribute('data-theme'); else document.documentElement.setAttribute('data-theme', id);
  };
  /** Grade de cartões de tema (pré-visualiza ao clicar). Devolve { el, value() }. */
  IDE.themeGrid = function (start) {
    let cur = start || IDE.themeId();
    const opts = THEMES.map((t) => {
      const b = h('button', { type: 'button', class: 'theme-opt' + (t.id === cur ? ' on' : ''), 'data-theme-id': t.id, 'aria-pressed': t.id === cur ? 'true' : 'false' },
        h('div', { class: 'tp-prev ' + t.cls }, h('div', { class: 'tp-side' }, h('i'), h('i'), h('i')), h('div', { class: 'tp-main' }, h('i', { class: 's' }), h('i'), h('i'))),
        h('div', null, h('b', null, t.name), h('span', { class: 'd' }, t.desc)));
      b.addEventListener('click', () => {
        cur = t.id; IDE.applyTheme(cur);
        opts.forEach((o) => { const on = o.dataset.themeId === cur; o.classList.toggle('on', on); o.setAttribute('aria-pressed', on ? 'true' : 'false'); });
      });
      return b;
    });
    return { el: h('div', { class: 'theme-pick' }, ...opts), value: () => cur };
  };
  /** Abre o pop-up de tema (botão "Tema…" da barra lateral). */
  IDE.themePicker = function () {
    const saved = IDE.themeId(), grid = IDE.themeGrid(saved);
    let done = false;
    IDE.modal({
      title: 'Escolha um tema', size: 'lg', body: h('div', null, grid.el),
      actions: [{ label: 'Usar este tema', kind: 'primary', onClick: () => { done = true; IDE.pref.set('theme', grid.value()); } }],
      onClose: () => { if (!done) IDE.applyTheme(saved); },
    });
  };
})(window.IDE);
