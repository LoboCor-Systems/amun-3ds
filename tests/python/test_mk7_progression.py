"""Cup candidate logic tests; these do not certify its unverified field layout."""
import copy
from pathlib import Path
import unittest

from compiler.profile import load_profile, LoadedProfile
from compiler.simulator import run_profile_tests

PROFILE = Path(__file__).resolve().parents[2] / 'profiles/mario-kart-7-eur-progression/profile.json'
CUPS = ('mushroom', 'flower', 'star', 'special', 'shell', 'banana', 'leaf', 'lightning')
CLASSES = ('50', '100', '150', 'mirror')


def progression_scenarios(document):
    base = {
        name: 0
        for name, symbol in document['symbols'].items()
        if symbol.get('resolver', {}).get('kind') != 'derived'
    }
    base['save.ready'] = 1
    scenarios = []

    def cell(values, cup, cc, byte):
        values[f'save.cup.{cup}.{cc}'] = byte
        values[f'save.shadow.{cup}.{cc}'] = byte

    def scenario(name, values, unlocked):
        scenarios.append({'name': name, 'frames': [{'timeMs': 0, 'values': values}],
                          'expectUnlocked': unlocked})

    for cup in CUPS:
        for cc in CLASSES:
            values = dict(base)
            cell(values, cup, cc, 0x3B)
            expected = ['first_gp_gold'] + ([f'gold_150_{cup}'] if cc == '150' else [])
            scenario(f'only {cup} {cc} gold', values, expected)
    for cc in CLASSES:
        values = dict(base)
        for cup in CUPS:
            cell(values, cup, cc, 0x39)
        expected = ['first_gp_gold']
        if cc == '150':
            expected += [f'gold_150_{cup}' for cup in CUPS] + ['star_150_all']
        else:
            expected += [f'gold_{cc}_all']
        scenario(f'eight {cc} gold trophies', values, expected)
        partial = dict(values)
        cell(partial, 'lightning', cc, 0x21)  # silver, not gold
        expected = ['first_gp_gold']
        if cc == '150':
            expected += [f'gold_150_{cup}' for cup in CUPS[:-1]]
        scenario(f'seven {cc} gold one silver', partial, expected)
    for rank, is_star in ((0x31, False), (0x39, True), (0x3B, True), (0x3D, True)):
        values = dict(base)
        for cup in CUPS:
            cell(values, cup, '150', rank)
        expected = ['first_gp_gold'] + [f'gold_150_{cup}' for cup in CUPS]
        if is_star:
            expected += ['star_150_all']
        scenario(f'all 150cc rank byte {rank:#x}', values, expected)
    for byte in (0, 0x11, 0x21, 0x30, 0x3A, 0x3E, 0x3F, 0x71, 0xFF):
        values = dict(base)
        cell(values, 'mushroom', '150', byte)
        scenario(f'non-gold or invalid cell {byte:#x}', values, [])
    values = dict(base)
    cell(values, 'mushroom', '150', 0x3B)
    values['save.ready'] = 0
    scenario('uninitialized save engine', values, [])
    values = dict(base)
    cell(values, 'mushroom', '150', 0x3B)
    values['save.shadow.mushroom.150'] = 0
    scenario('save copies disagree during update', values, [])

    def race(name, frames, unlocked):
        scenarios.append({'name': name, 'frames': [
            {'timeMs': index * 100, 'values': frame} for index, frame in enumerate(frames)
        ], 'expectUnlocked': unlocked})

    def racing(**overrides):
        values = dict(base)
        values.update({'race.engine_ready': 1, 'race.state': 2, 'race.play_mode': 0,
                       'race.rule_mode': 0, 'race.type': 2, 'race.place': 4, 'race.coins': 4})
        values.update(overrides)
        return values

    race('result screen was already up', [
        racing(**{'race.state': 3, 'race.place': 1, 'race.coins': 10}),
        racing(**{'race.state': 3, 'race.place': 1, 'race.coins': 10}),
    ], [])
    race('win with ten coins after racing', [
        racing(),
        racing(**{'race.state': 3, 'race.place': 1, 'race.coins': 10}),
    ], ['first_gp_win', 'win_with_ten'])
    race('win with nine coins', [
        racing(**{'race.coins': 8}),
        racing(**{'race.state': 3, 'race.place': 1, 'race.coins': 9}),
    ], ['first_gp_win'])
    race('second place does not win', [
        racing(**{'race.place': 3}),
        racing(**{'race.state': 3, 'race.place': 2, 'race.coins': 7}),
    ], [])
    race('demo and abandoned result do not carry', [
        racing(**{'race.play_mode': 3, 'race.place': 1, 'race.coins': 10}),
        racing(**{'race.engine_ready': 0, 'race.state': 0, 'race.place': 0, 'race.coins': 0}),
        racing(**{'race.state': 3, 'race.place': 1, 'race.coins': 10}),
    ], [])

    def tt(**overrides):
        values = dict(base)
        values.update({
            'race.engine_ready': 1, 'race.state': 2, 'race.play_mode': 0,
            'race.rule_mode': 1, 'race.type': 2, 'race.place': 4, 'race.coins': 0,
            'race.course': 4, 'race.ghost_class': 0,
            'race.player_ctime_min': 1, 'race.player_ctime_sec': 33, 'race.player_ctime_ms': 594,
            'race.player_item_kind': 7, 'race.player_item_stock': 3,
        })
        values.update(overrides)
        return values

    race('normal staff beat without using a mushroom', [
        tt(),
        tt(**{'race.state': 3, 'race.place': 1}),
    ], ['ghost_normal_first', 'ghost_n_c04', 'ghost_no_mushroom'])
    race('normal staff beat after mushrooms were used', [
        tt(),
        tt(**{'race.state': 3, 'race.place': 1, 'race.player_item_stock': 1}),
    ], ['ghost_normal_first', 'ghost_n_c04'])
    race('stock of three on a different item is not kinoko3', [
        tt(**{'race.player_item_kind': 3}),
        tt(**{'race.state': 3, 'race.place': 1, 'race.player_item_kind': 3}),
    ], ['ghost_normal_first', 'ghost_n_c04'])
    race('expert staff beat with unused mushrooms is not ghost_no_mushroom', [
        tt(**{'race.ghost_class': 1, 'race.player_ctime_sec': 25, 'race.player_ctime_ms': 97}),
        tt(**{'race.state': 3, 'race.place': 1, 'race.ghost_class': 1,
              'race.player_ctime_sec': 25, 'race.player_ctime_ms': 97}),
    ], ['ghost_expert_first', 'ghost_e_c04'])

    def gp(**overrides):
        values = dict(base)
        values.update({'race.engine_ready': 1, 'race.state': 2, 'race.play_mode': 0,
                       'race.rule_mode': 0, 'race.type': 2, 'race.place': 4,
                       'race.engine': 1, 'race.gp_cup': 5, 'race.gp_index': 0})
        values.update(overrides)
        return values

    def sweep(engine=1, cup=5, places=(1, 1, 1, 1)):
        frames = []
        for index, place in enumerate(places):
            frames.append(gp(**{'race.gp_index': index, 'race.engine': engine, 'race.gp_cup': cup}))
            frames.append(gp(**{'race.state': 3, 'race.place': place, 'race.gp_index': index,
                                'race.engine': engine, 'race.gp_cup': cup}))
        return frames

    race('100cc four firsts', sweep(), ['first_gp_win', 'gp_sweep'])
    race('50cc four firsts are not a sweep', sweep(engine=0), ['first_gp_win'])
    race('third race outside first clears the sweep', sweep(places=(1, 1, 2, 1)), ['first_gp_win'])

    def lap(**overrides):
        values = dict(base)
        values.update({
            'race.engine_ready': 1, 'race.state': 2, 'race.play_mode': 0,
            'race.rule_mode': 0, 'race.type': 2, 'race.place': 8, 'race.course': 4,
            'race.engine': 1, 'race.gp_cup': 0, 'race.gp_index': 0,
            'race.lap_index': 1, 'race.lap_shown': 0x0302,
        })
        values.update(overrides)
        return values

    eighth = lap(**{'race.lap_index': 2, 'race.lap_shown': 0x0303, 'race.place': 8})
    won = lap(**{'race.state': 3, 'race.place': 1, 'race.lap_index': 3, 'race.lap_shown': 0x0303})
    race('eighth at the final-lap line then first', [lap(), eighth, won],
         ['first_gp_win', 'last_lap_comeback'])
    race('first at the final-lap line then first', [
        lap(**{'race.place': 1}),
        lap(**{'race.lap_index': 2, 'race.lap_shown': 0x0303, 'race.place': 1}),
        won,
    ], ['first_gp_win'])
    race('eighth only after the final lap began', [
        lap(**{'race.place': 1}),
        lap(**{'race.lap_index': 2, 'race.lap_shown': 0x0303, 'race.place': 1}),
        eighth,
        won,
    ], ['first_gp_win'])
    race('wuhu is not an ordinary comeback course', [
        lap(**{'race.course': 8}),
        lap(**{'race.course': 8, 'race.lap_index': 2, 'race.lap_shown': 0x0303}),
        lap(**{'race.course': 8, 'race.state': 3, 'race.place': 1, 'race.lap_index': 3,
               'race.lap_shown': 0x0303}),
    ], ['first_gp_win'])
    race('a new race clears the comeback sample', [
        lap(), eighth,
        lap(**{'race.state': 0, 'race.place': 0, 'race.lap_index': 0, 'race.lap_shown': 0}),
        lap(**{'race.place': 1}),
        lap(**{'race.lap_index': 2, 'race.lap_shown': 0x0303, 'race.place': 1}),
        won,
    ], ['first_gp_win'])

    def rainbow(**overrides):
        values = dict(base)
        values.update({
            'race.engine_ready': 1, 'race.state': 2, 'race.play_mode': 0,
            'race.rule_mode': 0, 'race.type': 2, 'race.place': 4, 'race.course': 13,
            'race.engine': 2, 'race.gp_cup': 3, 'race.gp_index': 3,
            'race.respawn_log_size': 1, 'race.respawn_count': 0,
        })
        values.update(overrides)
        return values

    clean_win = rainbow(**{'race.state': 3, 'race.place': 1})
    race('3ds rainbow road 150cc first with zero rescues', [rainbow(), clean_win],
         ['first_gp_win', 'rainbow_no_rescue'])
    # Hardware 2026-10-05: start line RESPAWN 0, results after one Lakitu fall RESPAWN 1, place 1.
    race('one lakitu rescue then first', [
        rainbow(),
        rainbow(**{'race.respawn_count': 1}),
        rainbow(**{'race.state': 3, 'race.place': 1, 'race.respawn_count': 1}),
    ], ['first_gp_win'])
    race('100cc rainbow road is not rainbow_no_rescue', [
        rainbow(**{'race.engine': 1}),
        rainbow(**{'race.engine': 1, 'race.state': 3, 'race.place': 1}),
    ], ['first_gp_win'])
    race('snes rainbow road is not rainbow_no_rescue', [
        rainbow(**{'race.course': 31}),
        rainbow(**{'race.course': 31, 'race.state': 3, 'race.place': 1}),
    ], ['first_gp_win'])
    race('rescued race does not latch into the next clean race', [
        rainbow(),
        rainbow(**{'race.respawn_count': 1}),
        rainbow(**{'race.state': 3, 'race.place': 1, 'race.respawn_count': 1}),
        rainbow(**{'race.engine_ready': 0, 'race.state': 0, 'race.place': 0,
                   'race.respawn_log_size': 0}),
        rainbow(),
        clean_win,
    ], ['first_gp_win', 'rainbow_no_rescue'])
    race('rainbow results already showing do not count', [clean_win, clean_win], [])
    race('unreadable respawn log does not unlock', [
        rainbow(**{'race.respawn_log_size': 0}),
        rainbow(**{'race.state': 3, 'race.place': 1, 'race.respawn_log_size': 0}),
    ], ['first_gp_win'])

    def land_sea(**overrides):
        values = dict(base)
        values.update({
            'race.engine_ready': 1, 'race.state': 2, 'race.play_mode': 0,
            'race.rule_mode': 0, 'race.type': 2, 'race.place': 4, 'race.course': 12,
            'race.engine': 1, 'race.gp_cup': 3, 'race.gp_index': 0,
            'race.underwater_log_size': 1, 'race.underwater_count': 0,
            'race.flying_log_size': 1, 'race.flying_count': 0,
        })
        values.update(overrides)
        return values

    # Hardware 2026-10-05: Piranha Plant Slide start UW0/FL0; finish 1st UW2032/FL518.
    # 2026-10-06 Toad Circuit no-glider control: FLYING stayed 0.
    armed = land_sea(**{'race.underwater_count': 2032, 'race.flying_count': 518})
    lsa_win = land_sea(**{'race.state': 3, 'race.place': 1,
                          'race.underwater_count': 2032, 'race.flying_count': 518})
    race('underwater and glide then first', [land_sea(), armed, lsa_win],
         ['first_gp_win', 'land_sea_air_win'])
    race('underwater only then first', [
        land_sea(),
        land_sea(**{'race.underwater_count': 100}),
        land_sea(**{'race.state': 3, 'race.place': 1, 'race.underwater_count': 100}),
    ], ['first_gp_win'])
    race('glide only then first', [
        land_sea(),
        land_sea(**{'race.flying_count': 100}),
        land_sea(**{'race.state': 3, 'race.place': 1, 'race.flying_count': 100}),
    ], ['first_gp_win'])
    race('toad jumps without glide stay flying zero', [
        land_sea(**{'race.course': 4}),
        land_sea(**{'race.course': 4, 'race.underwater_count': 0, 'race.flying_count': 0}),
        land_sea(**{'race.course': 4, 'race.state': 3, 'race.place': 1}),
    ], ['first_gp_win'])
    race('second after underwater and glide does not unlock', [
        land_sea(), armed,
        land_sea(**{'race.state': 3, 'race.place': 2,
                    'race.underwater_count': 2032, 'race.flying_count': 518}),
    ], [])
    race('land_sea_air results already showing do not count', [lsa_win, lsa_win], [])
    race('partial land_sea_air attempt does not carry', [
        land_sea(),
        land_sea(**{'race.underwater_count': 50}),
        land_sea(**{'race.engine_ready': 0, 'race.state': 0, 'race.place': 0,
                    'race.underwater_log_size': 0, 'race.flying_log_size': 0}),
        land_sea(),
        land_sea(**{'race.flying_count': 80}),
        land_sea(**{'race.state': 3, 'race.place': 1, 'race.flying_count': 80}),
    ], ['first_gp_win'])
    race('armed land_sea_air then leave race clears latches', [
        land_sea(), armed,
        land_sea(**{'race.engine_ready': 0, 'race.state': 0, 'race.place': 0,
                    'race.underwater_log_size': 0, 'race.flying_log_size': 0}),
        lsa_win,
    ], [])
    race('brief zero after arming does not clear latches', [
        land_sea(), armed,
        land_sea(**{'race.underwater_count': 0, 'race.flying_count': 0}),
        lsa_win,
    ], ['first_gp_win', 'land_sea_air_win'])
    return scenarios


