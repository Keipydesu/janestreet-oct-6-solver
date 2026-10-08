import unittest
from unittest.mock import patch

from model import GridState
from state_counts import state_count_heatmap


class StateCountTests(unittest.TestCase):
    def test_exact_small_counts_deduplicate_across_roots(self):
        # Every square belongs to its singleton and two adjacent dominoes.
        report = state_count_heatmap(GridState(2), max_area=2, seconds=2)
        self.assertEqual(report['heatmap'], [[3,3],[3,3]])
        self.assertEqual(report['unique_states'], 8)
        self.assertTrue(report['complete_within_limit'])

    def test_timeout_is_sampled_zero_not_impossibility(self):
        report = state_count_heatmap(GridState(2), seconds=0)
        self.assertEqual(report['heatmap'], [[0,0],[0,0]])
        self.assertEqual(report['complete_cell_count'], 0)
        self.assertFalse(report['complete_within_limit'])

    def test_ignores_paint_and_manual_stars_without_mutation(self):
        state = GridState(2)
        state.grid[0][0].region_color = '#123456'
        state.grid[0][0].is_capital = True
        before = state.to_dict()
        report = state_count_heatmap(state,max_area=2,seconds=2)
        self.assertEqual(report['heatmap'], [[3,3],[3,3]])
        self.assertEqual(state.to_dict(),before)

    def test_counts_shapes_from_other_roots_without_claiming_completeness(self):
        def sample(state,row,col,**kwargs):
            return {'complete_within_limit':False, 'survivors':[
                {'cells':[[0,0],[0,1]], 'capitol':None}]}
        with patch('state_counts.search_candidates',side_effect=sample):
            report = state_count_heatmap(GridState(2),max_area=2,seconds=1)
        self.assertEqual(report['heatmap'],[[1,1],[0,0]])
        self.assertEqual(report['unique_states'],1)
        self.assertFalse(report['complete_within_limit'])

    def test_invalid_area_is_rejected(self):
        for area in (0,5,True,1.5):
            with self.assertRaises(ValueError):
                state_count_heatmap(GridState(2),max_area=area)

    def test_starting_clues_change_counts(self):
        state = GridState(2)
        state.grid[0][0].starting_number = 0
        report = state_count_heatmap(state,max_area=2,seconds=2)
        # The zero's only possible state of area <=2 is its singleton.
        self.assertEqual(report['heatmap'][0][0],1)
        self.assertTrue(report['complete_cells'][0][0])


if __name__ == '__main__':
    unittest.main()
