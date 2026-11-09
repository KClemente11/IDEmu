"""Tests for the GUI translations: tools/i18n_check.py, the dictionary in idemu/web/i18n.js and, when node is available, IDE.t itself."""
import json
import os
import re
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))

import i18n_check  # noqa: E402

BRACES = re.compile(r'\{\w+\}')
PERCENT = re.compile(r'%[st]')


def find_node():
    local = os.path.expanduser('~/.local/node/bin/node')
    return shutil.which('node') or (local if os.path.exists(local) else None)


class CheckerTest(unittest.TestCase):
    def test_check_passes(self):
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'i18n_check.py')], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_check_reports_a_missing_entry(self):
        ix = i18n_check.Index()
        ix.pt.discard('Emulador parado.')
        self.assertTrue(any('Emulador parado.' in p for p in i18n_check.check_js(ix)))
        ix = i18n_check.Index()
        ix.rule_pt.discard('chassi desconhecido: %s')
        ix.res = []
        self.assertTrue(any('chassi desconhecido' in p for p in i18n_check.check_python(ix)))

    def test_js_literals_skip_regex_and_comments(self):
        src = "/* 'a' */ const x = s.replace(/[&<>\"']/g, 'b'); // 'c'\nconst y = 4 / 2 + 'd';"
        self.assertEqual([s for _, s in i18n_check.js_literals(src)], ['b', 'd'])


class DictionaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pairs, cls.rules = i18n_check.load_tables()

    def test_tables_are_not_empty(self):
        self.assertGreater(len(self.pairs), 500)
        self.assertGreater(len(self.rules), 20)

    def test_no_pt_key_with_two_en_values(self):
        seen = {}
        for pt, en in self.pairs:
            self.assertEqual(seen.setdefault(pt, en), en, 'conflicting translations for %r' % pt)
        seen = {}
        for pt, en in self.rules:
            self.assertEqual(seen.setdefault(pt, en), en, 'conflicting rules for %r' % pt)

    def test_placeholders_match(self):
        for pt, en in self.pairs:
            self.assertEqual(sorted(BRACES.findall(pt)), sorted(BRACES.findall(en)), 'placeholders differ: %r / %r' % (pt, en))
        for pt, en in self.rules:
            self.assertEqual(PERCENT.findall(pt), PERCENT.findall(en), 'rule placeholders differ or are reordered: %r / %r' % (pt, en))
            self.assertTrue(PERCENT.search(pt), 'rule without a variable part belongs in DICT: %r' % pt)

    def test_translating_twice_changes_nothing(self):
        """h() translates text that may already have gone through IDE.t, so a translation must not itself be a key for something else."""
        p2e, e2p = {}, {}
        for pt, en in self.pairs:
            p2e.setdefault(pt, en)
            e2p.setdefault(en, pt)
        for pt, en in self.pairs:
            self.assertEqual(p2e.get(en, en), en, 'en text is also a pt key: %r' % en)
            self.assertEqual(e2p.get(pt, pt), pt, 'pt text is also an en key: %r' % pt)

    def test_no_surrounding_whitespace(self):
        for s in [x for pair in self.pairs + self.rules for x in pair]:
            self.assertEqual(s, s.strip(), 'IDE.t trims before looking up: %r' % s)


SCRIPT = r"""
const fs = require('fs'), vm = require('vm');
const ctx = { window: {}, document: { documentElement: {} } };
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const IDE = ctx.window.IDE, out = {};
function run(lang, cases) { IDE.setLang(lang); out[lang] = { html: ctx.document.documentElement.lang, locale: IDE.locale(), res: cases.map((c) => IDE.t(c[0], c[1])) }; }
run('en', JSON.parse(process.argv[2]));
run('pt', JSON.parse(process.argv[3]));
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(find_node(), 'node not found')
class TranslateTest(unittest.TestCase):
    EN = [
        (['Parar'], 'Stop'),
        (['  Pasta psdzdata '], '  psdzdata folder '),
        (['Flash to head unit'], 'Flash to head unit'),
        (['Excluir "{name}"? Os arquivos do ambiente serão removidos e isso não pode ser desfeito.', {'name': 'F30 $1'}], 'Delete "F30 $1"? The environment files will be removed and this cannot be undone.'),
        (['arquivo SWFL ausente ou inexistente para "hmi"'], 'SWFL file missing or not found for "hmi"'),
        (['ValueError: valor inválido para vehicle_speed: \'x\''], 'ValueError: Invalid value for vehicle_speed: \'x\''),
        (['KeyError: \'sinal desconhecido: foo\''], 'KeyError: \'Unknown signal: foo\''),
        (['falha ao regravar a codificação: pasta inexistente'], 'Could not rewrite the coding: Folder does not exist'),
        (['VIDEO_HANDBRAKE'], 'VIDEO_HANDBRAKE'),
        (['0x1A0'], '0x1A0'),
        (['', None], ''),
    ]
    PT = [
        (['Flash to head unit'], 'Gravar na head unit'),
        (['Parar'], 'Parar'),
        (['Value must be between 0 and {max}.', {'max': 15}], 'O valor deve estar entre 0 e 15.'),
        (['Backing up the current coding'], 'Fazendo backup da codificação atual'),
        (['Head unit'], 'Execução'),
        (['Unknown signal: foo'], 'sinal desconhecido: foo'),
        (['VIDEO_HANDBRAKE'], 'VIDEO_HANDBRAKE'),
    ]

    def test_both_directions(self):
        en = json.dumps([c for c, _ in self.EN])
        pt = json.dumps([c for c, _ in self.PT])
        r = subprocess.run([find_node(), '-e', SCRIPT, os.path.join(ROOT, 'idemu', 'web', 'i18n.js'), en, pt], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out['en']['res'], [w for _, w in self.EN])
        self.assertEqual(out['pt']['res'], [w for _, w in self.PT])
        self.assertEqual((out['en']['html'], out['en']['locale']), ('en', 'en-US'))
        self.assertEqual((out['pt']['html'], out['pt']['locale']), ('pt-BR', 'pt-BR'))


if __name__ == '__main__':
    unittest.main()
