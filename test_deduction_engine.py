import random
import unittest

from candidate_search import NEIGHBORS
from deduction_engine import Contradiction, DeductionEngine, deduce
from model import GridState
from solver import N, materialize
from starting_grid import new_workspace


class DeductionTests(unittest.TestCase):
    def test_capitol_domain_is_odd_but_not_forced_singleton(self):
        state=GridState();state.grid[5][5].starting_number=0
        report=deduce(state)
        self.assertEqual(report['status'],'deduction_fixed_point')
        domain=report['area_domains'][5][5]
        self.assertIn(1,domain);self.assertIn(3,domain)
        self.assertTrue(all(s%2 for s in domain))

    def test_bellman_support_rejects_an_impossible_first_step(self):
        engine=DeductionEngine(GridState())
        engine.domains[0]={2,5};engine.lower[0]=engine.upper[0]=2
        for j in (1,11):
            engine.domains[j]={3};engine.lower[j]=engine.upper[j]=0
        engine.propagate_area_support()
        self.assertEqual(engine.domains[0],{2})
        self.assertTrue(any(s['rule']=='bellman_area_support' and s['cell']==[1,1]
                            for s in engine.steps))

    def test_support_helper_matches_direct_edge_cost_definition(self):
        rng=random.Random(7)
        for _ in range(500):
            size=rng.randrange(1,122)
            domain=set(rng.sample(range(1,122),rng.randrange(1,20)))
            low,high=sorted((rng.randrange(-10,125),rng.randrange(-10,125)))
            self.assertEqual(DeductionEngine.weight_supported(size,domain,low,high),
                             any(low<=min(size,other)<=high for other in domain))

    def test_preserves_known_partitions_and_exact_distances(self):
        # Both adjacent equal-area regions and a mixture of capitol-bearing
        # and capitol-free states are covered by these independently validated
        # concrete solutions; propagation must never remove their true values.
        rows=[(sum(1<<(r*11+c) for c in range(11)),None) for r in range(10)]
        rows += [(1<<i,i) for i in range(110,121)]
        mixed=[(sum(1<<i for i in (0,1,11)),0),
               (sum(1<<i for i in (2,3,4)),None),((1<<20)|(1<<21),None)]
        occupied=sum(mask for mask,cap in mixed)
        mixed += [(1<<i,i) for i in range(N) if not occupied & (1<<i)]
        rng=random.Random(18)
        for chosen in (rows,mixed):
            complete=materialize(GridState(),chosen)
            self.assertTrue(complete.validate_puzzle()['puzzle_valid'])
            actual=complete.smart_heatmap(use_derived_capitals=True)['heatmap']
            areas={i:mask.bit_count() for mask,cap in chosen for i in range(N) if mask&(1<<i)}
            for density in (0.2,0.6,1.0):
                state=GridState()
                for i in range(N):
                    if rng.random()<density:
                        state.grid[i//11][i%11].starting_number=actual[i//11][i%11]
                # Ensure finite-distance problem scope even if sampling changes.
                state.grid[10][10].starting_number=actual[10][10]
                report=deduce(state)
                self.assertEqual(report['status'],'deduction_fixed_point',report['contradiction'])
                for i in range(N):
                    r,c=divmod(i,11)
                    self.assertIn(areas[i],report['area_domains'][r][c])
                    low,high=report['distance_intervals'][r][c]
                    self.assertLessEqual(low,actual[r][c]);self.assertGreaterEqual(high,actual[r][c])

    def test_real_clues_have_reasoned_additional_deductions(self):
        state=new_workspace().saved;before=state.to_dict()
        report=deduce(state)
        self.assertEqual(state.to_dict(),before)
        self.assertEqual(report['status'],'deduction_fixed_point')
        self.assertGreater(report['additional_area_options_removed'],0)
        self.assertTrue(all(s['reason'] for s in report['steps']))
        self.assertEqual([s['step'] for s in report['steps']],list(range(1,len(report['steps'])+1)))
        self.assertIn({'cell':[6,11],'area':1},report['forced_areas'])
        self.assertIn('not a solved partition',report['scope'])

    def test_potential_component_smaller_than_area_removes_it(self):
        # Three mutually-adjacent cells (0,1,11) still admit area 4; isolate
        # them from every other area-4-admitting cell so the potential
        # component has only 3 members. 4 cells are needed, connected, so
        # area 4 must be removed from all three -- without this being a
        # forced-singleton domain, so it is not a contradiction.
        engine = DeductionEngine(GridState())
        for i in range(N):
            engine.domains[i].discard(4)
        for i in (0, 1, 11):
            engine.domains[i].add(4)
        engine.propagate_inventory()
        for i in (0, 1, 11):
            self.assertNotIn(4, engine.domains[i])
        self.assertTrue(any(s['rule'] == 'inventory_component_capacity' and s['cell'] == [1, 1]
                            for s in engine.steps))

    def test_non_multiple_potential_component_is_not_a_contradiction(self):
        # Five cells (not a multiple of 2) still admit area 2 alongside
        # other values -- not yet forced to exactly {2} -- so this must
        # NOT raise, unlike the forced case below.
        engine = DeductionEngine(GridState())
        five = (0, 1, 2, 11, 12)
        for i in range(N):
            engine.domains[i].discard(2)
        for i in five:
            engine.domains[i].add(2)
        engine.propagate_inventory()
        for i in five:
            self.assertIn(2, engine.domains[i])

    def test_forced_non_multiple_component_is_a_contradiction(self):
        # Same five cells, but now EVERY one of them is forced to exactly
        # {2}: that region is certainly realized at area 2, and 5 cells
        # cannot be covered by whole area-2 states.
        engine = DeductionEngine(GridState())
        five = (0, 1, 2, 11, 12)
        for i in range(N):
            engine.domains[i] = {1}
        for i in five:
            engine.domains[i] = {2}
        with self.assertRaises(Contradiction):
            engine.propagate_inventory()
        self.assertEqual(engine.contradiction['area'], 2)

    def test_inventory_forces_optional_cells_when_range_collapses_to_the_maximum(self):
        # Six cells admit area 3; four are already forced to {3}. The only
        # multiple of 3 in [4,6] is 6, so the two optional cells must also
        # become area 3 -- not just "may remain area 3".
        engine = DeductionEngine(GridState())
        for i in range(N):
            engine.domains[i].discard(3)
        six = (0, 1, 2, 11, 12, 13)
        for i in six:
            engine.domains[i].add(3)
        for i in (0, 1, 11, 12):
            engine.domains[i] = {3}
        engine.propagate_inventory()
        for i in six:
            self.assertEqual(engine.domains[i], {3})

    def test_inventory_removes_optional_cells_when_range_collapses_to_the_minimum(self):
        # Five cells admit area 3; three are forced to {3} (not all five).
        # The only multiple of 3 in [3,5] is 3 itself, so the region can't
        # host any more area-3 cells than the 3 already forced: the two
        # optional cells must be removed from area 3, not forced into it
        # (contrast with the "collapses to the maximum" case above, and
        # this is NOT a contradiction -- it's a sound removal).
        engine = DeductionEngine(GridState())
        for i in range(N):
            engine.domains[i].discard(3)
        five = (0, 1, 2, 11, 12)
        for i in five:
            engine.domains[i].add(3)
        for i in (0, 1, 2):
            engine.domains[i] = {3}
        engine.propagate_inventory()
        self.assertEqual(engine.domains[0], {3})
        for i in (11, 12):
            self.assertNotIn(3, engine.domains[i])

    def test_inventory_partial_force_can_already_contradict_divisibility(self):
        engine=DeductionEngine(GridState())
        for domain in engine.domains:
            domain.discard(3)
        for i in (0,1,2,11,12):
            engine.domains[i].add(3)
        for i in (0,1,2,11):
            engine.domains[i]={3}
        with self.assertRaises(Contradiction):
            engine.propagate_inventory()
        self.assertEqual(engine.contradiction['area'],3)
        self.assertEqual(engine.contradiction['forced'],4)
        self.assertEqual(engine.contradiction['possible'],5)

    def test_two_step_bound_names_the_short_route_reason(self):
        # R3C3=7 and R4C4=51 are both adjacent to R3C4 and to R4C3, so each
        # is the middle of a 2-edge route between the two clues: any route
        # uses two edges each costing at most the middle's own area, so
        # 2*A(middle) >= |51-7| = 44, giving A(middle) >= 22.
        engine = DeductionEngine(new_workspace().saved)
        engine.seed()
        engine.propagate_distances()
        engine.propagate_two_step_area_bound()
        r3c3, r4c4 = 2*11+2, 3*11+3
        for middle in (2*11+3, 3*11+2):  # R3C4, R4C3 (zero-based)
            self.assertGreaterEqual(min(engine.domains[middle]), 22)
            self.assertTrue(any(s['rule'] == 'two_step_area_bound'
                                and s['cell'] == [middle//11+1, middle%11+1]
                                for s in engine.steps))

    def test_guaranteed_capitol_count_on_real_clues_matches_hand_count(self):
        # Two zero clues, the forced singleton at R6C11, and one more
        # required singleton capitol from one selected group near R3C6.
        # The R4C7 group overlaps it, so must not be counted separately.
        engine = DeductionEngine(new_workspace().saved)
        engine.seed()
        engine.propagate_distances()
        k, certain, groups = engine.guaranteed_distinct_capitol_count()
        self.assertGreaterEqual(k, 4)
        self.assertEqual(len(certain), 3)  # two zero clues + forced singleton
        self.assertEqual(k,len(certain)+len(groups))
        self.assertEqual(len(groups),1)
        used=set(certain)
        for group in groups:
            self.assertFalse(used & group)
            used.update(group)

    def test_global_capitol_count_bounds_large_areas(self):
        # Four cells forced to be distinct certain capitols (upper=0) means
        # K=4, so no state may have odd area > 121-4+1=118 or even area >
        # 121-4=117; areas above those limits must be removed everywhere.
        engine = DeductionEngine(GridState())
        for i in (0, 1, 2, 3):
            engine.upper[i] = 0
        engine.propagate_global_capitol_count()
        self.assertFalse(any(s > 118 for s in engine.domains[50]))
        self.assertNotIn(120, engine.domains[50])  # even, > 117
        self.assertNotIn(118, engine.domains[50])
        self.assertEqual(max(engine.domains[50]),117)
        self.assertEqual(max(s for s in engine.domains[50] if s%2==0),116)

    def test_global_capitol_count_skips_groups_touching_a_certain_capitol(self):
        # A clue-1's neighbor group containing an already-certain capitol
        # must not be credited as an ADDITIONAL distinct requirement.
        engine = DeductionEngine(GridState())
        engine.clues = {5: 1}
        engine.upper[NEIGHBORS[5][0]] = 0  # one neighbor is already certain
        k, certain, groups = engine.guaranteed_distinct_capitol_count()
        self.assertEqual(k, len(certain))
        self.assertEqual(groups, [])

    def test_real_clues_inventory_rule_strengthens_the_fixed_point(self):
        # The inventory component rule should find real, additional
        # eliminations on the supplied puzzle beyond the distance/support
        # rules alone, without ever producing a contradiction.
        report = deduce(new_workspace().saved)
        self.assertEqual(report['status'], 'deduction_fixed_point')
        self.assertGreater(report['rule_counts'].get('inventory_component_capacity', 0), 0)

    def test_fixed_point_is_stable(self):
        engine=DeductionEngine(new_workspace().saved)
        engine.run()
        revision=engine.revision
        engine.propagate_distances();engine.propagate_two_step_area_bound()
        engine.propagate_area_support();engine.propagate_inventory()
        engine.propagate_global_capitol_count()
        self.assertEqual(engine.revision,revision)


if __name__=='__main__':unittest.main()