class Mk7ProgressionTests(unittest.TestCase):
    def test_all_cells_classes_rank_and_initialization(self):
        loaded = load_profile(PROFILE)
        document = copy.deepcopy(loaded.document)
        document['tests'] = progression_scenarios(document)
        results = run_profile_tests(LoadedProfile(document, loaded.profile_path, loaded.project_root))
        for result in results:
            with self.subTest(result.name):
                self.assertTrue(result.passed, result.failures)

    def test_coin_ids_are_preserved_and_only_exact_current_eur_build_admitted(self):
        doc = load_profile(PROFILE).document
        self.assertEqual(len(doc['achievements']), 95)
        self.assertEqual([a['id'] for a in doc['achievements'][:7]],
                         ['pocket_change', 'coins_25', 'coins_100', 'coins_500', 'coins_1000',
                          'first_gp_win', 'win_with_ten'])
        scored = [a for a in doc['achievements'] if a['points'] > 0]
        self.assertEqual(len(scored), 31)
        self.assertEqual(sum(a['points'] for a in scored), 345)
        self.assertTrue(any(a['id'] == 'ghost_normal_8' for a in doc['achievements']))
        self.assertTrue(any(a['id'] == 'ghost_no_mushroom' and a['points'] == 15 for a in doc['achievements']))
        self.assertTrue(any(a['id'] == 'gp_sweep' and a['points'] == 10 for a in doc['achievements']))
        self.assertTrue(any(a['id'] == 'last_lap_comeback' and a['points'] == 10 for a in doc['achievements']))
        self.assertTrue(any(a['id'] == 'rainbow_no_rescue' and a['points'] == 10 for a in doc['achievements']))
        self.assertTrue(any(a['id'] == 'land_sea_air_win' and a['points'] == 10 for a in doc['achievements']))
        self.assertTrue(any(a['id'] == 'ghost_n_c00' and a['points'] == 0 and a['secret'] for a in doc['achievements']))
        # The experimental set is deliberately admitted on the one exact EUR build it targets
        # (authorised full-progression deploy, 2026-10-06); no other build is listed.
        self.assertEqual(len(doc['game']['builds']), 1)
        self.assertEqual(doc['game']['builds'][0]['applicationVersion'], '3152')
        self.assertTrue(doc['game']['builds'][0]['compatible'])


if __name__ == '__main__':
    unittest.main()
