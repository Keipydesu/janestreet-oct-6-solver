import unittest
from model import GridState
from starting_grid import new_workspace

class CandidateTests(unittest.TestCase):
    def test_complete_small_enumeration_at_corner(self):
        r=GridState().candidate_states(0,0,3,time_limit=10)
        self.assertEqual(r['examined'],8)  # singleton, two dominoes, five triominoes
        self.assertEqual(r['survivor_count'],8)
        self.assertTrue(r['complete_within_limit'])
        self.assertFalse(r['exhaustive'])
        self.assertEqual(r['forced_cells'],[])
        self.assertEqual(r['conditional_common_cells'],[[0,0]])
        self.assertEqual(r['completed_through_area'],3)
        shapes={tuple(map(tuple,c['cells'])) for c in r['survivors']}
        self.assertEqual(len(shapes),8)

    def test_actual_forced_singleton_exhaustive(self):
        state=new_workspace().saved
        before=state.to_dict()
        r=state.candidate_states(5,10,9)
        self.assertTrue(r['exhaustive'])
        self.assertEqual(r['survivor_count'],1)
        self.assertEqual(r['forced_cells'],[[5,10]])
        self.assertEqual(r['survivors'][0]['capitol'],[5,10])
        self.assertEqual(state.to_dict(),before)

    def test_interrupted_search_never_claims_forced_membership(self):
        r=GridState().candidate_states(5,5,9,node_limit=2,time_limit=10)
        self.assertTrue(r['truncated'])
        self.assertFalse(r['exhaustive'])
        self.assertFalse(r['complete_within_limit'])
        self.assertEqual(r['forced_cells'],[])
        self.assertEqual(r['conditional_common_cells'],[])

    def test_actual_four_clue_has_explained_rejections(self):
        r=new_workspace().saved.candidate_states(0,2,5,time_limit=10)
        self.assertTrue(r['complete_within_limit'])
        self.assertGreater(r['survivor_count'],0)
        for c in r['survivors']:
            self.assertGreaterEqual(c['area'],4)
            self.assertIn([0,2],c['cells'])
            self.assertTrue(GridState.shape_symmetry(c['cells'])['symmetric'])
            self.assertNotEqual(c['capitol'],[0,2])
        self.assertIn('Cheaper neighboring route',r['rejections'])
        self.assertIn('Positive clue at capitol',r['rejections'])

    def test_rejected_small_shapes_can_grow_into_valid_large_shapes(self):
        state=GridState();state.grid[0][0].starting_number=4
        r=state.candidate_states(0,0,4,time_limit=10)
        # The area-one prefix is impossible, but its domino extensions may survive.
        self.assertTrue(any(c['area']==2 for c in r['survivors']))
        self.assertTrue(any(c['area']==4 for c in r['survivors']))

    def test_empty_bounded_search_is_not_global_impossibility(self):
        r=new_workspace().saved.candidate_states(10,8,3,time_limit=10)
        self.assertEqual(r['survivor_count'],0)
        self.assertTrue(r['complete_within_limit'])
        self.assertFalse(r['exhaustive'])
        self.assertIn('larger states remain possible',r['conclusion'])

    def test_paint_not_used_as_an_assumption(self):
        state=GridState()
        before=state.candidate_states(0,0,3,time_limit=10)
        for row in state.grid:
            for cell in row: cell.region_color='#abcdef';cell.is_capital=True
        after=state.candidate_states(0,0,3,time_limit=10)
        self.assertEqual(before['survivors'],after['survivors'])

