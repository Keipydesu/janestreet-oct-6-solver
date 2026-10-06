"""Pure Python puzzle model. Coordinates are zero-based: grid[row][col]."""
from collections import deque
from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import re
from pathlib import Path

SIZE = 11
FIELDS = ('starting_number', 'region_color', 'user_number', 'is_capital', 'capital_required')
LAYERS = dict(starting='starting_number', regions='region_color', numbers='user_number', capitals='is_capital')

@dataclass
class Cell:
    starting_number: int | float | None = None
    region_color: str | None = None
    user_number: int | float | None = None
    is_capital: bool = False
    capital_required: bool = False

class GridState:
    def __init__(self):
        self.grid = [[Cell() for _ in range(SIZE)] for _ in range(SIZE)]

    def to_dict(self):
        return [[asdict(cell) for cell in row] for row in self.grid]

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, list) or len(data) != SIZE:
            raise ValueError('Expected 11 rows.')
        state = cls()
        for r, row in enumerate(data):
            if not isinstance(row, list) or len(row) != SIZE:
                raise ValueError('Expected 11 cells per row.')
            for c, cell in enumerate(row):
                if isinstance(cell, dict):
                    cell = dict(cell)
                    cell.setdefault('capital_required', False)
                if not isinstance(cell, dict) or set(cell) != set(FIELDS):
                    raise ValueError('Invalid cell fields.')
                for field, value in cell.items():
                    validate_value(field, value)
                if cell['capital_required'] and not cell['is_capital']:
                    raise ValueError('Required capitals cannot be unmarked.')
                state.grid[r][c] = Cell(**cell)
        return state

    def connected_regions(self):
        """Same-color components with edge adjacency; diagonal contact doesn't count."""
        seen, regions = set(), []
        for r in range(SIZE):
            for c in range(SIZE):
                color = self.grid[r][c].region_color
                if color is None or (r, c) in seen:
                    continue
                queue, cells = deque([(r, c)]), []
                seen.add((r, c))
                while queue:
                    rr, cc = queue.popleft()
                    cells.append((rr, cc))
                    for nr, nc in ((rr-1, cc), (rr+1, cc), (rr, cc-1), (rr, cc+1)):
                        if 0 <= nr < SIZE and 0 <= nc < SIZE and (nr, nc) not in seen and self.grid[nr][nc].region_color == color:
                            seen.add((nr, nc))
                            queue.append((nr, nc))
                regions.append({'color': color, 'area': len(cells), 'cells': cells})
        return regions

    @staticmethod
    def shape_symmetry(cells):
        """Test a region's occupied unit squares, allowing translation after a transform.

        Rotations are non-identity counterclockwise angles in degrees. Reflection
        axes pass through the shape's center: horizontal, vertical, and the two
        diagonals. Coordinates are (row, column), with rows increasing downward.
        These are all possible nontrivial symmetries of a finite square-cell shape.
        Numbers, colors, and capital markers are not part of this shape test.
        """
        cells = set(tuple(cell) for cell in cells)
        if not cells:
            raise ValueError('A shape must contain at least one cell.')

        def normalize(points):
            points = set(points)
            r0 = min(r for r, c in points)
            c0 = min(c for r, c in points)
            return frozenset((r-r0, c-c0) for r, c in points)

        original = normalize(cells)
        rotations = {
            90: lambda r, c: (-c, r),
            180: lambda r, c: (-r, -c),
            270: lambda r, c: (c, -r),
        }
        reflections = {
            'horizontal': lambda r, c: (-r, c),
            'vertical': lambda r, c: (r, -c),
            'main_diagonal': lambda r, c: (c, r),
            'anti_diagonal': lambda r, c: (-c, -r),
        }
        angles = [angle for angle, transform in rotations.items()
                  if normalize(transform(r, c) for r, c in cells) == original]
        axes = [axis for axis, transform in reflections.items()
                if normalize(transform(r, c) for r, c in cells) == original]
        operations = []
        base_r = min(r for r,c in cells)
        base_c = min(c for r,c in cells)
        for kind, transforms, names in (('rotation', rotations, angles), ('reflection', reflections, axes)):
            for name in names:
                transform = transforms[name]
                moved = {cell: transform(*cell) for cell in cells}
                dr = base_r - min(r for r,c in moved.values())
                dc = base_c - min(c for r,c in moved.values())
                fixed = sorted([list(cell) for cell,(r,c) in moved.items() if cell == (r+dr,c+dc)])
                operations.append({'kind':kind, 'name':name, 'fixed_cells':fixed, 'fixed_count':len(fixed)})
        return {'rotations': angles, 'reflections': axes,
                'rotationally_symmetric': bool(angles),
                'reflectionally_symmetric': bool(axes),
                'symmetric': bool(angles or axes), 'operations': operations}

    def region_symmetries(self):
        """Return color, area, coordinates and shape symmetry for each component."""
        return [dict(region, symmetry=self.shape_symmetry(region['cells']))
                for region in self.connected_regions()]

    def validate_regions(self):
        """Check state symmetry and the universal fixed-square capitol rule.

        No capitol is allowed for an otherwise symmetric state. A square is
        fixed when a symmetry maps that entire square to itself (not merely
        when an axis passes through it). All nonidentity symmetries are tested.
        Manual markers are checked separately from geometrically derived truth.
        """
        regions = []
        heatmap = [[None for _ in range(SIZE)] for _ in range(SIZE)]
        for region in self.connected_regions():
            symmetry = self.shape_symmetry(region['cells'])
            operations = symmetry['operations']
            unique_fixed = bool(operations) and all(op['fixed_count'] == 1 for op in operations)
            capitol = operations[0]['fixed_cells'][0] if unique_fixed else None
            if capitol is not None and any(op['fixed_cells'][0] != capitol for op in operations):
                capitol = None
            marked = [[r,c] for r,c in region['cells'] if self.grid[r][c].is_capital]
            incorrect = [cell for cell in marked if cell != capitol]
            required = [[r,c] for r,c in region['cells'] if self.grid[r][c].capital_required or self.grid[r][c].starting_number == 0]
            required_conflicts = [cell for cell in required if cell != capitol]
            valid = symmetry['symmetric']
            issues = []
            if not valid: issues.append('No nontrivial symmetry: not a valid state.')
            if incorrect: issues.append('A marked capital is not the capitol derived from symmetry.')
            if required_conflicts: issues.append('A required zero-clue capital is not the derived capitol.')
            if not valid: status = 'invalid_shape'
            elif incorrect or required_conflicts: status = 'capital_conflict'
            else: status = 'valid_with_capitol' if capitol is not None else 'valid_without_capitol'
            result = dict(region, symmetry=symmetry, valid_state=valid, capitol=capitol,
                          marked_capitals=marked, incorrect_markers=incorrect,
                          required_conflicts=required_conflicts,
                          missing_marker=capitol is not None and capitol not in marked,
                          status=status, issues=issues)
            regions.append(result)
            code = 0 if status in ('invalid_shape','capital_conflict') else (2 if capitol is not None else 1)
            for r,c in region['cells']: heatmap[r][c] = code
        uncolored = sum(cell.region_color is None for row in self.grid for cell in row)
        return {'regions':regions, 'heatmap':heatmap, 'uncolored_count':uncolored,
                'complete':uncolored == 0,
                'valid_state_count':sum(r['valid_state'] for r in regions),
                'invalid_state_count':sum(not r['valid_state'] for r in regions),
                'capital_conflict_count':sum(bool(r['incorrect_markers'] or r['required_conflicts']) for r in regions),
                'derived_capitols':[r['capitol'] for r in regions if r['capitol'] is not None],
                'partition_valid': None if uncolored else all(r['valid_state'] for r in regions)}

    def validate_puzzle(self):
        """Region report plus numbered-clue checks using the derived capitols."""
        report = self.validate_regions()
        costs = self.smart_heatmap(use_derived_capitals=True)
        report['clue_checks'] = costs['checks']
        report['puzzle_valid'] = None if not report['complete'] else (
            report['partition_valid'] and all(not r['required_conflicts'] for r in report['regions'])
            and all(c['actual'] == c['expected'] for c in costs['checks']))
        return report

    def region_areas(self):
        """11×11 numeric array; blank cells have area zero."""
        result = [[0] * SIZE for _ in range(SIZE)]
        for region in self.connected_regions():
            for r, c in region['cells']:
                result[r][c] = region['area']
        return result

    def movement_heatmap(self, row, col, within_region=False):
        """Independent 11×11 array of maximum remaining movement budget.

        Each orthogonal step costs one. None means unreachable; zero means
        reachable with no budget left. The source costs zero. Uses shortest
        paths; this is reachability within a budget, not exact-length paths.
        Optional region restriction uses edge-connected cells of the source
        color, and rejects an uncolored source. Other clues are not obstacles.
        """
        if any(type(x) is not int or not 0 <= x < SIZE for x in (row, col)):
            raise ValueError('Invalid source coordinate.')
        if type(within_region) is not bool:
            raise ValueError('Region restriction must be true or false.')
        source = self.grid[row][col]
        budget = source.starting_number
        if budget is None or budget < 0:
            raise ValueError('Select a starting clue with a nonnegative value.')
        if within_region and source.region_color is None:
            raise ValueError('Color the source region before restricting movement to it.')
        heatmap = [[None for _ in range(SIZE)] for _ in range(SIZE)]
        heatmap[row][col] = budget
        queue = deque([(row, col)])
        while queue:
            r, c = queue.popleft()
            remaining = heatmap[r][c] - 1
            if remaining < 0:
                continue
            for nr, nc in ((r-1,c), (r+1,c), (r,c-1), (r,c+1)):
                if not (0 <= nr < SIZE and 0 <= nc < SIZE) or heatmap[nr][nc] is not None:
                    continue
                if within_region and self.grid[nr][nc].region_color != source.region_color:
                    continue
                heatmap[nr][nc] = remaining
                queue.append((nr,nc))
        return heatmap

    def weighted_movement_heatmap(self, row, col, within_region=False):
        """Budget remaining with current state-size travel costs.

        Unknown squares use size 1, the minimum possible area. Painted connected
        components use their current sizes. These are optimistic budgets if those
        components are retained and expanded, not proof of valid puzzle routes.
        """
        import heapq
        if any(type(x) is not int or not 0 <= x < SIZE for x in (row,col)):
            raise ValueError('Invalid source coordinate.')
        budget=self.grid[row][col].starting_number
        if budget is None or budget < 0:
            raise ValueError('Select a nonnegative starting clue.')
        if type(within_region) is not bool:
            raise ValueError('Region restriction must be true or false.')
        source_color=self.grid[row][col].region_color
        if within_region and source_color is None:
            raise ValueError('Color the source region before restricting movement to it.')
        sizes=self.region_areas()
        result=[[None for _ in range(SIZE)] for _ in range(SIZE)]
        result[row][col]=budget
        queue=[(-budget,row,col)]
        while queue:
            negative,r,c=heapq.heappop(queue)
            remaining=-negative
            if result[r][c] != remaining: continue
            for nr,nc in ((r-1,c),(r+1,c),(r,c-1),(r,c+1)):
                if not (0 <= nr < SIZE and 0 <= nc < SIZE): continue
                if within_region and self.grid[nr][nc].region_color != source_color: continue
                # Same-state endpoints have identical areas, so min handles both rules.
                cost=min(sizes[r][c] or 1,sizes[nr][nc] or 1)
                left=remaining-cost
                if left >= 0 and (result[nr][nc] is None or left > result[nr][nc]):
                    result[nr][nc]=left
                    heapq.heappush(queue,(-left,nr,nc))
        return result

    def deductions(self):
        """Sound, clue-only deductions. Paint and manual markers are hypotheses.

        This is a deliberately limited rule engine, not exhaustive shape search.
        Results are necessary conditions for any solution to the supplied clues.
        """
        def neighbors(r,c):
            return [(rr,cc) for rr,cc in ((r-1,c),(r+1,c),(r,c-1),(r,c+1))
                    if 0 <= rr < SIZE and 0 <= cc < SIZE]
        def label(r,c): return f'R{r+1} C{c+1}'
        notes=[[[] for _ in range(SIZE)] for _ in range(SIZE)]
        bounds=[[1 for _ in range(SIZE)] for _ in range(SIZE)]
        clues={(r,c):cell.starting_number for r,row in enumerate(self.grid) for c,cell in enumerate(row) if cell.starting_number is not None}
        invalid=[{'cell':list(p),'reason':'Travel-cost clues must be nonnegative integers.'} for p,n in clues.items() if n < 0 or n != int(n)]
        if invalid:
            return {'heatmap':[[None]*SIZE for _ in range(SIZE)],'notes':notes,'minimum_state_sizes':bounds,
                    'one_clues':[],'forced_singletons':[],'candidate_singletons':[],'required_capitals':[],
                    'contradictions':invalid,'available':False}
        def bound(p,value,reason):
            value=int(value)
            if value>bounds[p[0]][p[1]]:
                bounds[p[0]][p[1]]=value
                notes[p[0]][p[1]].append(reason)
        for (r,c),n in clues.items():
            if n>0:
                bound((r,c),2,'A positive clue cannot be a singleton: a singleton is its own capitol and has cost 0.')
            else:
                notes[r][c].append('Clue 0 forces this square to be a capitol. Its state has odd area; singleton is not implied.')
            for q in neighbors(r,c):
                if q in clues:
                    delta=abs(n-clues[q])
                    for p0 in ((r,c),q):
                        bound(p0,delta,f'Adjacent clues at {label(r,c)} and {label(*q)} differ by {int(delta)}. Their connecting edge costs at least that much, so both state areas are at least {int(delta)}.')
        excluded={}
        for r in range(SIZE):
            for c in range(SIZE):
                reasons=[]
                if clues.get((r,c),0)>0: reasons.append('A positive clue cannot be a singleton capitol.')
                for q in neighbors(r,c):
                    if clues.get(q,0)>1:
                        reasons.append(f'A singleton here would give neighboring clue {label(*q)} = {clues[q]} a route costing 1, which is too cheap.')
                if bounds[r][c]>1: reasons.append(f'This square must belong to a state of at least {bounds[r][c]} squares.')
                if reasons: excluded[(r,c)]=reasons
        groups=[];forced=set();candidates=set();contradictions=[]
        for p0,n in clues.items():
            if n!=1: continue
            possible=[q for q in neighbors(*p0) if q not in excluded]
            eliminated=[{'cell':list(q),'reasons':excluded[q]} for q in neighbors(*p0) if q in excluded]
            group={'clue':list(p0),'candidates':[list(q) for q in possible],'eliminated':eliminated,'forced':list(possible[0]) if len(possible)==1 else None}
            groups.append(group);candidates.update(possible)
            notes[p0[0]][p0[1]].append('Clue 1 must be adjacent to a singleton capitol: its only possible cheapest route is one step costing 1.')
            notes[p0[0]][p0[1]].append('Remaining singleton neighbors: '+(', '.join(label(*q) for q in possible) or 'NONE — contradiction.'))
            for q in neighbors(*p0):
                notes[q[0]][q[1]].extend(excluded[q] if q in excluded else [f'Possible singleton capitol for clue 1 at {label(*p0)}; this is not yet forced.'])
            if len(possible)==1:
                forced.add(possible[0])
                notes[possible[0][0]][possible[0][1]].append(f'FORCED SINGLETON: the other neighbors of clue 1 at {label(*p0)} are excluded.')
            if not possible: contradictions.append({'cell':list(p0),'reason':'Clue 1 has no possible adjacent singleton capitol.'})
        # A neighbor of a forced singleton has distance at most 1. Apply the
        # adjacent-distance inequality to any numbered neighbor of that square.
        for sr,sc in forced:
            for q in neighbors(sr,sc):
                notes[q[0]][q[1]].append(f'Cost to a capitol is at most 1: adjacent to forced singleton {label(sr,sc)}.')
                for p0 in neighbors(*q):
                    n=clues.get(p0)
                    if n is not None and n>1:
                        reason=f'Forced singleton {label(sr,sc)} gives {label(*q)} distance at most 1. Next to clue {label(*p0)} = {n}, the edge must cost at least {int(n-1)}; both endpoint states have area at least {int(n-1)}.'
                        bound(q,n-1,reason);bound(p0,n-1,reason)
        # Known capitols have odd-area states; round any area lower bound up.
        for p0,n in clues.items():
            if n==0 and bounds[p0[0]][p0[1]]%2==0:
                bound(p0,bounds[p0[0]][p0[1]]+1,'A capitol-bearing state has odd area; round the size lower bound up to the next odd number.')
        heat=[[None for _ in range(SIZE)] for _ in range(SIZE)]
        for r in range(SIZE):
            for c in range(SIZE):
                if bounds[r][c]>1: heat[r][c]=3
                if (r,c) in candidates: heat[r][c]=2
                if clues.get((r,c))==0: heat[r][c]=4
                if (r,c) in forced: heat[r][c]=1
                if bounds[r][c]>SIZE*SIZE:
                    contradictions.append({'cell':[r,c],'reason':'Required state area exceeds the whole board.'})
        for entry in contradictions: heat[entry['cell'][0]][entry['cell'][1]]=5
        return {'heatmap':heat,'notes':notes,'minimum_state_sizes':bounds,'one_clues':groups,
                'forced_singletons':[list(p) for p in sorted(forced)],
                'candidate_singletons':[list(p) for p in sorted(candidates-forced)],
                'required_capitals':[list(p) for p,n in clues.items() if n==0],
                'contradictions':contradictions,'available':True}

    def all_clues_heatmap(self, aggregation='count', use_region_sizes=True):
        """Combine independent unit-step movement maps for every starting clue.

        count: number of clues that can reach each square (including origins).
        min_remaining: smallest nonnegative remaining budget, or None if none.
        Per-source arrays are also returned for inspection and further math.
        """
        if aggregation not in ('count', 'min_remaining'):
            raise ValueError('Unknown heatmap aggregation.')
        heatmap = [[0 if aggregation == 'count' else None for _ in range(SIZE)] for _ in range(SIZE)]
        sources = []
        skipped = []
        for r, row in enumerate(self.grid):
            for c, cell in enumerate(row):
                if cell.starting_number is None:
                    continue
                if cell.starting_number < 0:
                    skipped.append([r,c])
                    continue
                values = self.weighted_movement_heatmap(r,c) if use_region_sizes else self.movement_heatmap(r,c)
                sources.append({'source': [r,c], 'budget': cell.starting_number, 'heatmap': values})
                for rr in range(SIZE):
                    for cc in range(SIZE):
                        value = values[rr][cc]
                        if value is None:
                            continue
                        if aggregation == 'count':
                            heatmap[rr][cc] += 1
                        elif heatmap[rr][cc] is None or value < heatmap[rr][cc]:
                            heatmap[rr][cc] = value
        return {'heatmap': heatmap, 'aggregation': aggregation,
                'sources': sources, 'skipped_sources': skipped, 'use_region_sizes':use_region_sizes,
                'uncolored_count':sum(cell.region_color is None for row in self.grid for cell in row)}

    def smart_heatmap(self, use_derived_capitals=False):
        """Multi-source Dijkstra: minimum weighted cost to ANY marked capital.

        A state is one edge-connected color component. Within-state edge cost
        equals its area; crossing an edge between states costs min(their areas).
        Uncolored squares are unknown, not unit-size states. They cannot be
        traversed. Costs on an incomplete map are provisional, not bounds on
        the eventual solution. Capital cells themselves always have cost zero.
        """
        import heapq
        if type(use_derived_capitals) is not bool:
            raise ValueError('Derived-capital mode must be true or false.')
        validation = self.validate_regions() if use_derived_capitals else None
        origins = set(tuple(cell) for cell in validation['derived_capitols']) if validation else {(r,c) for r,row in enumerate(self.grid) for c,cell in enumerate(row) if cell.is_capital}
        regions = self.connected_regions()
        ids = [[None for _ in range(SIZE)] for _ in range(SIZE)]
        sizes = [[None for _ in range(SIZE)] for _ in range(SIZE)]
        for index, region in enumerate(regions):
            region['capitals'] = [[r,c] for r,c in region['cells'] if (r,c) in origins]
            for r,c in region['cells']:
                ids[r][c] = index
                sizes[r][c] = region['area']
        costs = [[None for _ in range(SIZE)] for _ in range(SIZE)]
        nearest = [[None for _ in range(SIZE)] for _ in range(SIZE)]
        queue = []
        capitals = []
        for r, row in enumerate(self.grid):
            for c, cell in enumerate(row):
                if (r,c) in origins:
                    capitals.append([r,c])
                    costs[r][c] = 0
                    nearest[r][c] = [r,c]
                    heapq.heappush(queue, (0,r,c))
        while queue:
            cost,r,c = heapq.heappop(queue)
            if costs[r][c] != cost or sizes[r][c] is None:
                continue
            for nr,nc in ((r-1,c),(r+1,c),(r,c-1),(r,c+1)):
                if not (0 <= nr < SIZE and 0 <= nc < SIZE) or sizes[nr][nc] is None:
                    continue
                edge = sizes[r][c] if ids[r][c] == ids[nr][nc] else min(sizes[r][c],sizes[nr][nc])
                new_cost = cost + edge
                if costs[nr][nc] is None or new_cost < costs[nr][nc]:
                    costs[nr][nc] = new_cost
                    nearest[nr][nc] = nearest[r][c][:]
                    heapq.heappush(queue,(new_cost,nr,nc))
        uncolored = sum(value is None for row in sizes for value in row)
        complete = uncolored == 0 and bool(capitals)
        checks = []
        for r,row in enumerate(self.grid):
            for c,cell in enumerate(row):
                if cell.starting_number is None:
                    continue
                actual = costs[r][c]
                status = 'unknown' if actual is None else ('match' if actual == cell.starting_number else 'mismatch')
                if not complete and status != 'unknown':
                    status = 'provisional_' + status
                checks.append({'cell':[r,c], 'expected':cell.starting_number, 'actual':actual,
                               'difference':None if actual is None else actual-cell.starting_number,
                               'status':status, 'nearest_capital':nearest[r][c]})
        return {'heatmap':costs, 'nearest_capitals':nearest, 'state_sizes':sizes,
                'state_ids':ids, 'regions':regions, 'capitals':capitals,
                'uncolored_count':uncolored, 'complete':complete, 'checks':checks,
                'states_without_capitals':sum(not region['capitals'] for region in regions),
                'capital_mode':'derived' if use_derived_capitals else 'marked',
                'invalid_state_count':validation['invalid_state_count'] if validation else None}

    def candidate_states(self, row, col, max_area=7, **limits):
        """Enumerate locally compatible symmetric states; see completeness metadata."""
        from candidate_search import search_candidates
        return search_candidates(self,row,col,max_area,**limits)

    def numbers(self, field='user_number', empty=0):
        if field not in ('starting_number', 'user_number'):
            raise ValueError('Choose a numeric field.')
        return [[getattr(cell, field) if getattr(cell, field) is not None else empty for cell in row] for row in self.grid]

