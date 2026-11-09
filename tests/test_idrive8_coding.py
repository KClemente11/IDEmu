# -*- coding: utf-8 -*-
"""Editor de codificação do iDrive 8: dicionário do firmware, tabela por ambiente, guest e servidor."""
import json, os, unittest
from idemu import coding8, mgu, server

HAVE = os.path.isfile(coding8.path()) and os.path.isfile(os.path.join(mgu.OUT, 'guest', 'coding.tab'))


def env():
    return {'kind': 'mgu22', 'coding': {}}


@unittest.skipUnless(HAVE, 'mgu22/coding8.json e coding.tab ausentes (monte o iDrive 8)')
class Coding8(unittest.TestCase):
    def test_dictionary_matches_factory_table(self):
        tab = coding8.factory_tab(); P = coding8.load()
        self.assertGreater(len(P), 1200)
        self.assertEqual([n for n, p in P.items() if tab.get(p['id']) != p['default']], [])     # padrão do dicionário = tabela que o libcod já lê

    def test_describe_shape(self):
        d = coding8.describe(env(), '/nonexistent'); X = {p['name']: p for p in d['params']}
        self.assertEqual(len(X), len(coding8.load()))
        t = X['DEVELOPER_MENU']; self.assertEqual((t['factory'], t['value'], t['coded'], t['bits']), (1, 1, False, 1))
        self.assertEqual([o['value'] for o in t['options']], [0, 1])
        self.assertEqual(X['USB_HUB_AVAIL']['bits'], 2)
        self.assertTrue(all(q in X for q in d['popular_order']))
        self.assertIn('HMI', {g['id'] for g in d['groups']})

    def test_no_change_means_factory_table(self):
        self.assertIsNone(coding8.build_tab(env()))

    def test_apply_changes_only_the_chosen_ids(self):
        e = env(); P = coding8.load()
        done = coding8.apply_changes(e, {'DEVELOPER_MENU': 0, 'USB_HUB_AVAIL': 1})
        self.assertEqual({n for n, _, _ in done}, {'DEVELOPER_MENU', 'USB_HUB_AVAIL'})
        txt = coding8.build_tab(e); fac = coding8.factory_tab()
        new = {int(a, 16): int(b) for a, b in (l.split() for l in txt.splitlines())}
        self.assertEqual(len(new), len(fac))
        self.assertEqual({k for k in new if new[k] != fac[k]}, {P['DEVELOPER_MENU']['id'], P['USB_HUB_AVAIL']['id']})
        self.assertEqual(new[P['DEVELOPER_MENU']['id']], 0); self.assertEqual(new[P['USB_HUB_AVAIL']['id']], 1)

    def test_value_equal_to_factory_is_not_stored_and_none_resets(self):
        e = env(); coding8.apply_changes(e, {'DEVELOPER_MENU': 1}); self.assertEqual(e['coding']['extra'], {})
        coding8.apply_changes(e, {'DEVELOPER_MENU': 0}); self.assertEqual(e['coding']['extra'], {'DEVELOPER_MENU': 0})
        coding8.apply_changes(e, {'DEVELOPER_MENU': None}); self.assertEqual(e['coding']['extra'], {})

    def test_by_label_numbers_and_invalid_values(self):
        e = env(); coding8.apply_changes(e, {'USB_HUB_AVAIL': 'hub_on_usb1'}); self.assertEqual(e['coding']['extra'], {'USB_HUB_AVAIL': 1})
        num = next(n for n, p in coding8.load().items() if not p['options'] and p['default'] == 1)       # parâmetro numérico livre
        coding8.apply_changes(e, {num: 7}); self.assertEqual(e['coding']['extra'][num], 7)
        for bad in ({'USB_HUB_AVAIL': 3}, {'DEVELOPER_MENU': 2}, {'DEVELOPER_MENU': 'talvez'}, {'NAO_EXISTE': 1}, {num: -1}):
            with self.assertRaises(ValueError): coding8.apply_changes(dict(e), bad)

    def test_unknown_names_in_env_are_ignored(self):
        e = env(); e['coding']['extra'] = {'JA_NAO_EXISTE': 5}; self.assertIsNone(coding8.build_tab(e))

    def test_libcod_table_fits(self):
        self.assertLess(len(coding8.factory_tab()), 8192)                                   # limite do array de libcod.c


class Wiring(unittest.TestCase):
    def read(self, p):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), p), encoding='utf-8') as f: return f.read()

    def test_guest_confirms_the_table_and_runtime_ships_it(self):
        self.assertIn('== coding applied', self.read('tools/mgu/guest_boot.sh'))
        s = self.read('idemu/mgu.py'); self.assertIn('coding8.build_tab(self.env)', s); self.assertIn("f == 'coding.tab'", s)

    def test_server_accepts_mgu22(self):
        s = self.read('idemu/server.py')
        self.assertNotIn('ainda não existe para o iDrive 8', s); self.assertIn("('mgu7', 'mgu22')", s)

    def test_build_writes_the_dictionary(self):
        self.assertIn('gen_coding8', self.read('tools/mgu/build_image.py'))

    def test_catalog_level(self):
        from idemu import catalog
        f = {x['id']: x for x in next(g for g in catalog.GENERATIONS if g['id'] == 'id8')['level']['features']}
        self.assertEqual(f['coding']['state'], 'half')


if __name__ == '__main__':
    unittest.main()