class SymmetryGeneratorTests(unittest.TestCase):
    def test_matches_exhaustive_reference_search(self):
        for root in ((0,0),(5,5)):
            state=GridState()
            direct=state.candidate_states(*root,5,time_limit=10,node_limit=500000)
            reference=state.candidate_states(*root,5,time_limit=10,node_limit=500000,strategy='connected_growth')
            self.assertTrue(direct['complete_within_limit'])
            self.assertEqual(direct['survivor_count'],reference['survivor_count'])
            self.assertEqual(direct['heatmap'],reference['heatmap'])
            self.assertNotIn('Asymmetric',direct['rejections'])

    def test_clue_pruning_matches_exhaustive_connected_growth(self):
        # Independent enumeration grows ALL connected shapes, without the new
        # hereditary predicate. Compare full cell/capitol sets, not just counts.
        from candidate_search import search_candidates
        supplied = new_workspace().saved
        enclosed = GridState()
        enclosed.grid[0][0].starting_number = 2
        zeros = GridState()
        zeros.grid[0][0].starting_number = 0
        zeros.grid[0][2].starting_number = 0
        scenarios = [(supplied, (0,2)), (supplied, (2,5)),
                     (supplied, (4,10)), (enclosed, (0,0)), (zeros, (0,0))]
        reasons = set()
        for state, root in scenarios:
            with self.subTest(root=root, clues=state.to_dict()):
                args = dict(max_area=5, time_limit=20, node_limit=500000,
                            preview_limit=None)
                actual = search_candidates(state, *root, **args)
                expected = search_candidates(state, *root,
                                             strategy='connected_growth', **args)
                self.assertTrue(actual['complete_within_limit'])
                self.assertTrue(expected['complete_within_limit'])
                def signatures(result):
                    return {(tuple(map(tuple, candidate['cells'])),
                             tuple(candidate['capitol']) if candidate['capitol'] else None)
                            for candidate in result['survivors']}
                self.assertEqual(signatures(actual), signatures(expected))
                self.assertEqual(actual['heatmap'], expected['heatmap'])
                reasons.update(actual['branch_prunes'])
        self.assertTrue({'Forced singleton', 'Multiple zero clues',
                         'Clue 1 blocked', 'Enclosed positive clue'} <= reasons)

    def test_larger_search_and_board_limit(self):
        state = new_workspace().saved
        result = state.candidate_states(0,2,121,time_limit=10,node_limit=30000,preview_limit=None)
        self.assertLessEqual(result['max_examined_area'],121)
        self.assertGreater(sum(result['branch_prunes'].values()),0)
        self.assertGreater(result['max_survivor_area'],20)
        for candidate in result['survivors']:
            self.assertTrue(state.shape_symmetry(candidate['cells'])['symmetric'])
        with self.assertRaises(ValueError):
            state.candidate_states(0,2,122)

    def test_twenty_square_search_preserves_symmetry_and_connectivity(self):
        from symmetric_shapes import connected
        state=new_workspace().saved
        result=state.candidate_states(0,2,20,time_limit=10,node_limit=20000)
        self.assertEqual(result['strategy'],'symmetry_orbits')
        self.assertEqual(result['max_examined_area'],20)
        self.assertEqual(result['max_survivor_area'],20)
        self.assertNotIn('Asymmetric',result['rejections'])
        self.assertTrue(result['truncated'])
        self.assertEqual(result['forced_cells'],[])
        for candidate in result['survivors']:
            self.assertLessEqual(candidate['area'],20)
            self.assertTrue(state.shape_symmetry(candidate['cells'])['symmetric'])
            mask=sum(1<<(r*11+c) for r,c in candidate['cells'])
            self.assertTrue(connected(mask))
        self.assertEqual(result['frequency'][0][2],1.0)
        self.assertTrue(all(0<=v<=1 for row in result['frequency'] for v in row))

class PaintConstraintTests(unittest.TestCase):
    def test_includes_source_component_and_avoids_other_colors(self):
        state=GridState()
        state.grid[0][0].region_color='#aaaaaa'
        state.grid[0][1].region_color='#aaaaaa'
        state.grid[1][0].region_color='#bbbbbb'
        result=state.candidate_states(0,0,4,time_limit=10,respect_paint=True)
        self.assertTrue(result['complete_within_limit'])
        self.assertGreater(result['survivor_count'],0)
        for c in result['survivors']:
            self.assertIn([0,0],c['cells']);self.assertIn([0,1],c['cells'])
            self.assertNotIn([1,0],c['cells'])
        self.assertEqual(result['forced_cells'],[])
        self.assertIn([0,1],result['conditional_common_cells'])
        self.assertTrue(result['respect_paint'])

    def test_cannot_split_another_connected_component(self):
        state=GridState()
        for r,c in [(0,0),(0,2),(0,3)]: state.grid[r][c].region_color='#aaaaaa'
        result=state.candidate_states(0,0,4,time_limit=10,respect_paint=True)
        for c in result['survivors']:
            self.assertEqual([0,2] in c['cells'],[0,3] in c['cells'])

    def test_paint_needs_source_and_does_not_mutate(self):
        state=GridState()
        with self.assertRaises(ValueError): state.candidate_states(0,0,3,respect_paint=True)
        state.grid[0][0].region_color='#aaaaaa'
        before=state.to_dict()
        state.candidate_states(0,0,3,respect_paint=True)
        self.assertEqual(before,state.to_dict())

