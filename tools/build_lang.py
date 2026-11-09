#!/usr/bin/env python3
"""Monta idemu/web/lang/<código>.js a partir de traduções em JSON.

Uso: python3 tools/build_lang.py <código> <pasta com src_N.json e out_<código>_N.json>
Cada src_N.json é uma lista de textos em inglês (dicionário e depois modelos de regras, na ordem de i18n.js) e cada
out_<código>_N.json é a lista traduzida, na mesma ordem. Traduções que perdem ou mudam os marcadores ({nome}, %s, %t...) voltam para o inglês.
"""

"""Builds idemu/web/lang/<code>.js from JSON translations.

Usage: python3 tools/build_lang.py <code> <folder containing src_N.json and out_<code>_N.json files>
Each src_N.json file contains a list of English texts (a dictionary followed by rule templates, in the same order as in i18n.js), and each
corresponding out_<code>_N.json file contains the translated list, in the same order. Translations that lose or alter placeholders ({name}, %s, %t, etc.) will revert to English.
"""
import json, os, re, sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PH = re.compile(r'\{\w+\}|%[strdj]')

def main(code, folder):
    src, out = [], []
    for i in range(4):
        src += json.load(open(os.path.join(folder, 'src_%d.json' % i), encoding='utf-8'))
        out += json.load(open(os.path.join(folder, 'out_%s_%d.json' % (code, i)), encoding='utf-8'))
    assert len(src) == len(out), (len(src), len(out))
    n_rules = 80
    dict_n = len(src) - n_rules
    bad = 0
    pairs = []
    for en, tr in zip(src, out):
        if not isinstance(tr, str) or not tr.strip() or Counter(PH.findall(en)) != Counter(PH.findall(tr)):
            bad += 1; tr = en; print('marcadores diferentes, mantido em inglês:', en[:70], file=sys.stderr)
        pairs.append((en, tr))
    d, rules = pairs[:dict_n], pairs[dict_n:]
    lines = ['/* IDEmu – traduções da interface (%s), geradas a partir do inglês. Veja tools/build_lang.py. */' % code,
             'window.IDE = window.IDE || {}; IDE.LANG_DATA = IDE.LANG_DATA || {};', 'IDE.LANG_DATA.%s = {' % code, '  dict: {']
    seen = set()
    for en, tr in d:
        if en in seen or en == tr: continue
        seen.add(en); lines.append('    %s: %s,' % (json.dumps(en, ensure_ascii=False), json.dumps(tr, ensure_ascii=False)))
    lines.append('  },'); lines.append('  rules: [')
    for en, tr in rules: lines.append('    [%s, %s],' % (json.dumps(en, ensure_ascii=False), json.dumps(tr, ensure_ascii=False)))
    lines += ['  ],', '};', '']
    path = os.path.join(ROOT, 'idemu', 'web', 'lang', code + '.js')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'w', encoding='utf-8').write('\n'.join(lines))
    print(code, 'ok:', len(d), 'textos,', len(rules), 'regras,', bad, 'revertidos')

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
