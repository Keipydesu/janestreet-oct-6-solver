"""Prove upper bounds on the largest state in the original 11x11 puzzle.

Searches states occupying more than half the board. Such a state is unique,
so all cells with its area must belong to it. Numeric constraints are a
relaxation; symmetry is necessary and invalid remaining geometry learns cuts.
Only CP upper bounds or proved infeasibility tighten the reported bound.
Requires the optional OR-Tools environment in requirements-cp.txt.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import time

from area_solver import (build_area_model, components, partition_component,
                         add_component_cut, shape_capitol, GeometryTimeout)
from candidate_search import neighbors_for_size
from model import SIZE
from solver import N, materialize
from starting_grid import new_workspace


def symmetry_mappings(size, minimum_area):
    """All reflection / half-turn maps with room for the hypothesized state."""
    transforms = []
    for k in range(2*size-1):
        transforms.extend((lambda r,c,k=k:(k-r,c),
                           lambda r,c,k=k:(r,k-c),
                           lambda r,c,k=k:(k-c,k-r)))
    for k in range(1-size,size):
        transforms.append(lambda r,c,k=k:(c+k,r-k))
    for kr in range(2*size-1):
        for kc in range(2*size-1):
            transforms.append(lambda r,c,kr=kr,kc=kc:(kr-r,kc-c))
    for transform in transforms:
        mapping = []
        for r in range(size):
            for c in range(size):
                rr,cc = transform(r,c)
                mapping.append(rr*size+cc if 0 <= rr < size and 0 <= cc < size else None)
        if sum(j is not None for j in mapping) >= minimum_area:
            yield mapping


def geometric_upper_bounds(state, seconds=5):
    """Solve each possible large-state symmetry separately using escape clues.

    Every positive clue below the state area forces a missing cell in its
    closed neighborhood. This relaxation can only overestimate state size.
    Per-symmetry timeout bounds retain the full overlap capacity if needed.
    """
    from ortools.sat.python import cp_model
    size = state.size; n = size*size; minimum = n//2+1
    facts = state.deductions()
    if not facts['available'] or facts['contradictions']:
        raise ValueError('Invalid or contradictory starting clues.')
    model = cp_model.CpModel()
    member = [model.new_bool_var(f'm{i}') for i in range(n)]
    largest = model.new_int_var(minimum,n,'largest')
    model.add(sum(member) == largest)
    neighbors = neighbors_for_size(size)
    clues = {r*size+c:cell.starting_number for r,row in enumerate(state.grid)
             for c,cell in enumerate(row) if cell.starting_number is not None}
    for i,value in clues.items():
        if value <= 0:
            continue
        larger = model.new_bool_var(f'exceeds_clue{i}')
        model.add(largest > value).only_enforce_if(larger)
        model.add(largest <= value).only_enforce_if(~larger)
        model.add(sum(member[j] for j in (i,*neighbors[i])) <= len(neighbors[i])).only_enforce_if(larger)
    for r,c in facts['forced_singletons']:
        model.add(member[r*size+c] == 0)
    for group in facts['one_clues']:
        cells = [r*size+c for r,c in group['candidates']]
        model.add(sum(member[i] for i in cells) < len(cells))
    zeros = [i for i,value in clues.items() if value == 0]
    model.add(sum(member[i] for i in zeros) <= 1)
    model.maximize(largest)
    deadline = time.monotonic()+seconds
    best_relaxed = minimum-1
    records = []
    for mapping in symmetry_mappings(size,minimum):
        bound = sum(j is not None for j in mapping)
        status = 'overlap_capacity'
        if bound > best_relaxed and time.monotonic() < deadline:
            trial = model.clone()
            for i,j in enumerate(mapping):
                if j is None:
                    trial.add(member[i] == 0)
                elif i < j:
                    trial.add(member[i] == member[j])
            fixed = [member[i] for i,j in enumerate(mapping) if i == j]
            for i in zeros:
                if mapping[i] != i:
                    trial.add(member[i] == 0)
                trial.add(sum(fixed) == 1).only_enforce_if(member[i])
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = max(.001,min(.3,deadline-time.monotonic()))
            solver.parameters.num_search_workers = 1
            outcome = solver.solve(trial)
            status = solver.status_name(outcome)
            if outcome == cp_model.MODEL_INVALID:
                raise RuntimeError(trial.validate())
            if outcome == cp_model.INFEASIBLE:
                bound = minimum-1
            elif solver.best_objective_bound >= minimum:
                bound = min(bound,math.ceil(solver.best_objective_bound))
            if outcome in (cp_model.OPTIMAL,cp_model.FEASIBLE):
                best_relaxed = max(best_relaxed,round(solver.objective_value))
        records.append({'mapping':mapping,'upper_bound':bound,'status':status})
    return max([minimum-1]+[r['upper_bound'] for r in records]), records


def add_large_state_symmetry(model, area, capitols, largest, size=SIZE, bounds=None):
    """For a state larger than half the board, require at least one symmetry.

    This does not assume a particular axis, connectivity, or sufficient
    capitol geometry. Full geometry is checked separately before any witness
    is accepted. Every actual state symmetry includes a reflection/half-turn.
    """
    n = size*size
    member = [model.new_bool_var(f'largest_member{i}') for i in range(n)]
    for i in range(n):
        model.add(area[i] == largest).only_enforce_if(member[i])
        model.add(area[i] != largest).only_enforce_if(~member[i])
    model.add(sum(member) == largest)
    cap_members = []
    for i in range(n):
        flag = model.new_bool_var(f'largest_cap{i}')
        model.add(flag <= member[i]); model.add(flag <= capitols[i])
        model.add(flag >= member[i]+capitols[i]-1)
        cap_members.append(flag)
    has_capitol = model.new_bool_var("largest_has_capitol")
    model.add(sum(cap_members) == has_capitol)
    choices = []
    for number, mapping in enumerate(symmetry_mappings(size, n//2+1)):
        bound = bounds[number]['upper_bound'] if bounds is not None else sum(j is not None for j in mapping)
        if bound <= n//2:
            continue
        selected = model.new_bool_var(f'largest_symmetry{number}')
        choices.append(selected)
        model.add(largest <= bound).only_enforce_if(selected)
        fixed = []
        for i,j in enumerate(mapping):
            if j is None:
                model.add(member[i] == 0).only_enforce_if(selected)
            elif i < j:
                model.add(member[i] == member[j]).only_enforce_if(selected)
            if j == i:
                fixed.append(member[i])
            else:
                # Any actual capitol must be fixed by the selected symmetry.
                model.add(cap_members[i] == 0).only_enforce_if(selected)
        # A capitol requires exactly one fixed square for this symmetry.
        model.add(sum(fixed) == 1).only_enforce_if([selected, has_capitol])
    model.add_bool_or(choices)
    return member


def bound_largest_state(state, seconds=60, workers=1, progress=None):
    """Return a safe upper bound, even when full geometry search times out.

    No claim about states of size <= N//2 is needed if the larger-state
    hypothesis is disproved. A relaxed objective value is never a solution.
    """
    if state.size != SIZE:
        raise ValueError('This bound analysis currently supports the original 11x11 board only.')
    if not math.isfinite(seconds) or seconds < 0 or type(workers) is not int or workers < 1:
        raise ValueError('Use a finite nonnegative time budget and positive worker count.')
    from ortools.sat.python import cp_model
    started = time.monotonic(); deadline = started+seconds
    upper = N
    witness = None
    counts = Counter()
    status = 'time_limit'
    minimum = N//2+1
    geometric_bound = N
    if seconds > 0:
        geometric_bound, symmetry_bounds = geometric_upper_bounds(state,min(5,seconds*.1))
        upper = geometric_bound
        if progress:
            progress({'phase':'geometric_bound','proven_upper_bound':upper})
        model,area,distance,cap,is_area = build_area_model(state,template_sizes=(2,3,4))
        largest = model.new_int_var(minimum,N,'largest_state_area')
        model.add_max_equality(largest,area)
        model.add(largest <= upper)
        add_large_state_symmetry(model,area,cap,largest,bounds=symmetry_bounds)
        # Capitols of each area must fit that area's own inventory of states.
        for size in range(1,N+1,2):
            flags = []
            for i in range(N):
                flag = model.new_bool_var(f'cap_at_area{size}_{i}')
                model.add(flag <= cap[i]); model.add(flag <= is_area[i][size])
                model.add(flag >= cap[i]+is_area[i][size]-1)
                flags.append(flag)
            model.add(size*sum(flags) <= sum(f[size] for f in is_area))
        model.maximize(largest)
        while time.monotonic() < deadline:
            solver = cp_model.CpSolver()
            # Leave time to inspect a returned assignment and learn geometry cuts.
            solver.parameters.max_time_in_seconds = max(.001,(deadline-time.monotonic())*.9)
            solver.parameters.num_search_workers = workers
            outcome = solver.solve(model)
            counts['cp_calls'] += 1
            if outcome == cp_model.MODEL_INVALID:
                raise RuntimeError(model.validate())
            if outcome == cp_model.INFEASIBLE:
                upper = minimum-1
                status = 'proved_no_state_over_half_board'
                break
            # UNKNOWN before search can expose a default zero, not a bound.
            # Round upward conservatively, never round a bound below its value.
            raw_bound = solver.best_objective_bound
            if math.isfinite(raw_bound) and raw_bound >= minimum:
                upper = min(upper,math.ceil(raw_bound))
                model.add(largest <= upper)
            if progress:
                progress({'phase':'upper_bound','proven_upper_bound':upper,
                          'cp_status':solver.status_name(outcome)})
            if outcome not in (cp_model.OPTIMAL,cp_model.FEASIBLE):
                # Restarting identical UNKNOWN searches does not accumulate work.
                break
            counts['relaxed_assignments'] += 1
            values = [solver.value(a) for a in area]
            caps = {i for i,c in enumerate(cap) if solver.boolean_value(c)}
            chosen = []; cuts = 0
            try:
                for size in sorted(set(values),reverse=True):
                    mask = sum(1<<i for i,value in enumerate(values) if value==size)
                    for component in components(mask):
                        part = partition_component(component,size,caps,deadline)
                        if part is not None:
                            chosen.extend(part)
                        else:
                            area_only = component.bit_count()%size != 0
                            if component.bit_count()==size:
                                area_only = not shape_capitol(component)[0]
                            add_component_cut(model,is_area,cap,component,size,caps,area_only)
                            cuts += 1
                counts['geometry_cuts'] += cuts
            except GeometryTimeout:
                counts['geometry_timeouts'] += 1
                break
            if not cuts:
                candidate = materialize(state,chosen)
                if not candidate.validate_puzzle()['puzzle_valid']:
                    raise AssertionError('Bound witness failed independent validation.')
                witness = candidate.to_dict()
                status = 'exact_maximum' if max(values)==upper else 'bounded_with_verified_witness'
                break
            if progress:
                progress({'phase':'geometry','new_cuts':cuts,'proven_upper_bound':upper})
    return {'status':status,'proven_upper_bound':upper,
            'excluded_areas':list(range(upper+1,N+1)),
            'geometric_upper_bound':geometric_bound,
            'verified_witness':witness,'statistics':dict(counts),
            'elapsed_seconds':round(time.monotonic()-started,3),
            'scope':'Upper bound on state area in every valid finite-distance completion of these clues. '
                    'Exact numeric distances and inventory; large-state symmetry; small templates; '
                    'remaining connectivity and symmetry checked with sound geometry cuts. '
                    'A timeout does not make the bound exact or prove the puzzle impossible.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=float,default=60)
    parser.add_argument('--workers',type=int,default=1)
    parser.add_argument('--output',default='solver-largest-state-report.json')
    args = parser.parse_args()
    report = bound_largest_state(new_workspace().saved,args.seconds,args.workers,
                                progress=lambda item:print(json.dumps(item),flush=True))
    Path(args.output).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='verified_witness'},indent=2))
