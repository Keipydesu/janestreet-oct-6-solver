import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from model import Workspace, GridState
from app import make_server

class ModelTests(unittest.TestCase):
    def test_defined_starting_grid_and_required_capitals(self):
        from starting_grid import new_workspace, CLUES
        w = new_workspace()
        self.assertEqual(len(CLUES), 33)
        self.assertEqual(sum(cell.starting_number is not None for row in w.grid for cell in row), 33)
        self.assertEqual(w.grid[3][3].starting_number, 51)
        self.assertEqual(w.grid[10][9].starting_number, 61)
        for r, c in [(5,7), (10,5)]:
            self.assertEqual(w.grid[r][c].starting_number, 0)
            self.assertTrue(w.grid[r][c].is_capital)
            self.assertTrue(w.grid[r][c].capital_required)
            with self.assertRaises(ValueError):
                w.edit('capitals', [[r,c]], False)
            with self.assertRaises(ValueError):
                w.edit('experimental', [[r,c]], False, 'capitals')
        w.edit('capitals', [[0,0]], True)
        w.restore_history('capitals', 0)
        self.assertTrue(w.grid[5][7].is_capital)
        self.assertFalse(w.grid[0][0].is_capital)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'project.json'
            w.save(p)
            loaded = Workspace.load(p)
            self.assertTrue(loaded.grid[10][5].capital_required)

    def test_movement_heatmap_budget_and_isolation(self):
        state = GridState()
        state.grid[5][5].starting_number = 2
        before = state.to_dict()
        heat = state.movement_heatmap(5,5)
        self.assertEqual(heat[5][5],2)
        self.assertEqual(heat[5][6],1)
        self.assertEqual(heat[6][6],0)
        self.assertIsNone(heat[5][8])
        self.assertEqual(sum(x is not None for row in heat for x in row),13)
        heat[0][0]=999
        self.assertEqual(state.to_dict(),before)
        self.assertIsNone(state.movement_heatmap(5,5)[0][0])

    def test_movement_heatmap_zero_edges_and_invalid_source(self):
        state = GridState()
        state.grid[0][0].starting_number=0
        heat=state.movement_heatmap(0,0)
        self.assertEqual(heat[0][0],0)
        self.assertEqual(sum(x is not None for row in heat for x in row),1)
        state.grid[0][0].starting_number=1
        self.assertEqual(sum(x is not None for row in state.movement_heatmap(0,0) for x in row),3)
        state.grid[0][0].starting_number=77
        self.assertEqual(state.movement_heatmap(0,0)[10][10],57)
        with self.assertRaises(ValueError): state.movement_heatmap(0,1)
        with self.assertRaises(ValueError): state.movement_heatmap(-1,0)
        state.grid[0][0].starting_number=-1
        with self.assertRaises(ValueError): state.movement_heatmap(0,0)

    def test_movement_heatmap_region_detour(self):
        state = GridState()
        state.grid[0][0].starting_number=4
        with self.assertRaises(ValueError): state.movement_heatmap(0,0,True)
        for r,c in [(0,0),(1,0),(1,1),(1,2),(0,2),(5,5)]:
            state.grid[r][c].region_color='#abcdef'
        heat=state.movement_heatmap(0,0,True)
        self.assertEqual(heat[0][2],0)  # four-step detour, not Manhattan two
        self.assertIsNone(heat[0][1])
        self.assertIsNone(heat[5][5])  # disconnected, same color
        self.assertEqual(state.movement_heatmap(0,0)[0][2],2)

    def test_all_clues_heatmap_combines_sources(self):
        state=GridState()
        state.grid[0][0].starting_number=1
        state.grid[0][2].starting_number=2
        state.grid[10][10].starting_number=0
        combined=state.all_clues_heatmap()
        self.assertEqual(len(combined['sources']),3)
        self.assertEqual(combined['heatmap'][0][1],2)
        self.assertEqual(combined['heatmap'][10][10],1)
        self.assertEqual(combined['heatmap'][5][5],0)
        minimum=state.all_clues_heatmap('min_remaining')['heatmap']
        self.assertEqual(minimum[0][1],0)
        self.assertIsNone(minimum[5][5])

    def test_smart_weighted_costs_and_nearest_capital(self):
        state=GridState()
        for r,c in [(0,0),(0,1)]: state.grid[r][c].region_color='#aaaaaa'
        for r,c in [(0,2),(0,3),(1,3)]: state.grid[r][c].region_color='#bbbbbb'
        state.grid[0][0].is_capital=True
        state.grid[0][3].starting_number=7
        result=state.smart_heatmap()
        self.assertEqual(result['heatmap'][0][:4],[0,2,4,7])
        self.assertEqual(result['heatmap'][1][3],10)
        self.assertEqual(result['checks'][0]['status'],'provisional_match')
        self.assertIsNone(result['heatmap'][5][5])
        state.grid[1][3].is_capital=True
        result=state.smart_heatmap()
        self.assertEqual(result['heatmap'][0][3],3)
        self.assertEqual(result['nearest_capitals'][0][3],[1,3])
        self.assertEqual(result['heatmap'][0][2],4)

    def test_smart_same_color_disconnected_states_and_unknowns(self):
        state=GridState()
        for r,c in [(0,0),(0,1),(0,3)]: state.grid[r][c].region_color='#aaaaaa'
        state.grid[0][2].region_color='#bbbbbb'
        state.grid[0][3].is_capital=True
        state.grid[10][10].is_capital=True
        result=state.smart_heatmap()
        self.assertEqual(result['state_sizes'][0][:4],[2,2,1,1])
        self.assertEqual(result['heatmap'][0][:4],[4,2,1,0])
        self.assertEqual(result['heatmap'][10][10],0)
        self.assertIsNone(result['heatmap'][9][10])
        self.assertFalse(result['complete'])

    def test_smart_complete_map_validation_and_no_capitals(self):
        state=GridState()
        for row in state.grid:
            for cell in row: cell.region_color='#aaaaaa'
        self.assertIsNone(state.smart_heatmap()['heatmap'][0][0])
        state.grid[0][0].is_capital=True
        state.grid[0][1].starting_number=121
        state.grid[0][2].starting_number=1
        result=state.smart_heatmap()
        self.assertTrue(result['complete'])
        self.assertEqual(result['heatmap'][0][2],242)
        self.assertEqual([c['status'] for c in result['checks']],['match','mismatch'])

    def test_capitol_rule_rejects_bar_and_x_pentomino(self):
        # The X pentomino is the five-square cross; axes fix three squares.
        for cells in ([(0,0),(0,1),(0,2)], [(0,1),(1,0),(1,1),(1,2),(2,1)]):
            state=GridState()
            for r,c in cells: state.grid[r][c].region_color='#aaaaaa'
            region=state.validate_regions()['regions'][0]
            self.assertTrue(region['valid_state'])
            self.assertIsNone(region['capitol'])
            self.assertEqual(region['status'],'valid_without_capitol')
            self.assertTrue(any(op['fixed_count']>1 for op in region['symmetry']['operations']))

    def test_capitol_rule_singleton_elbow_and_asymmetric(self):
        state=GridState()
        state.grid[4][5].region_color='#aaaaaa'
        self.assertEqual(state.validate_regions()['derived_capitols'],[[4,5]])
        state=GridState()
        for r,c in [(3,4),(4,4),(4,5)]: state.grid[r][c].region_color='#aaaaaa'
        region=state.validate_regions()['regions'][0]
        self.assertEqual(region['capitol'],[4,4])
        state.grid[5][4].region_color='#aaaaaa'
        # T tetromino reflects in horizontal axis, fixing TWO squares.
        region=state.validate_regions()['regions'][0]
        self.assertTrue(region['valid_state'])
        self.assertIsNone(region['capitol'])
        state=GridState()
        for r,c in [(0,0),(1,0),(2,0),(2,1)]: state.grid[r][c].region_color='#aaaaaa'
        self.assertFalse(state.validate_regions()['regions'][0]['valid_state'])

    def test_even_symmetries_markers_and_zero_clue_conflicts(self):
        state=GridState()
        for r in range(2):
            for c in range(2): state.grid[r][c].region_color='#aaaaaa'
        state.grid[0][0].is_capital=True
        state.grid[0][0].starting_number=0
        report=state.validate_regions()
        region=report['regions'][0]
        self.assertIsNone(region['capitol'])
        self.assertTrue(any(op['fixed_count']==0 for op in region['symmetry']['operations']))
        self.assertEqual(region['required_conflicts'],[[0,0]])
        self.assertEqual(region['incorrect_markers'],[[0,0]])
        self.assertEqual(region['status'],'capital_conflict')
        self.assertIsNone(state.validate_puzzle()['puzzle_valid'])

    def test_derived_smart_capitals_and_full_puzzle_validation(self):
        state=GridState()
        for r in range(11):
            for c in range(11):
                state.grid[r][c].region_color='#aaaaaa' if (r+c)%2 else '#bbbbbb'
                state.grid[r][c].starting_number=0
        # 121 disconnected singleton states, every square its own derived capitol.
        report=state.validate_puzzle()
        self.assertTrue(report['partition_valid'])
        self.assertTrue(report['puzzle_valid'])
        self.assertEqual(len(report['derived_capitols']),121)
        self.assertTrue(all(v==0 for row in state.smart_heatmap(True)['heatmap'] for v in row))
        self.assertIsNone(state.smart_heatmap(False)['heatmap'][0][0])
        state.grid[0][0].starting_number=1
        self.assertFalse(state.validate_puzzle()['puzzle_valid'])

    def test_actual_puzzle_forces_singleton_and_propagates_bounds(self):
        from starting_grid import new_workspace
        state=new_workspace().saved
        before=state.to_dict()
        report=state.deductions()
        self.assertIn([5,10],report['forced_singletons'])  # R6 C11
        group=next(g for g in report['one_clues'] if g['clue']==[4,10])
        self.assertEqual(group['candidates'],[[5,10]])
        self.assertEqual(report['minimum_state_sizes'][6][9],8)  # 9 at R7 C10
        self.assertEqual(report['minimum_state_sizes'][5][9],8)
        self.assertEqual(report['minimum_state_sizes'][6][10],12)  # 13 at R8 C11 gives stronger bound
        self.assertEqual(report['minimum_state_sizes'][10][8],16)
        self.assertEqual(report['minimum_state_sizes'][10][9],16)
        self.assertEqual(state.to_dict(),before)
        self.assertFalse(report['contradictions'])

    def test_deductions_do_not_treat_paint_as_proof(self):
        state=GridState();state.grid[5][5].starting_number=1
        for row in state.grid:
            for cell in row: cell.region_color='#aaaaaa'
        report=state.deductions()
        self.assertEqual(len(report['one_clues'][0]['candidates']),4)
        self.assertEqual(report['forced_singletons'],[])
        state.grid[5][5].starting_number=0.5
        self.assertFalse(state.deductions()['available'])

    def test_deductions_contradiction(self):
        state=GridState();state.grid[0][0].starting_number=1
        state.grid[0][1].starting_number=2;state.grid[1][0].starting_number=2
        self.assertEqual(len(state.deductions()['contradictions']),1)

    def test_weighted_all_clues_updates_after_region_edit_and_undo(self):
        w=Workspace();w.edit('starting',[[0,0]],2)
        self.assertEqual(w.saved.all_clues_heatmap()['heatmap'][0][1],1)
        w.edit('regions',[[0,0],[0,1],[1,0]],'#abcdef')
        result=w.saved.all_clues_heatmap()
        self.assertEqual(result['heatmap'][0][1],0)  # first step costs 3
        self.assertEqual(w.saved.all_clues_heatmap(use_region_sizes=False)['heatmap'][0][1],1)
        w.restore_history('regions',0)
        self.assertEqual(w.saved.all_clues_heatmap()['heatmap'][0][1],1)

    def test_weighted_movement_region_restriction(self):
        w=Workspace();w.edit('starting',[[0,0]],4)
        with self.assertRaises(ValueError): w.saved.weighted_movement_heatmap(0,0,True)
        w.edit('regions',[[0,0],[0,1],[5,5]],'#abcdef')
        heat=w.saved.weighted_movement_heatmap(0,0,True)
        self.assertEqual(heat[0][0],4)
        self.assertEqual(heat[0][1],2)
        self.assertIsNone(heat[1][0])
        self.assertIsNone(heat[5][5])

    def test_cells_independent(self):
        w = Workspace()
        w.grid[0][0].is_capital = True
        self.assertFalse(w.grid[0][1].is_capital)
        self.assertFalse(w.grid[1][0].is_capital)
        self.assertFalse(w.experimental.grid[0][0].is_capital)

    def test_components_and_diagonals(self):
        w = Workspace()
        w.edit('regions', [[0,0],[0,1],[1,2],[5,5]], '#ABCDEF')
        a = w.saved.region_areas()
        self.assertEqual([a[0][0],a[0][1],a[1][2],a[5][5],a[10][10]], [2,2,1,1,0])
        w.edit('regions', [[0,2]], '#abcdef')
        self.assertEqual(w.saved.region_areas()[1][2], 4)
        w.restore_history('regions', 1)
        self.assertEqual(w.saved.region_areas()[1][2], 1)

    def test_undo_isolation_and_branch(self):
        w = Workspace()
        w.edit('regions', [[0,0]], '#abcdef')
        w.edit('starting', [[0,0]], 9)
        w.edit('capitals', [[0,0]], True)
        w.restore_history('starting', 0)
        self.assertEqual(w.grid[0][0].region_color, '#abcdef')
        self.assertTrue(w.grid[0][0].is_capital)
        self.assertIsNone(w.grid[0][0].starting_number)
        w.edit('starting', [[0,0]], 4)
        self.assertEqual(len(w.histories['starting'].states), 2)
        self.assertFalse(w.histories['starting'].view()['can_redo'])

    def test_experiment_save_load(self):
        w = Workspace()
        w.edit('starting', [[1,2]], 7)
        w.edit('capitals', [[1,2]], True)
        w.reset_experiment()
        w.edit('experimental', [[1,2]], False, 'capitals')
        w.edit('experimental', [[1,2]], 99, 'starting')
        self.assertTrue(w.grid[1][2].is_capital)
        self.assertEqual(w.grid[1][2].starting_number, 7)
        w.restore_history('experimental', 1)
        self.assertTrue(w.experimental.grid[1][2].is_capital)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'project.json'
            w.save(p)
            self.assertNotIn('experimental', json.loads(p.read_text())['histories'])
            loaded = Workspace.load(p)
            self.assertEqual(loaded.experimental.grid[1][2].starting_number, 7)
            loaded.restore_history('capitals', 0)
            self.assertFalse(loaded.grid[1][2].is_capital)
            self.assertTrue(loaded.payload()['dirty'])

    def test_symmetry_square_rectangle_and_single(self):
        for cells in ([(0,0)], [(3,4),(3,5),(4,4),(4,5)]):
            sym = GridState.shape_symmetry(cells)
            self.assertEqual(sym['rotations'], [90,180,270])
            self.assertEqual(len(sym['reflections']), 4)
        rectangle = GridState.shape_symmetry([(r,c) for r in range(2) for c in range(3)])
        self.assertEqual(rectangle['rotations'], [180])
        self.assertEqual(rectangle['reflections'], ['horizontal','vertical'])

    def test_symmetry_rotation_only_reflection_only_and_neither(self):
        zigzag = GridState.shape_symmetry([(0,1),(0,2),(1,0),(1,1)])
        self.assertEqual(zigzag['rotations'], [180])
        self.assertEqual(zigzag['reflections'], [])
        elbow = GridState.shape_symmetry([(0,0),(1,0),(1,1)])
        self.assertEqual(elbow['rotations'], [])
        self.assertEqual(elbow['reflections'], ['anti_diagonal'])
        asymmetric = GridState.shape_symmetry([(0,0),(1,0),(2,0),(2,1)])
        self.assertFalse(asymmetric['symmetric'])
        with self.assertRaises(ValueError):
            GridState.shape_symmetry([])

    def test_symmetry_matches_brute_force_reference_on_random_shapes(self):
        """shape_symmetry uses analytic bounding-box offsets per transform
        instead of re-scanning for a translation each time; this checks the
        optimized path against a naive brute-force transform+translate+compare
        on many random (including disconnected, negative-coordinate) shapes.
        """
        import random

        def brute_force(cells):
            cells = set(tuple(cell) for cell in cells)

            def normalize(points):
                points = set(points)
                r0 = min(r for r, c in points)
                c0 = min(c for r, c in points)
                return frozenset((r - r0, c - c0) for r, c in points)

            original = normalize(cells)
            rotations = {90: lambda r, c: (-c, r), 180: lambda r, c: (-r, -c), 270: lambda r, c: (c, -r)}
            reflections = {'horizontal': lambda r, c: (-r, c), 'vertical': lambda r, c: (r, -c),
                           'main_diagonal': lambda r, c: (c, r), 'anti_diagonal': lambda r, c: (-c, -r)}
            angles = [a for a, t in rotations.items() if normalize(t(r, c) for r, c in cells) == original]
            axes = [a for a, t in reflections.items() if normalize(t(r, c) for r, c in cells) == original]
            base_r, base_c = min(r for r, c in cells), min(c for r, c in cells)
            operations = []
            for kind, table, names in (('rotation', rotations, angles), ('reflection', reflections, axes)):
                for name in names:
                    transform = table[name]
                    moved = {cell: transform(*cell) for cell in cells}
                    dr = base_r - min(r for r, c in moved.values())
                    dc = base_c - min(c for r, c in moved.values())
                    fixed = sorted([list(cell) for cell, (r, c) in moved.items() if cell == (r + dr, c + dc)])
                    operations.append({'kind': kind, 'name': name, 'fixed_cells': fixed, 'fixed_count': len(fixed)})
            return {'rotations': angles, 'reflections': axes, 'symmetric': bool(angles or axes),
                    'operations': sorted((o['kind'], o['name'], o['fixed_count'], tuple(map(tuple, o['fixed_cells'])))
                                          for o in operations)}

        rng = random.Random(1234)
        for sample in range(500):
            n = rng.randint(1, 10)
            cells = {(rng.randint(-5, 5), rng.randint(-5, 5))}
            while len(cells) < n:
                r, c = rng.choice(list(cells))
                dr, dc = rng.choice([(-1, 0), (1, 0), (0, -1), (0, 1)])
                cells.add((r + dr, c + dc))
            if sample % 2:
                # Neighbor growth above is always connected. An isolated cell
                # exercises arbitrary disconnected inputs as well.
                cells.add((max(r for r, c in cells) + 3, 0))
            shape = [list(cell) for cell in cells]
            fast = GridState.shape_symmetry(shape)
            fast_ops = sorted((o['kind'], o['name'], o['fixed_count'], tuple(map(tuple, o['fixed_cells'])))
                               for o in fast['operations'])
            reference = brute_force(shape)
            self.assertEqual(fast['rotations'], reference['rotations'], shape)
            self.assertEqual(fast['reflections'], reference['reflections'], shape)
            self.assertEqual(fast['symmetric'], reference['symmetric'], shape)
            self.assertEqual(fast_ops, reference['operations'], shape)

    def test_region_symmetries_keep_disconnected_colors_separate(self):
        w = Workspace()
        w.edit('regions', [[0,0],[0,1],[5,5]], '#abcdef')
        w.edit('capitals', [[0,0]], True)
        w.edit('starting', [[0,0]], 9)
        regions = w.saved.region_symmetries()
        self.assertEqual([r['area'] for r in regions], [2,1])
        self.assertEqual(regions[0]['symmetry']['rotations'], [180])
        self.assertEqual(regions[1]['symmetry']['rotations'], [90,180,270])

    def test_atomic_invalid_edit(self):
        w = Workspace()
        with self.assertRaises(ValueError):
            w.edit('starting', [[0,0],[12,0]], 3)
        self.assertIsNone(w.grid[0][0].starting_number)
        for v in (True, float('nan'), float('inf'), '2'):
            with self.assertRaises(ValueError):
                w.edit('starting', [[0,0]], v)
        with self.assertRaises(ValueError):
            w.edit('capitals', [[0,0]], 1)

    def test_math_and_empty(self):
        w = Workspace()
        w.edit('starting', [[1,1]], 2.5)
        self.assertEqual(sum(map(sum, w.saved.numbers())), 2.5)
        self.assertEqual(w.saved.region_areas(), [[0]*11 for _ in range(11)])

    def test_corrupt_history_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'project.json'
            w = Workspace()
            w.save(p)
            data = json.loads(p.read_text())
            data['histories']['capitals']['states'][0][0][0] = True
            p.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                Workspace.load(p)

