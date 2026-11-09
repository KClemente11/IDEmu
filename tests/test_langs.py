import json, os, re, unittest
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANG = os.path.join(ROOT, 'idemu', 'web', 'lang')
PH = re.compile(r'\{\w+\}|%[strdj]')
CODES = ['es', 'fr', 'de', 'it', 'tr', 'ru', 'zh', 'ja']


def load(code):
    t = open(os.path.join(LANG, code + '.js'), encoding='utf-8').read()
    body = t[t.index('IDE.LANG_DATA.%s = ' % code) + len('IDE.LANG_DATA.%s = ' % code):].rstrip().rstrip(';')
    body = re.sub(r',(\s*[}\]])', r'\1', body)          # vírgulas finais
    body = re.sub(r'^(\s*)(dict|rules):', r'\1"\2":', body, flags=re.M)
    return json.loads(body)


class LangFilesTest(unittest.TestCase):
    def test_each_language_is_complete_and_keeps_placeholders(self):
        for code in CODES:
            d = load(code)
            self.assertGreater(len(d['dict']), 900, code)
            self.assertEqual(len(d['rules']), 80, code)
            for en, tr in list(d['dict'].items()) + d['rules']:
                self.assertEqual(Counter(PH.findall(en)), Counter(PH.findall(tr)), (code, en))

    def test_languages_are_registered_in_server_and_page(self):
        srv = open(os.path.join(ROOT, 'idemu', 'server.py'), encoding='utf-8').read()
        html = open(os.path.join(ROOT, 'idemu', 'web', 'index.html'), encoding='utf-8').read()
        for code in CODES:
            self.assertIn("'%s'" % code, srv)
            self.assertIn('lang/%s.js' % code, html)


if __name__ == '__main__':
    unittest.main()
