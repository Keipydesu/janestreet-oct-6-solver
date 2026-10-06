import time
import unittest
from unittest.mock import patch

from model import GridState
from solver import N, materialize
from area_solver import components, partition_component, GeometryTimeout, solve_area, build_area_model

try:
    from ortools.sat.python import cp_model
except ImportError:
    cp_model = None


def mask(*cells):
    return sum(1 << i for i in cells)


class GeometryTests(unittest.TestCase):
    def test_glued_equal_size_states_are_partitioned(self):
        # A 2x2 connected area-2 component contains two distinct dominoes.
        cells = mask(0,1,11,12)
        result = partition_component(cells,2,set())
        self.assertIsNotNone(result)
        self.assertEqual(len(result),2)
        self.assertEqual(sum(s for s,c in result),cells)
        self.assertTrue(all(s.bit_count()==2 and c is None for s,c in result))

    def test_disconnected_equal_size_components_cannot_share_a_state(self):
        self.assertIsNone(partition_component(mask(0,2),2,set()))
        self.assertEqual(len(list(components(mask(0,2)))),2)

    def test_whole_component_must_match_geometric_capitol(self):
        cells=mask(0,1,11)  # L triomino: reflection fixes the corner only.
        self.assertEqual(partition_component(cells,3,{0}),[(cells,0)])
        self.assertIsNone(partition_component(cells,3,set()))
        self.assertIsNone(partition_component(cells,3,{1}))
        self.assertIsNone(partition_component(mask(0,1,2),3,{1}))
        self.assertEqual(partition_component(mask(0,1,2),3,set()),[(mask(0,1,2),None)])

    def test_timeout_is_distinct_from_infeasibility(self):
        with self.assertRaises(GeometryTimeout):
            partition_component(mask(0,1),2,set(),deadline=time.monotonic()-1)

    def test_component_partition_matches_independent_subset_reference(self):
        from itertools import combinations
        from area_solver import shape_capitol
        # Reference enumerates every subset, independently of frontier growth.
        cells=[0,1,2,11,12,13]
        whole=mask(*cells)
        def reference(remaining,size,caps):
            if not remaining:
                return True
            root=(remaining & -remaining).bit_length()-1
            rest=[i for i in cells if remaining & (1<<i) and i!=root]
            for extra in combinations(rest,size-1):
                part=mask(root,*extra)
                if len(list(components(part)))!=1:
                    continue
                valid,cap=shape_capitol(part)
                if not valid or {i for i in caps if part & (1<<i)} != ({cap} if cap is not None else set()):
                    continue
                if reference(remaining^part,size,caps):
                    return True
            return False
        for size in (2,3):
            for cap_bits in range(1 << len(cells)):
                caps={i for n,i in enumerate(cells) if cap_bits & (1<<n)}
                self.assertEqual(partition_component(whole,size,caps) is not None,
                                 reference(whole,size,caps),(size,caps))


