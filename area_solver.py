"""Experimental area-first constraint solver; requires requirements-cp.txt.

Distances and area inventory are solved before shapes. Invalid geometric
components produce sound cuts; a timed-out component never produces a cut.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import time

from candidate_search import NEIGHBORS, indices
from model import GridState, SIZE
from solver import N, distances, materialize
from starting_grid import new_workspace
from symmetric_shapes import NEIGHBOR_MASK


class GeometryTimeout(Exception):
    pass


def components(mask):
    """Connected components of a board bit mask."""
    while mask:
        reached = front = mask & -mask
        while front:
            adjacent = 0
            for i in indices(front):
                adjacent |= NEIGHBOR_MASK[i]
            front = adjacent & mask & ~reached
            reached |= front
        yield reached
        mask ^= reached


def shape_capitol(mask):
    symmetry = GridState.shape_symmetry([divmod(i, SIZE) for i in indices(mask)])
    if not symmetry['symmetric']:
        return False, None
    operations = symmetry['operations']
    if all(op['fixed_count'] == 1 for op in operations):
        fixed = operations[0]['fixed_cells'][0]
        if all(op['fixed_cells'][0] == fixed for op in operations):
            return True, fixed[0] * SIZE + fixed[1]
    return True, None


def partition_component(mask, size, capitols, deadline=float('inf')):
    """Exact geometry subproblem; None means proved impossible, not timeout.

    Adjacent states of equal area may form one larger component. They must
    be partitioned, not mistaken for one state. Only the size==area case is
    uniquely determined. Capitol arguments are cell-index sets.
    """
    cap_mask = sum(1 << i for i in capitols)
    failed = set()

    def check_time():
        if time.monotonic() >= deadline:
            raise GeometryTimeout

    def acceptable(shape):
        valid, cap = shape_capitol(shape)
        return valid and shape & cap_mask == (0 if cap is None else 1 << cap), cap

    def states(allowed):
        root = allowed & -allowed
        root_i = root.bit_length() - 1
        # Include/exclude a frontier square. Excluded squares stay excluded,
        # preventing the same connected subset being generated in many orders.
        stack = [(root, NEIGHBOR_MASK[root_i] & allowed & ~root, 0)]
        while stack:
            check_time()
            shape, frontier, excluded = stack.pop()
            area = shape.bit_count()
            if (shape & cap_mask).bit_count() > 1:
                continue
            if area == size:
                good, cap = acceptable(shape)
                if good:
                    yield shape, cap
                continue
            if not frontier:
                continue
            bit = frontier & -frontier
            rest = frontier ^ bit
            stack.append((shape, rest, excluded | bit))
            neighbors = NEIGHBOR_MASK[bit.bit_length() - 1]
            stack.append((shape | bit,
                          (rest | neighbors) & allowed & ~(shape | bit | excluded),
                          excluded))

    def visit(remaining):
        check_time()
        if not remaining:
            return []
        if remaining in failed:
            return None
        parts = list(components(remaining))
        if any(part.bit_count() % size for part in parts):
            failed.add(remaining)
            return None
        # Disconnected residual components are independent subproblems.
        if len(parts) > 1:
            result = []
            for part in parts:
                sub = visit(part)
                if sub is None:
                    failed.add(remaining)
                    return None
                result.extend(sub)
            return result
        if (remaining & cap_mask).bit_count() > remaining.bit_count() // size:
            failed.add(remaining)
            return None
        if remaining.bit_count() == size:
            good, cap = acceptable(remaining)
            if good:
                return [(remaining, cap)]
        else:
            for shape, cap in states(remaining):
                rest = visit(remaining ^ shape)
                if rest is not None:
                    return [(shape, cap)] + rest
        failed.add(remaining)
        return None

    return visit(mask)


def small_state_templates(size):
    """Every distinct symmetric connected placement of exactly this area.

    Enumerating from every root cell and deduplicating covers all possible
    positions and orientations; cheap only because size is small (2 or 3).
    """
    from symmetric_shapes import symmetric_masks, connected
    found = set()
    for root in range(N):
        for mask in symmetric_masks(root, size):
            if mask.bit_count() != size or mask in found or not connected(mask):
                continue
            valid, cap = shape_capitol(mask)
            if valid:
                found.add(mask)
                yield mask, cap


def add_small_templates(model, is_area, cap, size):
    """Tie an area indicator to an ACTUAL placement for small, cheap sizes.

    Removes "fake" area patterns the abstract relaxation would otherwise
    allow: a selected placement forces the real capitol pattern, and the
    per-cell coverage equality forbids two placements claiming one cell
    (sum would exceed the boolean indicator) without extra constraints.
    """
    covering = [[] for _ in range(N)]
    for mask, cap_cell in small_state_templates(size):
        selected = model.new_bool_var(f'template{size}_{mask}')
        for i in indices(mask):
            covering[i].append(selected)
        for i in indices(mask):
            if i == cap_cell:
                model.add_implication(selected, cap[i])
            else:
                model.add_implication(selected, ~cap[i])
    for i in range(N):
        model.add(sum(covering[i]) == is_area[i][size])


def build_area_model(state, max_area=N, template_sizes=(2, 3)):
    """Exact distance constraints, with exhaustive templates only for small states."""
    try:
        from ortools.sat.python import cp_model
    except ImportError as exc:
        raise RuntimeError('Install optional dependencies: python -m pip install -r requirements-cp.txt') from exc
    facts = state.deductions()
    if not facts['available'] or facts['contradictions']:
        raise ValueError('Invalid or contradictory starting clues.')
    # Every removed domain value has a clue-only necessary-condition proof.
    # Applying these deductions before search preserves every legal partition.
    from deduction_engine import deduce
    deductions = deduce(state)
    model = cp_model.CpModel()
    if deductions['status'] == 'contradiction':
        model.add_bool_or([])
    clues = {r*SIZE+c: cell.starting_number for r, row in enumerate(state.grid)
             for c, cell in enumerate(row) if cell.starting_number is not None}
    forced = {r*SIZE+c for r, c in facts['forced_singletons']}
    certain = forced | {i for i, value in clues.items() if value == 0}
    upper = distances([1 if i in forced else max_area for i in range(N)], certain)
    limit = (N-1)*max_area
    area, distance, cap, is_area = [], [], [], []
    for i in range(N):
        low = facts['minimum_state_sizes'][i//SIZE][i%SIZE]
        a = model.new_int_var(1, max_area, f'a{i}')
        model.add(a >= low)
        model.add_linear_expression_in_domain(
            a, cp_model.Domain.from_values(deductions['area_domains'][i//SIZE][i%SIZE]))
        d = model.new_int_var(0, min(limit, int(upper[i])) if certain else limit, f'd{i}')
        proven_low, proven_high = deductions['distance_intervals'][i//SIZE][i%SIZE]
        model.add(d >= proven_low)
        model.add(d <= proven_high)
        c = model.new_bool_var(f'cap{i}')
        model.add(d == 0).only_enforce_if(c)
        model.add(d >= 1).only_enforce_if(~c)
        if i in clues:
            model.add(d == clues[i])
        flags = {}
        for s in range(1, max_area+1):
            flag = model.new_bool_var(f'a{i}_{s}')
            model.add(a == s).only_enforce_if(flag)
            model.add(a != s).only_enforce_if(~flag)
            flags[s] = flag
            if s % 2 == 0:
                model.add_implication(flag, ~c)
        model.add_implication(flags[1], c)
        if i in forced:
            model.add(a == 1)
        area.append(a); distance.append(d); cap.append(c); is_area.append(flags)
    state_counts = []
    for s in range(1, max_area+1):
        count = model.new_int_var(0, N//s, f'states{s}')
        model.add(sum(flags[s] for flags in is_area) == s*count)
        state_counts.append(count)
    # Capitols only exist in odd-area states (proven: any nontrivial symmetry
    # admitting a capitol is an involution or generates one, so non-capitol
    # cells pair up evenly and area = 1 + 2k). Crediting even-size counts
    # toward the capitol budget leaves extra slack, not just a weaker
    # restatement of the existing per-cell parity implications: those stop a
    # single even-area cell from being a capitol, but nothing else currently
    # stops the relaxed model from handing out more capitols across odd sizes
    # than those sizes' own state_counts could ever host.
    model.add(sum(cap) <= sum(count for s, count in zip(range(1, max_area+1), state_counts) if s % 2))
    for size in template_sizes:
        if size <= max_area:
            add_small_templates(model, is_area, cap, size)
    witnesses = [[] for _ in range(N)]
    same_neighbors = [[] for _ in range(N)]
    for i in range(N):
        for j in NEIGHBORS[i]:
            if j < i:
                continue
            cost = model.new_int_var(1, max_area, f'edge{i}_{j}')
            model.add_min_equality(cost, [area[i], area[j]])
            equal = model.new_bool_var(f'same_area{i}_{j}')
            model.add(area[i] == area[j]).only_enforce_if(equal)
            model.add(area[i] != area[j]).only_enforce_if(~equal)
            same_neighbors[i].append(equal); same_neighbors[j].append(equal)
            for u, v in ((i,j), (j,i)):
                model.add(distance[u] <= distance[v] + cost)
                witness = model.new_bool_var(f'down{u}_{v}')
                model.add(distance[u] == distance[v] + cost).only_enforce_if(witness)
                witnesses[u].append(witness)
    for i in range(N):
        model.add_bool_or([cap[i]] + witnesses[i])
        model.add_bool_or([is_area[i][1]] + same_neighbors[i])
    return model, area, distance, cap, is_area



def add_component_cut(model, is_area, cap, component, size, caps, area_only=False):
    """Exclude a proved-bad component, allowing its boundary/capitols to change."""
    border = 0
    for i in indices(component):
        border |= NEIGHBOR_MASK[i]
    border &= ~component
    cut = [~is_area[i][size] for i in indices(component)]
    cut += [is_area[i][size] for i in indices(border)]
    if not area_only:
        cut += [~cap[i] if i in caps else cap[i] for i in indices(component)]
    model.add_bool_or(cut)


def solve_area(state, seconds=120, max_area=N, workers=1, progress=None):
    if type(max_area) is not int or not 1 <= max_area <= N:
        raise ValueError('Maximum area must be from 1 to 121.')
    if seconds < 0 or workers < 1:
        raise ValueError('Use a nonnegative time budget and at least one worker.')
    started = time.monotonic(); deadline = started + seconds
    counts = Counter()
    if seconds == 0:
        return {'status':'time_limit', 'solution':None, 'statistics':{}, 'elapsed_seconds':0}
    model, area, distance, cap, is_area = build_area_model(state, max_area)
    from ortools.sat.python import cp_model
    counts['model_variables'] = len(model.proto.variables)
    result_status = 'time_limit'
    solution = None
    last_assignment = None
    while time.monotonic() < deadline:
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(.001, deadline-time.monotonic())
        solver.parameters.num_search_workers = workers
        status = solver.solve(model)
        counts['cp_calls'] += 1
        counts['cp_branches'] += solver.num_branches
        counts['cp_conflicts'] += solver.num_conflicts
        if status == cp_model.INFEASIBLE:
            result_status = 'infeasible_within_area_limit'
            break
        if status == cp_model.MODEL_INVALID:
            raise RuntimeError(model.validate())
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            break
        values = [solver.value(a) for a in area]
        caps = {i for i, c in enumerate(cap) if solver.boolean_value(c)}
        counts['area_assignments'] += 1
        last_assignment = {'areas':values, 'capitols':sorted(caps),
                           'distances':[solver.value(d) for d in distance]}
        chosen = []; cuts = 0
        try:
            for size in sorted(set(values), reverse=True):
                mask = sum(1 << i for i, value in enumerate(values) if value == size)
                for component in components(mask):
                    part = partition_component(component, size, caps, deadline)
                    if part is not None:
                        chosen.extend(part)
                        continue
                    # Keeping these cells at size s AND every boundary cell
                    # away from s keeps exactly this connected component.
                    area_only = component.bit_count() % size != 0
                    if component.bit_count() == size:
                        area_only = not shape_capitol(component)[0]
                    add_component_cut(model, is_area, cap, component, size, caps, area_only)
                    counts['geometry_cuts'] += 1
                    cuts += 1
        except GeometryTimeout:
            counts['geometry_timeouts'] += 1
            break
        if progress:
            progress({'phase':'geometry', 'assignments':counts['area_assignments'],
                      'new_cuts':cuts, 'total_cuts':counts['geometry_cuts']})
        if not cuts:
            candidate = materialize(state, chosen)
            if not candidate.validate_puzzle()['puzzle_valid']:
                raise AssertionError('Area/geometry model disagrees with independent validator.')
            solution = candidate.to_dict(); result_status = 'verified_solution'
            break
    return {'status':result_status, 'solution':solution, 'statistics':dict(counts),
            'elapsed_seconds':round(time.monotonic()-started,3), 'max_area':max_area,
            'scope':'Experimental area-first exact constraints; no candidate sampling. '
                    'Infeasibility is conditional on max_area; time_limit proves nothing.',
            'last_relaxed_assignment':last_assignment}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=120)
    parser.add_argument('--max-area', type=int, default=N)
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--output', default='solver-area-report.json')
    args = parser.parse_args()
    report = solve_area(new_workspace().saved, args.seconds, args.max_area, args.workers,
                        progress=lambda item: print(json.dumps(item), flush=True))
    Path(args.output).write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('solution','last_relaxed_assignment')}, indent=2))