class ServerTests(unittest.TestCase):
    def test_http_edit_save_and_auth(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'project.json'
            server = make_server(p, 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f'http://127.0.0.1:{server.server_port}'
            try:
                with urlopen(url) as r:
                    html = r.read().decode()
                token = html.split("const token='")[1].split("'")[0]
                def post(path, data, key=token):
                    request = Request(url+'/api/'+path, data=json.dumps(data).encode(), headers={'X-Grid-Token':key,'Content-Type':'application/json'})
                    with urlopen(request) as r:
                        return json.load(r)
                try:
                    post('edit', {}, 'wrong')
                    self.fail('Unauthenticated mutation was accepted')
                except HTTPError as error:
                    self.assertEqual(error.code, 403)
                    error.close()
                heat = post('heatmap', {'source':[0,1]})
                combined = post('heatmap', {'kind':'allheat'})
                self.assertEqual(len(combined['sources']),33)
                candidates = post('heatmap', {'kind':'candidates','source':[5,10],'max_area':7})
                self.assertTrue(candidates['border_check_enabled'])
                self.assertTrue(candidates['exhaustive'])
                self.assertEqual(candidates['forced_cells'],[[5,10]])
                deductions = post('heatmap', {'kind':'deductions'})
                self.assertIn([5,10],deductions['forced_singletons'])
                report = post('heatmap', {'kind':'validation'})
                self.assertEqual(report['uncolored_count'],121)
                smart = post('heatmap', {'kind':'smartheat', 'use_derived_capitals':False})
                self.assertEqual(smart['heatmap'][5][7],0)
                self.assertFalse(smart['complete'])
                self.assertEqual(heat['heatmap'][0][1],8)
                self.assertEqual(heat['heatmap'][0][2],7)
                self.assertIsNone(heat['heatmap'][10][10])
                post('edit', {'layer':'regions','cells':[[0,1],[0,2],[1,1]],'value':'#abcdef'})
                weighted = post('heatmap', {'source':[0,1]})
                self.assertTrue(weighted['use_region_sizes'])
                self.assertEqual(weighted['heatmap'][0][2],5)
                unit = post('heatmap', {'source':[0,1],'use_region_sizes':False})
                self.assertEqual(unit['heatmap'][0][2],7)
                post('history', {'layer':'regions','index':0})
                self.assertEqual(post('heatmap', {'source':[0,1]})['heatmap'][0][2],7)
                result = post('edit', {'layer':'capitals','cells':[[0,0]],'value':True})
                self.assertTrue(result['main'][0][0]['is_capital'])
                post('save', {})
                self.assertTrue(p.exists())
                result = post('load', {})
                self.assertTrue(result['experimental'][0][0]['is_capital'])
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

if __name__ == '__main__':
    unittest.main()
