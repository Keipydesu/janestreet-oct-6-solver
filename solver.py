"""Bounded clue-only exact-cover search with global shortest-path pruning.
Run: python3 solver.py --seconds 120 --output solver-report.json
Never changes the editor or project.json. Candidate sampling is NOT exhaustive.
"""
import argparse
import colorsys
from collections import Counter
import heapq
import json
import time
from pathlib import Path
from candidate_search import search_candidates, NEIGHBORS, indices, neighbors_for_size
from model import GridState, SIZE
from starting_grid import new_workspace

N = SIZE * SIZE
FULL = (1 << N) - 1
INF = float('inf')


def distances(areas, capitals, size=SIZE):
    return distance_envelope(areas, {i: 0 for i in capitals}, size)


def distance_envelope(areas, seeds, size=SIZE):
    """Minimum seed value plus weighted path cost (seed values may be negative)."""
    N = size * size
    NEIGHBORS = neighbors_for_size(size)
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


def shape_has_distance_support(shape, area_low, area_high, lower, upper, size):
    """Necessary Bellman support for a fixed shape, with relaxed surroundings.

    Outside areas and distances may be independently chosen from intervals.
    This can admit impossible shapes, but cannot reject a realizable one.
    Internal edge costs are exact, including for states without a capitol.
    """
    mask, cap = shape
    area = mask.bit_count()
    neighbors = neighbors_for_size(size)
    for i in indices(mask):
        lo, hi = lower[i], upper[i]
        if i == cap:
            if lo > 0:
                return False
            hi = min(hi, 0)
        else:
            lo = max(lo, 1)
        edges = []
        for j in neighbors[i]:
            inside = bool(mask & (1 << j))
            wlo = area if inside else min(area, area_low[j])
            whi = area if inside else min(area, area_high[j])
            jlo, jhi = lower[j], upper[j]
            if j == cap:
                jlo, jhi = max(jlo, 0), min(jhi, 0)
            elif inside:
                jlo = max(jlo, 1)
            # Every edge must permit |d(i)-d(j)| <= its cost.
            lo = max(lo, jlo - whi)
            hi = min(hi, jhi + whi)
            edges.append((jlo, jhi, wlo, whi))
        if lo > hi:
            return False
        # Some edge must attain d(i) = d(j) + cost, unless i is a capitol.
        if i != cap and not any(max(lo, jlo + wlo) <= min(hi, jhi + whi)
                                for jlo, jhi, wlo, whi in edges):
            return False
    return True


class TravelConstraints:
    """Cache clue facts and bound distances for a partial exact cover.

    Candidate domains, when supplied, restrict the claim to completions from
    that pool. They must include every remaining compatible candidate.
    """

    def __init__(self, state):
        self.size = SIZE = state.size
        self.clues = {r*SIZE+c: x.starting_number for r,row in enumerate(state.grid)
                      for c,x in enumerate(row) if x.starting_number is not None}
        d = state.deductions()
        self.low = [v for row in d['minimum_state_sizes'] for v in row]
        self.certain = {i for i,n in self.clues.items() if n == 0}
        self.singletons = {r*SIZE+c for r,c in d['forced_singletons']}
        self.certain.update(self.singletons)

    def rejection(self, chosen, max_area, domains=None, candidates=None,
                  unsupported=None, deadline=INF):
        N = self.size * self.size
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
        upper = distance_envelope(high, upper_seeds, self.size)
        if any(upper[i] < n for i,n in self.clues.items()):
            return 'clue_path'

        # d(v) >= clue(u) - path(u,v). Positive lower bounds rule out
        # additional capitols, strengthening the optimistic nearest route.
        negative_lower = distance_envelope(high, {i: -n for i,n in self.clues.items()}, self.size)
        possible = {i for i in possible if negative_lower[i] >= 0}
        if not certain <= possible or not possible:
            return 'capitol'
        lower = distances(low, possible, self.size)
        lower = [max(value, -negative_lower[i]) for i, value in enumerate(lower)]
        if any(lower[i] > upper[i] for i in range(N)):
            return 'distance'
        for shape in chosen:
            if not shape_has_distance_support(shape, low, high, lower, upper, self.size):
                return 'bellman'
        if unsupported is not None and domains is not None:
            for k in set(k for options in domains.values() for k in options):
                if time.monotonic() >= deadline:
                    break
                if not shape_has_distance_support(candidates[k], low, high,
                                                  lower, upper, self.size):
                    unsupported.add(k)
        return None


