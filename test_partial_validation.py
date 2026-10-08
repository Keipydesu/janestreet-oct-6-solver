import json
from pathlib import Path
import tempfile
import unittest

from model import GridState, Workspace
from starting_grid import new_workspace


def paint(state,cells,color='#abcdef'):
    for r,c in cells:
        state.grid[r][c].region_color=color


class PartialValidationTests(unittest.TestCase):
    def test_blank_board_shortcuts_are_not_contradictions(self):
        for size in (5,11):
            report = new_workspace(size).saved.validate_partial()
            self.assertTrue(report['consistent'])
            self.assertGreater(report['unresolved_count'],0)
        state=GridState(5)
        state.grid[0][0].starting_number=10
        state.grid[0][4].starting_number=0
        check=state.validate_partial()['checks'][0]
        self.assertEqual(check['unit_cost_to_known_capitol'],4)
        self.assertEqual(check['status'],'unresolved')
        self.assertIsNone(check['upper_bound'])

    def test_small_number_trapped_inside_large_state_fails(self):
        state=GridState(5)
        paint(state,[(r,c) for r in range(1,4) for c in range(1,4)])
        state.grid[2][2].starting_number=4
        report=state.validate_partial()
        self.assertFalse(report['consistent'])
        check=report['checks'][0]
        self.assertEqual(check['lower_bound'],10)
        self.assertEqual(check['status'],'contradiction')
        self.assertEqual(report['heatmap'][1][1],0)

    def test_fixed_painted_route_can_prove_too_cheap(self):
        state=GridState(5)
        paint(state,[(0,0),(0,1),(1,0)])  # Capitol at (0,0).
        state.grid[0][1].starting_number=4
        check=state.validate_partial()['checks'][0]
        self.assertEqual(check['upper_bound'],3)
        self.assertEqual(check['status'],'contradiction')

    def test_clue_difference_on_fixed_route(self):
        state=GridState(5)
        paint(state,[(0,0),(0,1),(1,0),(1,1)])
        state.grid[0][0].starting_number=1
        state.grid[0][1].starting_number=8
        report=state.validate_partial()
        self.assertEqual(report['number_contradictions'],2)
        self.assertTrue(any('differs' in s for s in report['checks'][0]['reasons']))

    def test_shapes_and_required_capitols_are_checked(self):
        state=GridState(5)
        paint(state,[(0,0),(0,1),(0,2),(1,0)])
        self.assertEqual(state.validate_partial()['invalid_state_count'],1)
        state=GridState(5)
        paint(state,[(0,0),(0,1),(1,0),(1,1)])
        state.grid[0][0].starting_number=0
        report=state.validate_partial()
        self.assertFalse(report['consistent'])
        self.assertEqual(report['number_contradictions'],1)

    def test_every_partial_reveal_of_verified_solution_passes(self):
        # Previously verified 5x5 solution. Reveal complete states in all
        # 16 combinations; optimistic bounds must never reject the solution.
        labels=['ABBCC','ABBDC','AADDC','CAAAC','CCCCC']
        colors={letter:'#%06x'%(i+1) for i,letter in enumerate('ABCD')}
        for subset in range(16):
            state=new_workspace(5).saved
            for r,row in enumerate(labels):
                for c,letter in enumerate(row):
                    if subset & (1<<'ABCD'.index(letter)):
                        state.grid[r][c].region_color=colors[letter]
            before=state.to_dict()
            report=state.validate_partial()
            self.assertTrue(report['consistent'],(subset,report['checks']))
            self.assertEqual(state.to_dict(),before)
            if subset==15:
                self.assertEqual(report['fixed_match_count'],10)
                self.assertEqual(report['unresolved_count'],0)

    def test_highlighted_paths_match_weighted_bounds_and_can_take_a_detour(self):
        state = GridState(5)
        paint(state, [(0, 0)], '#111111')
        paint(state, [(0, c) for c in range(1, 5)], '#222222')
        state.grid[0][4].starting_number = 8
        before = state.to_dict()
        report = state.validate_partial(include_paths=True)
        check = report['checks'][0]
        self.assertEqual(check['paths']['known']['cost'], 6)
        self.assertEqual(check['paths']['upper']['cost'], 13)
        self.assertEqual(check['paths']['lower']['cost'], 1)
        self.assertTrue(check['paths']['known']['provisional'])
        self.assertFalse(check['paths']['upper']['provisional'])
        areas = state.region_areas()
        for kind, bound in [('known','unit_cost_to_known_capitol'), ('lower','lower_bound'), ('upper','upper_bound')]:
            path = check['paths'][kind]
            self.assertEqual(path['cells'][0], [0, 4])
            self.assertEqual(path['cells'][-1], path['destination'])
            self.assertEqual(path['cost'], check[bound])
            cost = 0
            for (r,c),(rr,cc) in zip(path['cells'],path['cells'][1:]):
                self.assertEqual(abs(r-rr)+abs(c-cc), 1)
                cost += min(areas[r][c] or 1, areas[rr][cc] or 1)
            self.assertEqual(cost, path['cost'])
        self.assertEqual(check['paths']['known']['destination'], [0, 0])
        self.assertEqual(state.to_dict(), before)
        self.assertNotIn('paths', state.validate_partial()['checks'][0])

    def test_paths_handle_unreachable_capitols_and_zero_step_routes(self):
        state = GridState(5)
        paint(state, [(r,c) for r in range(5) for c in range(5)])
        state.grid[0][0].starting_number = 3
        check = state.validate_partial(include_paths=True)['checks'][0]
        self.assertEqual(check['paths'], {'known':None, 'lower':None, 'upper':None})
        state = GridState(5)
        state.grid[2][2].starting_number = 0
        paint(state, [(2,2)])
        check = state.validate_partial(include_paths=True)['checks'][0]
        for path in check['paths'].values():
            self.assertEqual(path['cells'], [[2,2]])
            self.assertEqual(path['cost'], 0)

    def test_old_notes_are_migrated_out_without_changing_clues(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'project.json'
            original=new_workspace(5)
            original.save(path)
            data=json.loads(path.read_text())
            for row in data['grid']:
                for cell in row:cell['user_number']=999
            data['histories']['numbers']={'states':[[[999]*5 for _ in range(5)]], 'labels':['Old notes'], 'cursor':0}
            path.write_text(json.dumps(data))
            loaded=Workspace.load(path)
            self.assertEqual(loaded.saved.to_dict(),original.saved.to_dict())
            self.assertNotIn('numbers',loaded.histories)
            with self.assertRaises(ValueError):
                loaded.edit('numbers',[[0,0]],10)
            loaded.save(path)
            self.assertNotIn('user_number',path.read_text())
            self.assertNotIn('"numbers"',path.read_text())

class CandidateBorderCheckTests(unittest.TestCase):
    def test_other_asymmetric_paint_can_grow_without_blocking_candidates(self):
        from candidate_search import search_candidates
        state=GridState(5)
        paint(state,[(0,0)],'#111111')
        paint(state,[(3,2),(3,3),(3,4),(4,2)],'#222222')
        before=state.to_dict()
        unchecked=search_candidates(state,0,0,max_area=1,respect_paint=True)
        checked=search_candidates(state,0,0,max_area=1,respect_paint=True,check_borders=True)
        self.assertEqual(unchecked['survivor_count'],1)
        self.assertEqual(checked['survivor_count'],1)
        self.assertEqual(checked['heatmap'][0][0],1)
        self.assertEqual(checked['paint_mode'],'partial')
        self.assertTrue(checked['border_check_enabled'])
        self.assertEqual(state.to_dict(),before)
        ignored=search_candidates(state,0,0,max_area=1,respect_paint=False,check_borders=True)
        self.assertEqual(ignored['survivor_count'],1)

    def test_other_painted_route_is_not_a_fixed_upper_bound(self):
        state = GridState(5)
        paint(state, [(0, 0)], '#111111')
        # A 1x3 footprint has no derived capitol yet. Growing this state
        # changes its area and the cost to its required zero-clue capitol.
        paint(state, [(4, 2), (4, 3), (4, 4)], '#222222')
        state.grid[4][2].starting_number = 0
        state.grid[4][4].starting_number = 8
        self.assertFalse(state.validate_partial()['consistent'])
        result = state.candidate_states(0, 0, 1, respect_paint=True, check_borders=True)
        self.assertEqual(result['survivor_count'], 1)

    def test_partial_reveals_of_other_states_preserve_a_known_solution_candidate(self):
        labels = ['ABBCC','ABBDC','AADDC','CAAAC','CCCCC']
        colors = {letter: '#%06x' % (i+1) for i,letter in enumerate('ABCD')}
        expected = {(1,3), (2,2), (2,3)}
        for cutoff in range(1, 26):
            with self.subTest(cutoff=cutoff):
                state = new_workspace(5).saved
                for r, row in enumerate(labels):
                    for c, letter in enumerate(row):
                        if letter == 'D' or r*5+c < cutoff:
                            state.grid[r][c].region_color = colors[letter]
                before = state.to_dict()
                result = state.candidate_states(1, 3, 3, respect_paint=True,
                                                respect_stars=True, check_borders=True)
                self.assertEqual(result['survivor_count'], 1)
                self.assertEqual(set(map(tuple, result['survivors'][0]['cells'])), expected)
                self.assertEqual(state.to_dict(), before)

    def test_valid_small_candidate_survives_with_painted_neighbor_groups(self):
        from candidate_search import search_candidates
        state=new_workspace(5).saved
        labels=['ABBCC','ABBDC','AADDC','CAAAC','CCCCC']
        colors={letter:'#%06x'%(i+1) for i,letter in enumerate('ABCD')}
        for r,row in enumerate(labels):
            for c,letter in enumerate(row):
                state.grid[r][c].region_color=colors[letter]
        result=search_candidates(state,1,3,max_area=3,respect_paint=True,check_borders=True)
        self.assertEqual(result['survivor_count'],1)
        self.assertEqual(set(map(tuple,result['survivors'][0]['cells'])),{(1,3),(2,2),(2,3)})
        self.assertGreater(result['border_checks'],0)


if __name__=='__main__':unittest.main()
