"""Bounded clue-only exact-cover search with global shortest-path pruning.
Run: python3 solver.py --seconds 120 --output solver-report.json
Never changes the editor or project.json. Candidate sampling is NOT exhaustive.
"""
import argparse
from collections import Counter
import heapq
import json
import time
from pathlib import Path
from candidate_search import search_candidates, NEIGHBORS, indices
from model import GridState, SIZE
from starting_grid import new_workspace

N = SIZE * SIZE
FULL = (1 << N) - 1
INF = float('inf')


def distances(areas, capitals):
    return distance_envelope(areas, {i: 0 for i in capitals})


def distance_envelope(areas, seeds):
    """Minimum seed value plus weighted path cost (seed values may be negative)."""
    result = [INF] * N
    queue = [(value, i) for i, value in seeds.items()]
    for value, i in queue:
        result[i] = value
    heapq.heapify(queue)
    while queue:
        cost, i = heapq.heappop(queue)
        if cost != result[i]:
            continue
        for j in NEIGHBORS[i]:
            value = cost + min(areas[i], areas[j])
            if value < result[j]:
                result[j] = value
                heapq.heappush(queue, (value, j))
    return result


class TravelConstraints:
    """Cache clue facts and bound distances for a partial exact cover.

    Candidate domains, when supplied, restrict the claim to completions from
    that pool. They must include every remaining compatible candidate.
    """

    def __init__(self, state):
        self.clues = {r*SIZE+c: x.starting_number for r,row in enumerate(state.grid)
                      for c,x in enumerate(row) if x.starting_number is not None}
        d = state.deductions()
        self.low = [v for row in d['minimum_state_sizes'] for v in row]
        self.certain = {i for i,n in self.clues.items() if n == 0}
        self.singletons = {r*SIZE+c for r,c in d['forced_singletons']}
        self.certain.update(self.singletons)

    def rejection(self, chosen, max_area, domains=None, candidates=None):
        low = self.low[:]
        high = [max_area] * N
        possible = {i for i in range(N) if self.clues.get(i, 0) == 0}
        certain = self.certain.copy()
        for i in self.singletons:
            low[i] = high[i] = 1
        if domains is not None:
            for i, options in domains.items():
                if not options:
                    return 'cover'
                sizes = [candidates[k][0].bit_count() for k in options]
                low[i] = max(low[i], min(sizes))
                high[i] = min(high[i], max(sizes))
                caps = [candidates[k][1] == i for k in options]
                if not any(caps):
                    possible.discard(i)
                if all(caps):
                    certain.add(i)
        for mask, cap in chosen:
            cells = set(indices(mask))
            if any(low[i] > len(cells) or high[i] < len(cells) for i in cells):
                return 'area'
            if any(i in certain and i != cap for i in cells):
                return 'capitol'
            for i in cells:
                low[i] = high[i] = len(cells)
            possible.difference_update(cells)
            if cap is not None:
                possible.add(cap)
                certain.add(cap)
        if any(a > b for a,b in zip(low,high)):
            return 'area'
        if not certain <= possible:
            return 'capitol'

        # d(v) <= clue(u) + path(u,v). One multi-source pass checks all
        # clue pairs, including paths crossing several different states.
        upper_seeds = dict(self.clues)
        upper_seeds.update({i: 0 for i in certain})
        upper = distance_envelope(high, upper_seeds)
        if any(upper[i] < n for i,n in self.clues.items()):
            return 'clue_path'

        # d(v) >= clue(u) - path(u,v). Positive lower bounds rule out
        # additional capitols, strengthening the optimistic nearest route.
        negative_lower = distance_envelope(high, {i: -n for i,n in self.clues.items()})
        possible = {i for i in possible if negative_lower[i] >= 0}
        if not certain <= possible or not possible:
            return 'capitol'
        lower = distances(low, possible)
        if any(lower[i] > upper[i] for i in range(N)):
            return 'distance'
        return None


