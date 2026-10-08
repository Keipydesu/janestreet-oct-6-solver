"""Clue-only counts of distinct locally compatible states at every square."""
import time

from candidate_search import indices, search_candidates
from model import GridState
from solver import forbidden_capitols


def state_count_heatmap(state, max_area=None, seconds=8):
    size = state.size
    total = size * size
    if max_area is None:
        max_area = min(98, total)
    if type(max_area) is not int or not 1 <= max_area <= total:
        raise ValueError(f'Maximum area must be from 1 to {total}.')
    started = time.monotonic()
    deadline = started + max(0, seconds)
    # Paint and manual stars must not affect a starting-clue analysis.
    clues = GridState(size)
    for r, row in enumerate(state.grid):
        for c, cell in enumerate(row):
            clues.grid[r][c].starting_number = cell.starting_number
            clues.grid[r][c].capital_required = cell.starting_number == 0
            clues.grid[r][c].is_capital = cell.starting_number == 0
    deductions = clues.deductions()
    if not deductions['available'] or deductions['contradictions']:
        raise ValueError('Resolve invalid or contradictory starting clues before counting states.')
    forbidden = forbidden_capitols(clues, max_area, deductions)
    forced = {r*size+c for r,c in deductions['forced_singletons']}
    roots = sorted(range(total), key=lambda i: (i not in forced, i))
    seen = set()
    counts = [0] * total
    complete = [False] * total
    searched = [False] * total
    for position, root in enumerate(roots):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        result = search_candidates(clues, *divmod(root, size), max_area=max_area,
                                   time_limit=remaining/(total-position),
                                   node_limit=100000, preview_limit=None)
        searched[root] = True
        complete[root] = result['complete_within_limit']
        for candidate in result['survivors']:
            cap = candidate['capitol']
            if cap is not None and cap[0]*size+cap[1] in forbidden:
                continue
            mask = sum(1 << (r*size+c) for r,c in candidate['cells'])
            if mask in seen:
                continue
            seen.add(mask)
            for i in indices(mask):
                counts[i] += 1
    def grid(values):
        return [values[r*size:(r+1)*size] for r in range(size)]
    return {
        'heatmap': grid(counts), 'complete_cells': grid(complete),
        'searched_cells': grid(searched), 'complete_within_limit': all(complete),
        'max_area': max_area, 'unique_states': len(seen),
        'roots_searched': sum(searched), 'complete_cell_count': sum(complete),
        'elapsed_seconds': round(time.monotonic()-started, 3),
        'scope': 'Distinct connected symmetric states passing local starting-clue checks '
                 'and clue-based capitol exclusions, within the area limit. '
                 'Not proven to occur in a complete solution. Paint and manual stars ignored. '
                 'Incomplete counts are lower bounds on this candidate set; zero found '
                 'does not prove that no state is possible.'
    }