@unittest.skipUnless(cp_model, 'Optional OR-Tools dependency is not installed')
class AreaSolverTests(unittest.TestCase):
    def test_singletons_are_independently_verified(self):
        result=solve_area(GridState(),seconds=10,max_area=1)
        self.assertEqual(result['status'],'verified_solution')
        self.assertTrue(GridState.from_dict(result['solution']).validate_puzzle()['puzzle_valid'])

    def test_known_valid_partition_satisfies_exact_distance_model(self):
        # Adjacent equal-size states: ten area-11 rows and 11 singleton capitols.
        chosen=[(sum(1<<(r*11+c) for c in range(11)),None) for r in range(10)]
        chosen += [(1<<i,i) for i in range(110,121)]
        complete=materialize(GridState(),chosen)
        actual=complete.smart_heatmap(use_derived_capitals=True)['heatmap']
        state=GridState()
        for i in range(0,N,3):
            state.grid[i//11][i%11].starting_number=actual[i//11][i%11]
        model,areas,distances,caps,_=build_area_model(state,max_area=11)
        for i in range(N):
            model.add(areas[i] == (11 if i<110 else 1))
            model.add(caps[i] == (i>=110))
        solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=5
        self.assertIn(solver.solve(model),(cp_model.OPTIMAL,cp_model.FEASIBLE))
        self.assertEqual([solver.value(d) for d in distances], [v for row in actual for v in row])
        model.add(distances[0] != actual[0][0])
        self.assertEqual(solver.solve(model),cp_model.INFEASIBLE)

    def test_area_inventory_excludes_unpartitionable_counts(self):
        model,areas,_,_,_=build_area_model(GridState(),max_area=2)
        # Three area-2 cells violate count(area=2) being a multiple of two.
        for i,a in enumerate(areas):model.add(a==(2 if i<3 else 1))
        solver=cp_model.CpSolver()
        self.assertEqual(solver.solve(model),cp_model.INFEASIBLE)

    def test_geometry_timeout_never_returns_infeasible_or_solution(self):
        with patch('area_solver.partition_component',side_effect=GeometryTimeout):
            report=solve_area(GridState(),seconds=10,max_area=1)
        self.assertEqual(report['status'],'time_limit')
        self.assertIsNone(report['solution'])
        self.assertEqual(report['statistics'].get('geometry_cuts',0),0)

    def test_invalid_geometry_learns_cut_and_resolves(self):
        # This asymmetric tetromino satisfies the numeric relaxation with
        # singleton capitols elsewhere. Only geometry can reject it.
        def fixed_model(state,max_area):
            model,areas,distances,caps,flags=build_area_model(state,max_area)
            for i,a in enumerate(areas):
                model.add(a == (4 if i in (0,1,2,11) else 1))
            return model,areas,distances,caps,flags
        with patch('area_solver.build_area_model',side_effect=fixed_model):
            report=solve_area(GridState(),seconds=10,max_area=4)
        self.assertEqual(report['status'],'infeasible_within_area_limit')
        self.assertEqual(report['statistics']['cp_calls'],2)
        self.assertGreaterEqual(report['statistics']['geometry_cuts'],1)

    def test_component_cut_allows_boundary_and_capitol_changes(self):
        from area_solver import add_component_cut
        # A straight triomino has no capitol. The rejected labeling marked 0.
        component=mask(0,1,2)
        for change,expected in [('none',False),('cap',True),('inside',True),
                                ('boundary',True),('unrelated',False)]:
            with self.subTest(change=change):
                model=cp_model.CpModel()
                flags=[{3:model.new_bool_var(f'a{i}')} for i in range(N)]
                caps=[model.new_bool_var(f'c{i}') for i in range(N)]
                add_component_cut(model,flags,caps,component,3,{0})
                for i in range(N):
                    value=i in (0,1,2)
                    if (change=='inside' and i==1) or (change=='boundary' and i==3) or (change=='unrelated' and i==120):
                        value=not value
                    model.add(flags[i][3] == value)
                    model.add(caps[i] == (i==0 and change!='cap'))
                solver=cp_model.CpSolver()
                feasible=solver.solve(model) in (cp_model.OPTIMAL,cp_model.FEASIBLE)
                self.assertEqual(feasible,expected)

    def test_small_templates_accept_legal_triomino_orientations(self):
        # {0,1,11} is an L-triomino (capitol at the corner, cell 0); {0,1,2}
        # is a straight triomino (no capitol, per the puzzle's own example).
        # Both must be satisfiable with singleton states filling the rest.
        # Cells outside the triomino are left unconstrained: they're forced
        # area 1, and area-1 already implies capitol on its own, so asserting
        # cap==False there would contradict that unrelated rule instead of
        # testing the template encoding.
        for cells, capitol in ((frozenset((0, 1, 11)), 0), (frozenset((0, 1, 2)), None)):
            with self.subTest(cells=cells):
                model, area, _, cap, _ = build_area_model(GridState(), max_area=3)
                for i in range(N):
                    model.add(area[i] == (3 if i in cells else 1))
                for i in cells:
                    model.add(cap[i] == (i == capitol))
                solver = cp_model.CpSolver()
                self.assertIn(solver.solve(model), (cp_model.OPTIMAL, cp_model.FEASIBLE))

    def test_small_templates_reject_disconnected_triple(self):
        # Every CONNECTED triomino is symmetric (there are only two shapes,
        # straight and bent, both of which pass), so there's no asymmetric
        # connected case to reject. {0,1,13} is disconnected instead: no
        # template mask matches this exact set of three cells, so no
        # selected placement can cover them.
        model, area, _, cap, _ = build_area_model(GridState(), max_area=3)
        cells = frozenset((0, 1, 13))
        for i in range(N):
            model.add(area[i] == (3 if i in cells else 1))
        for i in cells:
            model.add(cap[i] == False)
        solver = cp_model.CpSolver()
        self.assertEqual(solver.solve(model), cp_model.INFEASIBLE)

    def test_small_templates_reject_wrong_capitol(self):
        # Same L-triomino, but marking the wrong cell as capitol.
        model, area, _, cap, _ = build_area_model(GridState(), max_area=3)
        cells = frozenset((0, 1, 11))
        for i in range(N):
            model.add(area[i] == (3 if i in cells else 1))
        for i in cells:
            model.add(cap[i] == (i == 1))
        solver = cp_model.CpSolver()
        self.assertEqual(solver.solve(model), cp_model.INFEASIBLE)

    def test_odd_only_capitol_bound_rejects_excess_capitols(self):
        # One area-5 (odd) blob and one area-4 (even) blob; everything else
        # is one big area-112 (even) blob, so NEITHER non-area-5 bucket can
        # legally hold a capitol. Marking two cells of the area-5 blob as
        # capitols makes sum(cap)=2. The OLD bound (sum(cap) <= sum of ALL
        # state_counts, 1+1+1=3) would have accepted this; the per-cell
        # parity implications alone don't block it either, since both
        # flagged cells sit on odd-area cells. Only the odd-only aggregate
        # bound (sum(cap) <= odd state_counts only = 1) correctly rejects it.
        max_area = 112
        model, area, _, cap, _ = build_area_model(GridState(), max_area=max_area)
        five = frozenset(range(5))
        four = frozenset((5, 6, 16, 17))
        for i in range(N):
            if i in five:
                model.add(area[i] == 5)
            elif i in four:
                model.add(area[i] == 4)
            else:
                model.add(area[i] == max_area)
        model.add(cap[0] == True)
        model.add(cap[1] == True)
        solver = cp_model.CpSolver()
        self.assertEqual(solver.solve(model), cp_model.INFEASIBLE)

    def test_infeasibility_is_labeled_with_area_limit(self):
        state=GridState();state.grid[0][0].starting_number=1
        report=solve_area(state,seconds=10,max_area=1)
        self.assertEqual(report['status'],'infeasible_within_area_limit')
        self.assertIsNone(report['solution'])

    def test_propagated_contradiction_becomes_model_infeasibility(self):
        # The adjacent 0/121 clues require an area-121 state, but a second
        # distinct capitol cannot fit outside it. Initial scalar bounds alone
        # allow121; the domain/capitol-count propagation proves contradiction.
        state=GridState()
        state.grid[0][0].starting_number=0
        state.grid[0][1].starting_number=121
        state.grid[10][10].starting_number=0
        self.assertFalse(state.deductions()['contradictions'])
        report=solve_area(state,seconds=10)
        self.assertEqual(report['status'],'infeasible_within_area_limit')
        self.assertIsNone(report['solution'])

    def test_zero_time_does_not_claim_infeasibility(self):
        self.assertEqual(solve_area(GridState(),seconds=0)['status'],'time_limit')


if __name__=='__main__':unittest.main()
