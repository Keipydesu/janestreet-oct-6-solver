"""Sound area-domain propagation with an explanation trace; no branching.

Run: python3 deduction_engine.py --output solver-deduction-report.json
A fixed point is not a solved partition, and surviving values are not all
necessarily realizable. Rules preserve every finite-distance puzzle solution.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from candidate_search import NEIGHBORS
from model import SIZE
from solver import N, distance_envelope, distances
from starting_grid import new_workspace


class Contradiction(Exception):
    pass


class DeductionEngine:
    def __init__(self, state):
        self.state = state
        self.clues = {r*SIZE+c: cell.starting_number for r, row in enumerate(state.grid)
                      for c, cell in enumerate(row) if cell.starting_number is not None}
        self.domains = [set(range(1,N+1)) for _ in range(N)]
        self.lower = [0]*N
        self.upper = [(N-1)*N]*N
        self.steps = []
        self.revision = 0
        self.contradiction = None

    def fail(self, reason, **details):
        self.contradiction = {'reason':reason, **details}
        raise Contradiction(reason)

    def restrict(self, cell, allowed, rule, reason, **premises):
        before = self.domains[cell]
        after = before & set(allowed)
        removed = sorted(before - after)
        if not removed:
            return False
        self.steps.append({'step':len(self.steps)+1, 'rule':rule,
                           'cell':[cell//SIZE+1,cell%SIZE+1],
                           'removed_areas':removed, 'remaining_count':len(after),
                           'reason':reason, 'premises':premises})
        self.domains[cell] = after
        self.revision += 1
        if not after:
            self.fail('No possible state area remains.', cell=[cell//SIZE+1,cell%SIZE+1], rule=rule)
        return True

    def bound_distance(self, cell, lower, upper, rule, reason):
        before = [self.lower[cell],self.upper[cell]]
        after = [max(before[0],int(lower)), min(before[1],int(upper))]
        if before == after:
            return False
        self.steps.append({'step':len(self.steps)+1, 'rule':rule,
                           'cell':[cell//SIZE+1,cell%SIZE+1],
                           'distance_before':before, 'distance_after':after,
                           'reason':reason})
        self.lower[cell],self.upper[cell] = after
        self.revision += 1
        if after[0] > after[1]:
            self.fail('Distance lower bound exceeds upper bound.',
                      cell=[cell//SIZE+1,cell%SIZE+1], bounds=after, rule=rule)
        return True

    def seed(self):
        facts = self.state.deductions()
        if not facts['available'] or facts['contradictions']:
            self.fail('Invalid or contradictory starting clues.', details=facts['contradictions'])
        for i,n in self.clues.items():
            self.bound_distance(i,n,n,'given_clue','The printed clue is the exact nearest-capitol distance.')
        for i in range(N):
            minimum = facts['minimum_state_sizes'][i//SIZE][i%SIZE]
            self.restrict(i,range(minimum,N+1),'initial_area_bound',
                          'Existing clue-only deductions give this minimum area.',
                          minimum=minimum, deductions=facts['notes'][i//SIZE][i%SIZE])
            if self.clues.get(i) == 0:
                self.restrict(i,range(1,N+1,2),'capitol_parity',
                              'A zero clue is a capitol; a capitol-bearing state has odd area.')
            high_neighbors = [j for j in NEIGHBORS[i] if self.clues.get(j,0)>1]
            if high_neighbors:
                self.restrict(i,range(2,N+1),'singleton_exclusion',
                              'A singleton here would give an adjacent clue a route costing 1.',
                              adjacent_clues=[{'cell':[j//SIZE+1,j%SIZE+1], 'value':self.clues[j]}
                                               for j in high_neighbors])
        for r,c in facts['forced_singletons']:
            self.restrict(r*SIZE+c,{1},'forced_singleton',
                          'A clue 1 has only this possible adjacent singleton capitol.',
                          deductions=facts['notes'][r][c])

    def propagate_distances(self):
        for i,domain in enumerate(self.domains):
            if domain == {1}:
                self.bound_distance(i,0,0,'singleton_distance','A singleton is its own capitol.')
        high_areas = [max(domain) for domain in self.domains]
        upper = distance_envelope(high_areas,dict(enumerate(self.upper)))
        negative_lower = distance_envelope(high_areas,{i:-v for i,v in enumerate(self.lower)})
        for i in range(N):
            self.bound_distance(i,-negative_lower[i],upper[i],'distance_lipschitz',
                                'Propagate distance inequalities along weighted paths using maximum possible edge costs.')
        possible_caps = {i for i in range(N) if self.lower[i] == 0
                         and any(s % 2 for s in self.domains[i])}
        if not possible_caps:
            self.fail('No possible capitol remains for finite clue distances.')
        optimistic = distances([min(domain) for domain in self.domains], possible_caps)
        for i in range(N):
            self.bound_distance(i,optimistic[i],self.upper[i],'optimistic_capitol_distance',
                                'Even the cheapest possible edges to all still-possible capitols cost at least this much.')

    def propagate_two_step_area_bound(self):
        """Name the short two-edge-route reason before the generic Bellman
        support rule would derive the same bound less legibly.

        For distinct neighbors u, v of a middle cell m: any route from u to
        v through m uses the two edges u-m and m-v, each at most A(m) (an
        edge's cost is the min of its two endpoints' areas, which is never
        more than either one). So distance(u)-distance(v) <= 2*A(m), giving
        A(m) >= ceil((lower[u]-upper[v])/2). This holds regardless of
        whether u, v, m are in the same or different states. It's a special
        case of propagate_area_support's general reasoning, kept as its own
        rule only so the trace can show the short arithmetic reason -- the
        generic rule would reach the same fixed point either way.
        """
        for m in range(N):
            neighbors = NEIGHBORS[m]
            if len(neighbors) < 2:
                continue
            best = 1
            best_pair = None
            for u in neighbors:
                for v in neighbors:
                    if u == v:
                        continue
                    bound = -(-(self.lower[u]-self.upper[v]) // 2)  # ceil division
                    if bound > best:
                        best, best_pair = bound, (u, v)
            if best_pair is None:
                continue
            u, v = best_pair
            self.restrict(m,[s for s in self.domains[m] if s >= best],'two_step_area_bound',
                          f'The two-edge route from R{u//SIZE+1}C{u%SIZE+1} to R{v//SIZE+1}C{v%SIZE+1} through '
                          f'here uses two edges each costing at most this cell\'s area, so twice that '
                          f'area is at least their distance difference.',
                          via=[m//SIZE+1,m%SIZE+1], minimum_area=best,
                          u={'cell':[u//SIZE+1,u%SIZE+1],'lower_distance':self.lower[u]},
                          v={'cell':[v//SIZE+1,v%SIZE+1],'upper_distance':self.upper[v]})

    @staticmethod
    def weight_supported(area, neighbor_domain, low, high):
        """Does some neighbor area make min(area, neighbor_area) fall in [low,high]?"""
        low = max(1,low)
        if high < low or area < low:
            return False
        if area <= high and max(neighbor_domain) >= area:
            return True
        return any(low <= other <= high and other < area for other in neighbor_domain)

    def propagate_area_support(self):
        for i in range(N):
            allowed = set()
            for size in self.domains[i]:
                # If A(i)=size, each incident edge is at most this bound.
                edge_max = {j:min(size,max(self.domains[j])) for j in NEIGHBORS[i]}
                low = max([self.lower[i]] + [self.lower[j]-edge_max[j] for j in NEIGHBORS[i]])
                high = min([self.upper[i]] + [self.upper[j]+edge_max[j] for j in NEIGHBORS[i]])
                if low > high:
                    continue
                if size % 2 and low == 0:
                    allowed.add(size)  # Still possibly a capitol.
                    continue
                if size == 1:
                    continue  # A singleton cannot be a non-capitol.
                low = max(1,low)
                if any(self.weight_supported(size,self.domains[j],
                                              low-self.upper[j],high-self.lower[j])
                       for j in NEIGHBORS[i]):
                    allowed.add(size)
            self.restrict(i,allowed,'bellman_area_support',
                          'For a removed area, neither a capitol nor any descending-neighbor equality is compatible with current distance intervals and adjacent area domains.',
                          distance=[self.lower[i],self.upper[i]],
                          neighbors=[{'cell':[j//SIZE+1,j%SIZE+1],
                                      'distance':[self.lower[j],self.upper[j]],
                                      'areas':sorted(self.domains[j])} for j in NEIGHBORS[i]])

    def propagate_inventory(self):
        """Per-area-value potential-component divisibility bounds.

        A "potential s-component" is a connected set of cells whose domain
        still admits area s. Inside it, let L be the cells already FORCED
        to exactly {s} and U be the component's whole size (all cells that
        still admit s, forced or not). The eventual number of area-s cells
        actually realized in this region is some multiple of s (an area-s
        state always has exactly s cells of area s, each belonging to
        exactly one such state) lying in [L, U] -- forced cells certainly
        count, and no cell outside the component can possibly count.

        If no multiple of s fits in [L, U] at all, that's a contradiction
        now (domains only shrink, so L only rises and U only falls --
        an empty range here never becomes non-empty). If the feasible
        range collapses to a single point at L (the largest multiple of s
        not exceeding U equals L exactly), no optional cell can add to it,
        so s is removed from every optional cell. If it collapses to a
        single point at U (the smallest multiple of s at least L equals U
        exactly), every optional cell must realize it, so each is forced to
        exactly {s}. A range that collapses to some OTHER single value
        strictly between L and U fixes the eventual count but not which
        cells realize it, so no domain action follows from that case.
        """
        values = set()
        for domain in self.domains:
            values.update(domain)
        for s in sorted(values):
            seen = set()
            for start in range(N):
                if start in seen or s not in self.domains[start]:
                    continue
                component = []
                stack = [start]
                seen.add(start)
                while stack:
                    i = stack.pop()
                    component.append(i)
                    for j in NEIGHBORS[i]:
                        if j not in seen and s in self.domains[j]:
                            seen.add(j)
                            stack.append(j)
                cells = [[i//SIZE+1,i%SIZE+1] for i in component]
                forced = [i for i in component if self.domains[i] == {s}]
                optional = [i for i in component if len(self.domains[i]) > 1]
                low, high = len(forced), len(component)
                low_multiple = s * -(-low // s)  # s * ceil(low/s)
                high_multiple = s * (high // s)  # s * floor(high/s)
                if low_multiple > high_multiple:
                    self.fail(f'No multiple of {s} fits between the {low} cells already forced to area '
                              f'{s} and the {high} cells that could still be area {s} in this connected region.',
                              area=s,forced=low,possible=high,component=cells)
                elif high_multiple == low:
                    for i in optional:
                        self.restrict(i,self.domains[i]-{s},'inventory_component_capacity',
                                      f'This region can host at most {low} area-{s} cells (all already '
                                      f'forced); no other cell here can be area {s} too.',
                                      area=s,forced=low,possible=high,component=cells)
                elif low_multiple == high:
                    for i in optional:
                        self.restrict(i,{s},'inventory_component_capacity',
                                      f'This region must host at least {high} area-{s} cells, which is '
                                      f'every cell in it; each remaining cell here must be area {s}.',
                                      area=s,forced=low,possible=high,component=cells)

    def guaranteed_distinct_capitol_count(self):
        """A sound lower bound K on the total number of distinct capitols.

        Every cell with upper[i]==0 is certainly a capitol -- that's K's
        base. Each clue-1 cell additionally needs ONE of its still-possible
        singleton neighbors (1 in that neighbor's domain) to be a capitol,
        though not which one; if that neighbor set doesn't already contain
        a certain capitol, it's a genuinely separate requirement. One
        candidate cell can satisfy multiple OVERLAPPING clue-1 groups at
        once (it's a single capitol serving all of them), so overlapping
        groups are NOT each worth a distinct capitol -- only a set of
        pairwise DISJOINT groups forces that many distinct ones (states
        have at most one capitol each, so no single cell can be the
        capitol for two groups that don't share it). Greedily packing
        disjoint groups (smallest first, to fit more) gives a valid K even
        though it may not be the true maximum packing; only the actually
        SELECTED, pairwise-disjoint groups are returned as witnesses.
        """
        certain = {i for i in range(N) if self.upper[i] == 0}
        candidates = []
        for i, n in self.clues.items():
            if n == 1:
                group = {j for j in NEIGHBORS[i] if 1 in self.domains[j]}
                if group and not (group & certain):
                    candidates.append(group)
        used, selected = set(), []
        for group in sorted(candidates, key=len):
            if not (group & used):
                used |= group
                selected.append(group)
        return len(certain) + len(selected), certain, selected

    def propagate_global_capitol_count(self):
        k, certain, groups = self.guaranteed_distinct_capitol_count()
        if k <= 1:
            return
        for i in range(N):
            odd_limit, even_limit = N-k+1, N-k
            allowed = [s for s in self.domains[i] if s <= (even_limit if s % 2 == 0 else odd_limit)]
            self.restrict(i,allowed,'global_capitol_count',
                          f'At least {k} cells are provably distinct capitols (each needing its own, '
                          f'non-overlapping, odd-area state), so no single state can leave fewer than '
                          f'{k}-1 cells (or all {k}, if this state is not itself one of them) for the rest.',
                          guaranteed_capitols=k,certain_cells=[[c//SIZE+1,c%SIZE+1] for c in sorted(certain)],
                          disjoint_groups=[[[j//SIZE+1,j%SIZE+1] for j in sorted(g)] for g in groups])

    def run(self):
        rounds = 0
        initial_options = None
        status = 'deduction_fixed_point'
        try:
            self.seed()
            initial_options = sum(map(len,self.domains))
            while True:
                before = self.revision
                rounds += 1
                self.propagate_distances()
                self.propagate_two_step_area_bound()
                self.propagate_area_support()
                self.propagate_inventory()
                self.propagate_global_capitol_count()
                if self.revision == before:
                    break
        except Contradiction:
            status = 'contradiction'
        final_options = sum(map(len,self.domains))
        return {'status':status, 'scope':'Clue-only necessary deductions for finite-distance solutions. '
                'No branching, paint, area cutoff, or sampled shape pool. A fixed point is not a solved partition.',
                'clues':[{'cell':[i//SIZE+1,i%SIZE+1],'value':n} for i,n in sorted(self.clues.items())],
                'rounds':rounds, 'initial_area_options':initial_options,
                'remaining_area_options':final_options,
                'additional_area_options_removed':None if initial_options is None else initial_options-final_options,
                'area_domains':[[sorted(self.domains[r*SIZE+c]) for c in range(SIZE)] for r in range(SIZE)],
                'distance_intervals':[[[self.lower[r*SIZE+c],self.upper[r*SIZE+c]] for c in range(SIZE)] for r in range(SIZE)],
                'forced_areas':[{'cell':[i//SIZE+1,i%SIZE+1],'area':next(iter(domain))}
                                for i,domain in enumerate(self.domains) if len(domain)==1],
                'rule_counts':dict(Counter(step['rule'] for step in self.steps)),
                'contradiction':self.contradiction, 'steps':self.steps}


def deduce(state):
    return DeductionEngine(state).run()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='solver-deduction-report.json')
    args = parser.parse_args()
    report = deduce(new_workspace().saved)
    Path(args.output).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items()
                      if k not in ('area_domains','distance_intervals','steps','clues')},indent=2))