def validate_value(field, value):
    if field in ('starting_number', 'user_number'):
        import math
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e15):
            raise ValueError('Numbers must be finite and between -1e15 and 1e15.')
    elif field == 'region_color':
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value)):
            raise ValueError('Choose a hex color or erase the color.')
    elif field in ('is_capital', 'capital_required'):
        if type(value) is not bool:
            raise ValueError('Capital must be true or false.')
    else:
        raise ValueError('Unknown cell field.')

class History:
    def __init__(self, initial):
        self.states = [deepcopy(initial)]
        self.labels = ['Initial state']
        self.cursor = 0

    def record(self, state, label):
        if state == self.states[self.cursor]:
            return
        self.states = self.states[:self.cursor + 1] + [deepcopy(state)]
        self.labels = self.labels[:self.cursor + 1] + [label]
        self.cursor += 1

    def view(self):
        return {'labels': self.labels, 'cursor': self.cursor, 'can_undo': self.cursor > 0, 'can_redo': self.cursor < len(self.states)-1}

class Workspace:
    def __init__(self, state=None):
        self.saved = state or GridState()
        self.experimental = deepcopy(self.saved)
        self.histories = {layer: History(self._snapshot(layer)) for layer in (*LAYERS, 'experimental')}
        self.disk_snapshot = self.saved.to_dict()

    @property
    def grid(self):
        """Main editable 2D Cell array; use edit() to preserve undo/history."""
        return self.saved.grid

    def _snapshot(self, layer):
        if layer == 'experimental':
            return self.experimental.to_dict()
        field = LAYERS[layer]
        return [[getattr(cell, field) for cell in row] for row in self.grid]

    def _restore(self, layer, snapshot):
        if layer == 'experimental':
            self.experimental = GridState.from_dict(snapshot)
        else:
            field = LAYERS[layer]
            for r in range(SIZE):
                for c in range(SIZE):
                    setattr(self.grid[r][c], field, True if field == 'is_capital' and self.grid[r][c].capital_required else snapshot[r][c])

    def edit(self, layer, cells, value, target=None):
        if layer not in self.histories:
            raise ValueError('Unknown layer.')
        field = LAYERS.get(target if layer == 'experimental' else layer)
        validate_value(field, value)
        if field == 'region_color' and value:
            value = value.lower()
        if not isinstance(cells, list) or not cells or len(cells) > SIZE * SIZE:
            raise ValueError('Select between 1 and 121 cells.')
        for coord in cells:
            if not isinstance(coord, (list, tuple)) or len(coord) != 2 or any(type(x) is not int or not 0 <= x < SIZE for x in coord):
                raise ValueError('Invalid cell coordinate.')
        state = self.experimental if layer == 'experimental' else self.saved
        if field == 'is_capital' and value is False and any(state.grid[r][c].capital_required for r, c in cells):
            raise ValueError('This square is a required capital in the starting puzzle.')
        for r, c in cells:
            setattr(state.grid[r][c], field, value)
        location = f'R{cells[0][0]+1} C{cells[0][1]+1}' if len(cells) == 1 else f'{len(cells)} cells'
        self.histories[layer].record(self._snapshot(layer), f'{location}: {field.replace("_", " ")} → {value}')

    def restore_history(self, layer, index):
        if layer not in self.histories:
            raise ValueError('Unknown layer.')
        history = self.histories[layer]
        if type(index) is not int or not 0 <= index < len(history.states):
            raise ValueError('No history entry at that position.')
        history.cursor = index
        self._restore(layer, deepcopy(history.states[index]))

    def reset_experiment(self):
        self.experimental = deepcopy(self.saved)
        self.histories['experimental'].record(self.experimental.to_dict(), 'Copied current main grid')

    def payload(self):
        return {'main': self.saved.to_dict(), 'experimental': self.experimental.to_dict(),
                'areas': self.saved.region_areas(), 'experimental_areas': self.experimental.region_areas(),
                'regions': self.saved.region_symmetries(), 'experimental_regions': self.experimental.region_symmetries(),
                'histories': {k: v.view() for k, v in self.histories.items()},
                'dirty': self.saved.to_dict() != self.disk_snapshot}

    def save(self, path):
        """Persist main grid + its undo histories. Experimental data is never saved."""
        data = {'version': 1, 'grid': self.saved.to_dict(), 'histories': {
            k: {'states': h.states, 'labels': h.labels, 'cursor': h.cursor}
            for k, h in self.histories.items() if k != 'experimental'}}
        path = Path(path)
        temp = path.with_suffix(path.suffix + '.tmp')
        temp.write_text(json.dumps(data, indent=2, allow_nan=False))
        temp.replace(path)
        self.disk_snapshot = self.saved.to_dict()

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text())
        if not isinstance(data, dict) or data.get('version') != 1:
            raise ValueError('Unsupported project file.')
        workspace = cls(GridState.from_dict(data['grid']))
        for layer, raw in data.get('histories', {}).items():
            if layer not in LAYERS:
                raise ValueError('Invalid history layer.')
            states, labels, cursor = raw['states'], raw['labels'], raw['cursor']
            if not isinstance(states, list) or not states or not isinstance(labels, list) or len(states) != len(labels) or any(not isinstance(x, str) for x in labels) or type(cursor) is not int or not 0 <= cursor < len(states):
                raise ValueError('Invalid history.')
            for snapshot in states:
                if not isinstance(snapshot, list) or len(snapshot) != SIZE or any(not isinstance(row, list) or len(row) != SIZE for row in snapshot):
                    raise ValueError('Invalid history grid.')
                for row in snapshot:
                    for value in row:
                        validate_value(LAYERS[layer], value)
            if states[cursor] != workspace._snapshot(layer):
                raise ValueError('History does not match grid.')
            h = workspace.histories[layer]
            h.states, h.labels, h.cursor = states, labels, cursor
        return workspace