class ManualStarConstraintTests(unittest.TestCase):
    def test_stars_require_the_symmetry_capitol_with_and_without_paint(self):
        for paint in (False, True):
            for borders in (False, True):
                with self.subTest(paint=paint, borders=borders):
                    state = GridState(5)
                    state.grid[0][0].is_capital = True
                    state.grid[0][0].region_color = '#aaaaaa'
                    before = state.to_dict()
                    options = dict(time_limit=10, respect_paint=paint, check_borders=borders)
                    ignored = state.candidate_states(0, 0, 3, **options)
                    required = state.candidate_states(0, 0, 3, respect_stars=True, **options)
                    self.assertGreater(ignored['survivor_count'], required['survivor_count'])
                    self.assertGreater(required['survivor_count'], 0)
                    self.assertTrue(all(c['capitol'] == [0, 0] for c in required['survivors']))
                    self.assertTrue(required['conditional'])
                    self.assertEqual(required['forced_cells'], [])
                    self.assertEqual(state.to_dict(), before)

    def test_line_and_cross_have_no_capitol_even_at_center(self):
        shapes = [([(2, 1), (2, 2), (2, 3)], (2, 2)),
                  ([(1, 2), (2, 1), (2, 2), (2, 3), (3, 2)], (2, 2))]
        for cells, star in shapes:
            with self.subTest(cells=cells):
                state = GridState(5)
                for r, c in cells:
                    state.grid[r][c].region_color = '#aaaaaa'
                state.grid[star[0]][star[1]].is_capital = True
                options = dict(respect_paint=True, check_borders=True, time_limit=10)
                ignored = state.candidate_states(*star, len(cells), **options)
                required = state.candidate_states(*star, len(cells), respect_stars=True, **options)
                self.assertEqual(ignored['survivor_count'], 1)
                self.assertEqual(required['survivor_count'], 0)

    def test_outside_stars_constrain_routes_like_zero_clues(self):
        state = GridState(5)
        state.grid[0][1].is_capital = True
        state.grid[1][0].starting_number = 2
        starred = state.candidate_states(0, 0, 4, respect_stars=True, check_borders=True)
        state.grid[0][1].starting_number = 0
        zero = state.candidate_states(0, 0, 4, check_borders=True)
        self.assertEqual(starred['survivors'], zero['survivors'])
        self.assertEqual(starred['heatmap'], zero['heatmap'])

    def test_lopsided_paint_must_be_completed_around_its_marked_capitol(self):
        state = GridState(5)
        state.grid[0][0].is_capital = True
        for r, c in [(0, 0), (0, 1)]:
            state.grid[r][c].region_color = '#aaaaaa'
        result = state.candidate_states(0, 1, 3, respect_paint=True,
                                        respect_stars=True, check_borders=True)
        self.assertTrue(result['complete_within_limit'])
        self.assertEqual(result['survivor_count'], 1)
        candidate = result['survivors'][0]
        self.assertEqual(set(map(tuple, candidate['cells'])), {(0, 0), (0, 1), (1, 0)})
        self.assertEqual(candidate['capitol'], [0, 0])
        # Reflection in the diagonal uniquely fixes the elbow. A capitol
        # does not require rotational symmetry or the bounding-box center.
        self.assertEqual(candidate['rotations'], [])
        self.assertEqual(candidate['reflections'], ['main_diagonal'])

    def test_starred_painted_search_matches_unpruned_enumeration(self):
        state = GridState(5)
        state.grid[2][2].is_capital = True
        for r, c in [(2, 2), (2, 3)]:
            state.grid[r][c].region_color = '#aaaaaa'
        state.grid[0][0].region_color = '#bbbbbb'
        options = dict(max_area=5, respect_paint=True, respect_stars=True,
                       check_borders=True, time_limit=20, preview_limit=None)
        actual = state.candidate_states(2, 3, **options)
        reference = state.candidate_states(2, 3, strategy='connected_growth', **options)
        self.assertTrue(actual['complete_within_limit'])
        self.assertTrue(reference['complete_within_limit'])
        self.assertEqual(actual['heatmap'], reference['heatmap'])
        self.assertGreater(actual['survivor_count'], 0)
        for candidate in actual['survivors']:
            self.assertEqual(candidate['capitol'], [2, 2])
            for operation in state.shape_symmetry(candidate['cells'])['operations']:
                self.assertEqual(operation['fixed_cells'], [[2, 2]])

    def test_conflicting_clue_and_invalid_option(self):
        state = GridState(5)
        state.grid[0][0].is_capital = True
        state.grid[0][0].starting_number = 2
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            state.candidate_states(0, 0, 3, respect_stars=True)
        with self.assertRaisesRegex(ValueError, 'true or false'):
            state.candidate_states(0, 0, 3, respect_stars='yes')

if __name__=='__main__': unittest.main()
