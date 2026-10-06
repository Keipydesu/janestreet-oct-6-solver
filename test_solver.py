import unittest
from model import GridState
from solver import distances, materialize, travel_feasible, solve, N, TravelConstraints


class SolverTests(unittest.TestCase):
    def test_exhausted_sample_expands_and_restarts_search(self):
        from unittest.mock import patch
        from collections import Counter
        calls = Counter()

        def sampled(state, row, col, **kwargs):
            root = row*11+col
            calls[root] += 1
            expanded = calls[root] > 1
            return {'complete_within_limit': expanded,
                    'survivors': [{'cells': [[row,col]], 'capitol': [row,col]}]
                    if expanded else []}

        with patch('solver.search_candidates', side_effect=sampled):
            report = solve(GridState(), seconds=10, max_area=1)
        self.assertEqual(report['status'], 'verified_solution')
        self.assertGreater(report['statistics']['search_rounds'], 1)
        self.assertEqual(report['generation_calls'], 2*N)
        self.assertTrue(GridState.from_dict(report['solution']).validate_puzzle()['puzzle_valid'])

    def test_exhausted_complete_generation_does_not_retry(self):
        from unittest.mock import patch
        with patch('solver.search_candidates', return_value={
                'complete_within_limit': True, 'survivors': []}) as search:
            report = solve(GridState(), seconds=10, max_area=1)
        self.assertEqual(report['status'], 'sample_exhausted')
        self.assertEqual(search.call_count, N)

    def test_clue_pair_prunes_without_a_known_capitol(self):
        state = GridState()
        state.grid[0][0].starting_number = 10
        state.grid[0][2].starting_number = 40
        # No zero clues: bounds to mandatory capitols alone cannot reject this.
        # Two edges of at most 10 cannot bridge a distance difference of 30.
        self.assertEqual(TravelConstraints(state).rejection([], 10), 'clue_path')

    def test_candidate_sizes_tighten_clue_pair_routes(self):
        state = GridState()
        state.grid[0][0].starting_number = 5
        state.grid[0][2].starting_number = 10
        self.assertTrue(travel_feasible(state, [], 121))
        candidates = [((1 << i) | (1 << (i+1)), None)
                      for i in range(N) if i % 11 < 10]
        domains = {i: [k for k,(mask,_) in enumerate(candidates) if mask & (1 << i)]
                   for i in range(N)}
        self.assertEqual(TravelConstraints(state).rejection([], 121, domains, candidates),
                         'clue_path')

    def test_pool_without_any_capitol_is_rejected(self):
        candidates = [(sum(1 << (r*11+c) for c in range(11)), None) for r in range(11)]
        domains = {i: [i//11] for i in range(N)}
        self.assertFalse(travel_feasible(GridState(), [], 121, domains, candidates))

    def test_valid_partition_survives_partial_domain_bounds(self):
        import random
        # Ten capitol-free 1x11 states and eleven singleton capitols.
        partition = [(sum(1 << (r*11+c) for c in range(11)), None) for r in range(10)]
        partition += [(1 << i, i) for i in range(110,121)]
        complete = materialize(GridState(), partition)
        actual = complete.smart_heatmap(use_derived_capitals=True)['heatmap']
        state = GridState()
        for i in range(0,N,3):
            state.grid[i//11][i%11].starting_number = actual[i//11][i%11]
        self.assertTrue(materialize(state, partition).validate_puzzle()['puzzle_valid'])
        # Add alternatives so unchosen cell areas/capitol locations are uncertain.
        candidates = partition + [(1 << i,i) for i in range(110)]
        rng = random.Random(17)
        travel = TravelConstraints(state)
        for _ in range(30):
            chosen = rng.sample(partition, rng.randrange(len(partition)+1))
            occupied = sum(mask for mask,_ in chosen)
            domains = {i: [k for k,(mask,_) in enumerate(candidates)
                           if mask & (1 << i) and not mask & occupied]
                       for i in range(N) if not occupied & (1 << i)}
            self.assertIsNone(travel.rejection(chosen,121,domains,candidates))

    def test_weighted_crossing(self):
        areas = [5]*N
        areas[1] = 2
        self.assertEqual(distances(areas,{0})[2],4)

    def test_cheaper_long_route_wins_over_fewer_steps(self):
        areas = [100]*N
        areas[11] = areas[12] = areas[13] = 1
        # Direct two-edge route costs 200; four-edge detour costs 4.
        self.assertEqual(distances(areas,{0})[2],4)

    def test_exact_complete_partition(self):
        state = GridState()
        state.grid[0][0].starting_number = 0
        chosen = [(1 << i,i) for i in range(N)]
        self.assertTrue(travel_feasible(state,chosen,20))
        self.assertTrue(materialize(state,chosen).validate_puzzle()['puzzle_valid'])
        state.grid[0][1].starting_number = 1
        self.assertFalse(travel_feasible(state,chosen,20))
        self.assertFalse(materialize(state,chosen).validate_puzzle()['puzzle_valid'])

    def test_candidate_cover_and_independent_verification(self):
        report = solve(GridState(),seconds=10,max_area=1,per_root_seconds=.05)
        self.assertEqual(report['status'],'verified_solution')
        self.assertTrue(GridState.from_dict(report['solution']).validate_puzzle()['puzzle_valid'])

    def test_twenty_square_limit_cannot_fit_supplied_clues(self):
        from starting_grid import new_workspace
        report = solve(new_workspace().saved,seconds=1,max_area=20)
        self.assertEqual(report['status'],'area_limit_contradiction')
        violation = next(v for v in report['violations'] if v['value']==77)
        self.assertEqual(violation['steps'],3)
        self.assertEqual(violation['required_maximum_state_area'],26)

    def test_timeout_not_impossibility(self):
        report = solve(GridState(),seconds=0)
        self.assertEqual(report['status'],'time_limit')
        self.assertIsNone(report['solution'])


if __name__ == '__main__':
    unittest.main()
