"""Small puzzle routing, persistence, and board-edge regression checks."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from app import make_server
from starting_grid import new_workspace, SMALL_CLUES


class SmallGridTests(unittest.TestCase):
    def test_small_candidates_respect_edges(self):
        state = new_workspace(5).saved
        for strategy in ('symmetry_orbits', 'connected_growth'):
            from candidate_search import search_candidates
            result = search_candidates(state, 4, 4, 3, strategy=strategy)
            self.assertEqual(len(result['heatmap']), 5)
            self.assertTrue(all(0 <= r < 5 and 0 <= c < 5
                                for item in result['survivors'] for r, c in item['cells']))
        with self.assertRaises(ValueError):
            state.candidate_states(5, 0, 3)

    def test_full_small_decomposition_is_independently_valid(self):
        from solver import solve
        from model import GridState
        state = new_workspace(5).saved
        before = state.to_dict()
        report = solve(state, seconds=8, per_root_seconds=.08)
        self.assertEqual(report['status'], 'verified_solution')
        self.assertEqual(state.to_dict(), before)
        result = GridState.from_dict(report['solution'])
        self.assertTrue(result.validate_puzzle()['puzzle_valid'])
        self.assertEqual(sum(region['area'] for region in result.connected_regions()), 25)
        self.assertEqual(report['board_cells'], 25)

    def test_small_timeout_is_not_impossibility(self):
        from solver import solve
        report = solve(new_workspace(5).saved, seconds=0)
        self.assertEqual(report['status'], 'time_limit')
        self.assertIsNone(report['solution'])

    def test_routes_and_saved_histories_are_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / 'project.json'
            server = make_server(project, 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            def get(path):
                with urlopen(base + path) as response:
                    return response.read().decode()
            try:
                html = get('/small')
                self.assertIn('const SIZE=5', html)
                self.assertIn("apiBase='/small/api/'", html)
                token = html.split("const token='")[1].split("'")[0]
                def post(action, data=None):
                    request = Request(base + '/small/api/' + action,
                                      data=json.dumps(data or {}).encode(),
                                      headers={'X-Grid-Token': token, 'Content-Type': 'application/json'})
                    with urlopen(request) as response:
                        return json.load(response)
                grid = json.loads(get('/small/api/state'))['main']
                self.assertEqual(len(grid), 5)
                self.assertEqual({(r+1,c+1): cell['starting_number'] for r,row in enumerate(grid)
                                  for c,cell in enumerate(row) if cell['starting_number'] is not None}, SMALL_CLUES)
                post('edit', {'layer': 'regions', 'cells': [[4, 4]], 'value': '#abcdef'})
                post('save')
                post('history', {'layer': 'regions', 'index': 0})
                self.assertEqual(post('load')['main'][4][4]['region_color'], '#abcdef')
                for kind in ('heatmap', 'allheat', 'smartheat', 'deductions', 'partial'):
                    result = post('heatmap', {'kind': kind, 'source': [4, 4]})
                    self.assertEqual(len(result['heatmap']), 5)
                    if kind == 'partial':
                        self.assertIn('paths', result['checks'][0])
                self.assertEqual(post('heatmap', {'kind': 'validation'})['uncolored_count'], 24)
                candidates = post('heatmap', {'kind': 'candidates', 'source': [4, 4],
                                              'max_area': 3, 'respect_stars': True})
                self.assertTrue(candidates['respect_stars'])
                self.assertTrue(candidates['conditional'])
                before = json.loads(get('/small/api/state'))
                report = post('decompose')
                self.assertEqual(report['status'], 'verified_solution')
                self.assertEqual(json.loads(get('/small/api/state')), before)
                applied = post('apply-decomposition')
                self.assertEqual(applied['main'], before['main'])
                self.assertEqual(applied['experimental'], report['solution'])
                restored = post('history', {'layer': 'experimental', 'index': 0})
                self.assertEqual(restored['experimental'], before['experimental'])
                original = json.loads(get('/api/state'))['main']
                self.assertEqual(len(original), 11)
                self.assertIsNone(original[4][4]['region_color'])
                self.assertFalse(project.exists())
                self.assertTrue(project.with_name('project-small.json').exists())
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