def travel_feasible(state, chosen, max_area, domains=None, candidates=None):
    """Necessary bounds; a sampled candidate pool never proves impossibility."""
    return TravelConstraints(state).rejection(chosen, max_area, domains, candidates) is None


def materialize(state, chosen):
    SIZE = state.size
    result = GridState.from_dict(state.to_dict())
    for row in result.grid:
        for cell in row:
            cell.region_color = None
            cell.is_capital = cell.capital_required
    for number, (mask, cap) in enumerate(chosen, 1):
        # Unique six-digit colors preserve state identity, including adjacent states.
        color = '#%02x%02x%02x' % tuple(round(v*255) for v in colorsys.hsv_to_rgb((number*.61803398875)%1, .42, .95))
        for i in indices(mask):
            cell = result.grid[i//SIZE][i%SIZE]
            cell.region_color = color
            cell.is_capital = i == cap or cell.capital_required
    return result


def forbidden_capitols(state, max_area, deductions=None):
    """Clue-only exclusions valid throughout this capped search."""
    deductions = deductions if deductions is not None else state.deductions()
    high = [max_area] * (state.size * state.size)
    for r, c in deductions['forced_singletons']:
        high[r*state.size+c] = 1
    clues = {r*state.size+c: cell.starting_number
             for r,row in enumerate(state.grid) for c,cell in enumerate(row)
             if cell.starting_number is not None}
    negative = distance_envelope(high, {i: -n for i,n in clues.items()}, state.size)
    return {i for i,value in enumerate(negative) if value < 0}


def decomposition_signature(chosen):
    """Forget borders only where occupied cell areas AND capitols agree."""
    by_area = {}
    capitals = 0
    for mask, cap in chosen:
        area = mask.bit_count()
        by_area[area] = by_area.get(area, 0) | mask
        if cap is not None:
            capitals |= 1 << cap
    return tuple(sorted(by_area.items())), capitals


def constrained_options(domains, candidates):
    """Prefer few area choices, then smaller area ceilings and shape counts."""
    def priority(item):
        cell, options = item
        areas = {candidates[k][0].bit_count() for k in options}
        return len(areas), max(areas), len(options), cell
    _, options = min(domains.items(), key=priority)
    return sorted(options, key=lambda k: (candidates[k][0].bit_count(), k))


def solve(state, seconds=120, max_area=None, per_root_seconds=.3, progress=None):
    SIZE = state.size
    N = SIZE * SIZE
    FULL = (1 << N) - 1
    if max_area is None:
        max_area = min(98, N)
    if type(max_area) is not int or not 1 <= max_area <= N:
        raise ValueError(f"Maximum area must be from 1 to {N}.")
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
    counts = Counter()
    excluded_capitols = forbidden_capitols(state, max_area, deductions)
    pool = {}
    generated_roots = 0
    exhaustive_roots = set()
    generation_attempts = Counter()
    generated_limits = {}
    bounds = [v for row in deductions['minimum_state_sizes'] for v in row]
    forced = {r*SIZE+c for r,c in deductions['forced_singletons']}
    clues = {r*SIZE+c: cell.starting_number for r,row in enumerate(state.grid)
             for c,cell in enumerate(row) if cell.starting_number is not None}
    area_choices = {}
    for i in range(N):
        values = {1} if i in forced else set(range(bounds[i], max_area+1))
        if clues.get(i) == 0:
            values = {a for a in values if a % 2}
        if clues.get(i, 0) > 0 or any(clues.get(j, 0) > 1
                                     for j in neighbors_for_size(SIZE)[i]):
            values.discard(1)
        area_choices[i] = values

    def next_limit(root):
        if root in forced:
            return 1
        previous = generated_limits.get(root, 0)
        return min(max_area, max(4, bounds[root], previous * 2))

    def root_priority(root):
        return (next_limit(root), len(area_choices[root]),
                generation_attempts[root], root)

    def generate(root, budget):
        nonlocal generated_roots
        r,c = divmod(root,SIZE)
        limit = next_limit(root)
        result = search_candidates(state,r,c,max_area=limit,
            time_limit=min(budget,max(0,deadline-time.monotonic())),
            node_limit=100000 * (generation_attempts[root]+1),preview_limit=None)
        generation_attempts[root] += 1
        generated_limits[root] = limit
        if result['complete_within_limit'] and (limit == max_area or root in forced):
            exhaustive_roots.add(root)
        for candidate in result['survivors']:
            mask = sum(1 << (r*SIZE+c) for r,c in candidate['cells'])
            cap = candidate['capitol']
            cap = None if cap is None else cap[0]*SIZE+cap[1]
            if cap in excluded_capitols:
                counts['initial_capitol_prunes'] += 1
                continue
            pool[mask] = cap
        generated_roots = len(generation_attempts)

    # Begin with small states. Higher-area roots are deferred to expansion.
    # Reserve time for partition search rather than consuming the entire
    # editor budget on its first generation pass.
    initial_deadline = start + max(0, seconds) / 2
    initial_roots = sorted((i for i in range(N) if bounds[i] <= 4), key=root_priority)
    for position, root in enumerate(initial_roots):
        remaining = initial_deadline - time.monotonic()
        if remaining <= 0:
            break
        generate(root, min(per_root_seconds, remaining / (len(initial_roots)-position)))
        if progress and generated_roots % 11 == 0:
            progress({'phase':'candidates','roots':generated_roots,'candidates':len(pool)})
    candidates = list(pool.items())
    covering = [[] for _ in range(N)]
    for k,(mask,cap) in enumerate(candidates):
        for i in indices(mask):
            covering[i].append(k)
    best = []
    solution = None
    timed_out = False
    travel = TravelConstraints(state)
    bottlenecks = Counter()
    failed_signatures = set()

    def visit(occupied, chosen):
        nonlocal timed_out
        if time.monotonic() >= deadline:
            timed_out = True
            return False
        signature = decomposition_signature(chosen)
        if signature in failed_signatures:
            counts['equivalent_partition_prunes'] += 1
            return False
        found = search_node(occupied, chosen)
        if not found and not timed_out:
            failed_signatures.add(signature)
        return found

    def search_node(occupied, chosen):
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
        # Remove unsupported shapes everywhere, then propagate the tighter
        # domains. A bounded number of rounds limits overhead; stopping early
        # only leaves extra possibilities, never discards a legal completion.
        for _ in range(3):
            unsupported = set()
            rejection = travel.rejection(chosen, max_area, domains, candidates,
                                         unsupported, deadline)
            if time.monotonic() >= deadline:
                timed_out = True
                return False
            if rejection:
                counts['travel_prunes'] += 1
                counts[rejection + '_prunes'] += 1
                return False
            if not unsupported:
                break
            counts['candidate_support_prunes'] += len(unsupported)
            counts['support_rounds'] += 1
            domains = {i: [k for k in options if k not in unsupported]
                       for i, options in domains.items()}
            if any(not options for options in domains.values()):
                counts['bellman_prunes'] += 1
                counts['travel_prunes'] += 1
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
        options = constrained_options(domains, candidates)
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
                       key=lambda i: (next_limit(i), len(area_choices[i]),
                                      generation_attempts[i], -bottlenecks[i], i))[:11]
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
        failed_signatures.clear()  # A larger pool can complete an old failed state.
        if progress:
            progress({'phase':'expansion', 'candidates':len(pool),
                      'search_round':counts['search_rounds']})
        visit(0,[])
    report = {'status':'verified_solution' if solution else 'time_limit' if timed_out else 'sample_exhausted',
        'elapsed_seconds':round(time.monotonic()-start,3),'max_area':max_area,
        'candidate_count':len(pool),'roots_generated':generated_roots,'statistics':dict(counts),
        'generation_calls':sum(generation_attempts.values()),
        'largest_generation_limit':max(generated_limits.values(), default=0),
        'initial_forbidden_capitols':[[i//SIZE+1, i%SIZE+1] for i in sorted(excluded_capitols)],
        'complete_candidate_roots':len(exhaustive_roots),
        'board_cells':N,
        'best_partial_coverage':sum(mask.bit_count() for mask,cap in best),
        'scope':'Clues only. Sampled symmetric states up to the area limit; no conclusion of global impossibility is valid.',
        'solution':solution.to_dict() if solution else None}
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=float,default=120)
    parser.add_argument('--max-area',type=int,default=98,choices=range(1,122))
    parser.add_argument('--per-root-seconds',type=float,default=.3)
    parser.add_argument('--output',default='solver-report.json')
    args = parser.parse_args()
    report = solve(new_workspace().saved,args.seconds,args.max_area,args.per_root_seconds,
                   progress=lambda item: print(json.dumps(item),flush=True))
    Path(args.output).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='solution'},indent=2))
