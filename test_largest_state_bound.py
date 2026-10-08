"""Check that bound relaxations never remove a real symmetric state."""
import unittest
from model import GridState
from largest_state_bound import geometric_upper_bounds, add_large_state_symmetry, bound_largest_state

try:
    from ortools.sat.python import cp_model
except ImportError:
    cp_model = None


@unittest.skipUnless(cp_model, 'Optional OR-Tools is not installed')
class LargestStateBoundTests(unittest.TestCase):
    def test_all_connected_symmetric_majorities_survive(self):
        # Exhaust every subset of a 3x3 board. Each valid majority shape,
        # with singleton states outside it, must survive our symmetry model.
        for mask in range(1,1<<9):
            count = mask.bit_count()
            if count <= 4:
                continue
            cells = [divmod(i,3) for i in range(9) if mask & (1<<i)]
            pending = set(cells); reached = {pending.pop()}
            while True:
                more = {p for p in pending if any(abs(p[0]-q[0])+abs(p[1]-q[1])==1 for q in reached)}
                if not more:
                    break
                reached |= more; pending -= more
            if pending:
                continue
            symmetry = GridState.shape_symmetry(cells)
            if not symmetry['symmetric']:
                continue
            ops = symmetry['operations']
            cap = None
            if all(op['fixed_count']==1 for op in ops):
                fixed = ops[0]['fixed_cells'][0]
                if all(op['fixed_cells'][0]==fixed for op in ops):
                    cap = fixed[0]*3+fixed[1]
            model = cp_model.CpModel()
            area = [model.new_int_var(1,9,f'a{i}') for i in range(9)]
            caps = [model.new_bool_var(f'c{i}') for i in range(9)]
            largest = model.new_int_var(count,count,'largest')
            add_large_state_symmetry(model,area,caps,largest,size=3)
            for i in range(9):
                inside = bool(mask & (1<<i))
                model.add(area[i] == (count if inside else 1))
                model.add(caps[i] == (i==cap if inside else True))
            solver = cp_model.CpSolver(); solver.parameters.num_search_workers=1
            self.assertEqual(solver.solve(model),cp_model.OPTIMAL, cells)

    def test_escape_bound_preserves_known_completion(self):
        # A five-square corner with diagonal symmetry and a corner capitol.
        completed = GridState(3)
        cells = {(0,0),(0,1),(0,2),(1,0),(2,0)}
        for r,row in enumerate(completed.grid):
            for c,cell in enumerate(row):
                cell.region_color = '#123456' if (r,c) in cells else '#%06x'%(1+r*3+c)
        clues = completed.smart_heatmap(use_derived_capitals=True)['heatmap']
        state = GridState(3)
        for r in range(3):
            for c in range(3):
                state.grid[r][c].starting_number = clues[r][c]
        bound,records = geometric_upper_bounds(state,seconds=5)
        self.assertGreaterEqual(bound,5)
        self.assertLess(bound,9)
        self.assertTrue(records)

    def test_zero_budget_claims_no_reduction(self):
        report = bound_largest_state(GridState(),seconds=0)
        self.assertEqual(report['proven_upper_bound'],121)
        self.assertEqual(report['excluded_areas'],[])
        self.assertIsNone(report['verified_witness'])

    def test_geometric_timeout_keeps_conservative_capacity(self):
        bound,records = geometric_upper_bounds(GridState(3),seconds=0)
        self.assertEqual(bound,9)
        self.assertTrue(all(r['status']=='overlap_capacity' for r in records))

    def test_rejects_wrong_board_and_invalid_budgets(self):
        with self.assertRaises(ValueError):
            bound_largest_state(GridState(5),seconds=0)
        for seconds in (-1,float('inf'),float('nan')):
            with self.assertRaises(ValueError):
                bound_largest_state(GridState(),seconds=seconds)


if __name__=='__main__':
    unittest.main()