def travel_feasible(state, chosen, max_area, domains=None, candidates=None):
    """Necessary bounds; a sampled candidate pool never proves impossibility."""
    return TravelConstraints(state).rejection(chosen, max_area, domains, candidates) is None


def materialize(state, chosen):
    result = GridState.from_dict(state.to_dict())
    for row in result.grid:
        for cell in row:
            cell.region_color = None
            cell.is_capital = cell.capital_required
    for number, (mask, cap) in enumerate(chosen, 1):
        # Unique six-digit colors preserve state identity, including adjacent states.
        color = '#%06x' % number
        for i in indices(mask):
            cell = result.grid[i//SIZE][i%SIZE]
            cell.region_color = color
            cell.is_capital = i == cap or cell.capital_required
    return result


def solve(state, seconds=120, max_area=121, per_root_seconds=.3, progress=None):
    if type(max_area) is not int or not 1 <= max_area <= N:
        raise ValueError("Maximum area must be from 1 to 121.")
    start = time.monotonic()
    deadline = start + seconds
    # A route to any mandatory capitol is an upper bound on the clue value.
    deductions = state.deductions()
    if not deductions['available'] or deductions['contradictions']:
        raise ValueError('Invalid or contradictory starting clues.')
    guaranteed = {r*SIZE+c for r,row in enumerate(state.grid) for c,cell in enumerate(row)
                  if cell.starting_number == 0}
    guaranteed.update(r*SIZE+c for r,c in deductions['forced_singletons'])
    violations = []
    for r,row in enumerate(state.grid):
        for c,cell in enumerate(row):
            value = cell.starting_number
            if value is None or not guaranteed:
                continue
            cap = min(guaranteed,key=lambda i:abs(r-i//SIZE)+abs(c-i%SIZE))
            steps = abs(r-cap//SIZE)+abs(c-cap%SIZE)
            if steps and value > steps*max_area:
                violations.append({'clue':[r+1,c+1], 'value':value,
                    'mandatory_capitol':[cap//SIZE+1,cap%SIZE+1], 'steps':steps,
                    'maximum_route_cost':steps*max_area,
                    'required_maximum_state_area':int((value+steps-1)//steps)})
    if violations:
        return {'status':'area_limit_contradiction','max_area':max_area,
                'elapsed_seconds':round(time.monotonic()-start,3),
                'violations':violations,'solution':None,
                'scope':'Proves the area limit is too small, not that the puzzle is impossible.'}
    pool = {}
    generated_roots = 0
    exhaustive_roots = set()
    generation_attempts = Counter()

    def generate(root, budget):
        nonlocal generated_roots
        r,c = divmod(root,SIZE)
        result = search_candidates(state,r,c,max_area=max_area,
            time_limit=min(budget,max(0,deadline-time.monotonic())),
            node_limit=100000 * (generation_attempts[root]+1),preview_limit=None)
        generation_attempts[root] += 1
        if result['complete_within_limit']:
            exhaustive_roots.add(root)
        for candidate in result['survivors']:
            mask = sum(1 << (r*SIZE+c) for r,c in candidate['cells'])
            cap = candidate['capitol']
            pool[mask] = None if cap is None else cap[0]*SIZE+cap[1]
        generated_roots = len(generation_attempts)

    # Roots with strongest size bounds first, then all remaining squares.
    deductions = state.deductions()
    if not deductions['available'] or deductions['contradictions']:
        raise ValueError('Invalid or contradictory starting clues.')
    bounds = [v for row in deductions['minimum_state_sizes'] for v in row]
    for root in sorted(range(N), key=lambda i: -bounds[i]):
        if time.monotonic() >= deadline:
            break
        generate(root, per_root_seconds)
        if progress and generated_roots % 11 == 0:
            progress({'phase':'candidates','roots':generated_roots,'candidates':len(pool)})
    candidates = list(pool.items())
    covering = [[] for _ in range(N)]
    for k,(mask,cap) in enumerate(candidates):
        for i in indices(mask):
            covering[i].append(k)
    counts = Counter()
    best = []
    solution = None
    timed_out = False
    travel = TravelConstraints(state)
    bottlenecks = Counter()

    def visit(occupied, chosen):
        nonlocal best, solution, timed_out
        if time.monotonic() >= deadline:
            timed_out = True
            return False
        counts['nodes'] += 1
        domains = {}
        for i in indices(FULL ^ occupied):
            available = [k for k in covering[i] if not candidates[k][0] & occupied]
            if not available:
                counts['cover_prunes'] += 1
                bottlenecks[i] += 1
                return False
            domains[i] = available
        rejection = travel.rejection(chosen, max_area, domains, candidates)
        if rejection:
            counts['travel_prunes'] += 1
            counts[rejection + '_prunes'] += 1
            return False
        if occupied.bit_count() > sum(mask.bit_count() for mask,cap in best):
            best = chosen[:]
        if occupied == FULL:
            counts['complete_partitions'] += 1
            candidate = materialize(state,chosen)
            if candidate.validate_puzzle()['puzzle_valid']:
                solution = candidate
                return True
            counts['validation_rejections'] += 1
            return False
        options = min(domains.values(), key=len)
        # Large compatible states tend to settle the high-cost clues earlier.
        options.sort(key=lambda k: -candidates[k][0].bit_count())
        for k in options:
            mask,cap = candidates[k]
            if visit(occupied | mask,chosen+[candidates[k]]):
                return True
            if timed_out:
                return False
        return False

    counts['search_rounds'] = 1
    visit(0,[])
    # A failed sampled exact cover says nothing about shapes omitted by the
    # generator. Expand at bottleneck cells, then restart: earlier pool-based
    # prunes are not valid for the enlarged pool.
    while solution is None and not timed_out and len(exhaustive_roots) < N:
        if time.monotonic() >= deadline:
            timed_out = True
            break
        roots = sorted((i for i in range(N) if i not in exhaustive_roots),
                       key=lambda i: (generation_attempts[i], -bottlenecks[i], -bounds[i]))[:11]
        generation_deadline = time.monotonic() + (deadline-time.monotonic()) / 2
        previous_count = len(pool)
        for root in roots:
            remaining = generation_deadline-time.monotonic()
            if remaining <= 0:
                break
            # Restarting the deterministic generator requires a larger budget
            # to reach shapes beyond the earlier sampled prefix.
            budget = max(.01, per_root_seconds) * 2 ** min(generation_attempts[root], 10)
            generate(root, min(budget, remaining))
        counts['expansion_batches'] += 1
        if len(pool) == previous_count:
            continue
        candidates = list(pool.items())
        covering = [[] for _ in range(N)]
        for k,(mask,cap) in enumerate(candidates):
            for i in indices(mask):
                covering[i].append(k)
        counts['search_rounds'] += 1
        if progress:
            progress({'phase':'expansion', 'candidates':len(pool),
                      'search_round':counts['search_rounds']})
        visit(0,[])
    report = {'status':'verified_solution' if solution else 'time_limit' if timed_out else 'sample_exhausted',
        'elapsed_seconds':round(time.monotonic()-start,3),'max_area':max_area,
        'candidate_count':len(pool),'roots_generated':generated_roots,'statistics':dict(counts),
        'generation_calls':sum(generation_attempts.values()),
        'best_partial_coverage':sum(mask.bit_count() for mask,cap in best),
        'scope':'Clues only. Sampled symmetric states up to the area limit; no conclusion of global impossibility is valid.',
        'solution':solution.to_dict() if solution else None}
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=float,default=120)
    parser.add_argument('--max-area',type=int,default=121,choices=range(1,122))
    parser.add_argument('--per-root-seconds',type=float,default=.3)
    parser.add_argument('--output',default='solver-report.json')
    args = parser.parse_args()
    report = solve(new_workspace().saved,args.seconds,args.max_area,args.per_root_seconds,
                   progress=lambda item: print(json.dumps(item),flush=True))
    Path(args.output).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='solution'},indent=2))
