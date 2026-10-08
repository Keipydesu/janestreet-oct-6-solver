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

    def test_generation_expands_small_complete_stages_to_full_limit(self):
        from unittest.mock import patch
        calls = []
        def empty(state, row, col, **kwargs):
            calls.append((row, col, kwargs['max_area']))
            return {'complete_within_limit': True, 'survivors': []}
        with patch('solver.search_candidates', side_effect=empty):
            report = solve(GridState(3), seconds=5, max_area=9)
        self.assertEqual(report['status'], 'sample_exhausted')
        self.assertEqual([limit for _,_,limit in calls[:9]], [4]*9)
        for row in range(3):
            for col in range(3):
                self.assertEqual([limit for r,c,limit in calls if (r,c)==(row,col)],
                                 [4,8,9])
        self.assertEqual(report['complete_candidate_roots'], 9)

    def test_branching_prefers_fewer_area_choices_then_smaller_states(self):
        from solver import constrained_options
        candidates = [(3,None), (7,None), (15,None), (24,None)]
        domains = {0:[0,1], 3:[2], 4:[3]}
        self.assertEqual(constrained_options(domains,candidates), [3])
        self.assertEqual(constrained_options({0:[1,0]},candidates), [0,1])

    def test_equal_area_borders_share_signature_but_capitols_do_not(self):
        from solver import decomposition_signature
        horizontal = [(0b0011,None), (0b1100,None)]
        vertical = [(0b0101,None), (0b1010,None)]
        self.assertEqual(decomposition_signature(horizontal), decomposition_signature(vertical))
        self.assertNotEqual(decomposition_signature([(0b1111,None)]),
                            decomposition_signature(horizontal))
        self.assertNotEqual(decomposition_signature([(0b0111,0)]),
                            decomposition_signature([(0b0111,1)]))
        self.assertNotEqual(decomposition_signature(horizontal),
                            decomposition_signature([(0b0011,None)]))

    def test_equivalent_failed_partitions_are_not_revisited(self):
        from unittest.mock import patch, Mock
        # Two domino tilings of the top-left 2x2 block of a 3x3 board.
        # The remaining cells have a fixed tiling and a singleton capitol.
        shapes = [([0,1],None),([3,4],None),([0,3],None),([1,4],None),
                  ([2,5],None),([6,7],None),([8],8)]
        survivors = [{'cells':[list(divmod(i,3)) for i in cells],
                      'capitol':None if cap is None else list(divmod(cap,3))}
                     for cells,cap in shapes]
        invalid = Mock()
        invalid.validate_puzzle.return_value = {'puzzle_valid':False}
        # Isolate the search cache from travel rejection/final acceptance.
        with patch('solver.search_candidates', return_value={
                'complete_within_limit':True,'survivors':survivors}), \
             patch('solver.TravelConstraints.rejection', return_value=None), \
             patch('solver.materialize', return_value=invalid):
            report = solve(GridState(3),seconds=5,max_area=2)
        self.assertEqual(report['status'],'sample_exhausted')
        self.assertGreater(report['statistics'].get('equivalent_partition_prunes',0),0)
        self.assertEqual(invalid.validate_puzzle.call_count,1)

    def test_capitol_exclusions_follow_maximum_route_cost(self):
        from solver import forbidden_capitols
        state = GridState(3)
        state.grid[0][0].starting_number = 5
        excluded = forbidden_capitols(state,4)
        self.assertTrue({0,1,3} <= excluded)
        self.assertNotIn(8,excluded)
        # At an adjacent clue 4, a cost-4 edge can reach zero exactly.
        state.grid[0][0].starting_number = 4
        self.assertNotIn(1,forbidden_capitols(state,4))

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
            unsupported = set()
            self.assertIsNone(travel.rejection(chosen,121,domains,candidates,unsupported))
            self.assertTrue(all(k not in unsupported for k in range(len(partition))))

    def test_positive_local_minimum_has_no_descending_step(self):
        state = GridState(5)
        for i in (12, 7, 11, 13, 17):
            state.grid[i//5][i%5].starting_number = 5
        chosen = [((1 << 12) | (1 << 13), None)]
        self.assertEqual(TravelConstraints(state).rejection(chosen, 25), 'bellman')

    def test_shape_support_requires_a_possible_exit(self):
        from solver import shape_has_distance_support
        # A domino with fixed distance 5 at both cells, surrounded by
        # distances >= 5, has no downhill step even with uncertain areas.
        low = [5] * 25
        high = [20] * 25
        high[12] = high[13] = 5
        domino = ((1 << 12) | (1 << 13), None)
        self.assertFalse(shape_has_distance_support(domino, [1]*25, [25]*25,
                                                    low, high, 5))
        # A cheap external exit can support the same shape.
        low[7] = high[7] = 3
        low[8] = high[8] = 3
        self.assertTrue(shape_has_distance_support(domino, [2]*25, [25]*25,
                                                   low, high, 5))

    def test_complete_valid_small_partition_keeps_every_remaining_shape(self):
        from starting_grid import new_workspace
        # Independently validated small-board solution: includes both capitol
        # and capitol-free states, internal paths, and cheaper external exits.
        groups = [([0,5,10,11,16,17,18],11), ([1,2,6,7],None),
                  ([3,4,9,14,15,19,20,21,22,23,24],24), ([8,12,13],13)]
        partition = [(sum(1 << i for i in cells), cap) for cells,cap in groups]
        state = new_workspace(5).saved
        self.assertTrue(materialize(state, partition).validate_puzzle()['puzzle_valid'])
        candidates = partition + [(1 << i, i) for i in range(25)]
        for subset in range(16):
            chosen = [shape for k,shape in enumerate(partition) if subset & (1 << k)]
            occupied = sum(mask for mask,_ in chosen)
            domains = {i: [k for k,(mask,_) in enumerate(candidates)
                           if mask & (1 << i) and not mask & occupied]
                       for i in range(25) if not occupied & (1 << i)}
            unsupported = set()
            self.assertIsNone(TravelConstraints(state).rejection(
                chosen,25,domains,candidates,unsupported))
            self.assertFalse(unsupported & set(range(4)))

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
