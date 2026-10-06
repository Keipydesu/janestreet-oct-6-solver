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

    def test_larger_search_and_board_limit(self):
        state = new_workspace().saved
        result = state.candidate_states(0,2,121,time_limit=10,node_limit=30000,preview_limit=None)
        self.assertEqual(result['max_examined_area'],121)
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

if __name__=='__main__': unittest.main()
