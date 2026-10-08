"""Bounded, complete-by-size enumeration of connected states containing a square.
Paint and manual capital markers are optional assumptions. No external dependencies.
"""
from collections import Counter, deque
import heapq
import time
from model import SIZE

def neighbors_for_size(size):
    return {r*size+c: tuple(rr*size+cc for rr,cc in ((r-1,c),(r+1,c),(r,c-1),(r,c+1))
                           if 0 <= rr < size and 0 <= cc < size)
            for r in range(size) for c in range(size)}

NEIGHBORS = neighbors_for_size(SIZE)

def indices(mask):
    while mask:
        bit=mask & -mask
        yield bit.bit_length()-1
        mask ^= bit

def coordinates(mask, size=SIZE):
    return [list(divmod(i,size)) for i in indices(mask)]

def search_candidates(state, row, col, max_area=7, time_limit=8.0, node_limit=100000, strategy=None, respect_paint=False, preview_limit=150, check_borders=False, respect_stars=False):
    SIZE = state.size
    NEIGHBORS = neighbors_for_size(SIZE)
    def coordinates(mask):
        return [list(divmod(i, SIZE)) for i in indices(mask)]
    if any(type(v) is not int or not 0 <= v < SIZE for v in (row,col)):
        raise ValueError('Select a square inside the grid.')
    if type(max_area) is not int or not 1 <= max_area <= SIZE*SIZE:
        raise ValueError(f'Choose a maximum candidate area from 1 to {SIZE*SIZE}.')
    if type(respect_paint) is not bool: raise ValueError('Paint constraint must be true or false.')
    if type(check_borders) is not bool: raise ValueError('Border check must be true or false.')
    if type(respect_stars) is not bool: raise ValueError('Manual star constraint must be true or false.')
    # A marked capital is equivalent to a zero-cost clue, but only on a copy:
    # preserve the user's clues, paint, and history. Unmarked cells may still be capitals.
    if respect_stars:
        from model import GridState
        state = GridState.from_dict(state.to_dict())
        for r, cells in enumerate(state.grid):
            for c, cell in enumerate(cells):
                if cell.is_capital:
                    if cell.starting_number not in (None, 0):
                        raise ValueError(f'Manual star at R{r+1} C{c+1} conflicts with its nonzero clue.')
                    cell.starting_number = 0
                    cell.capital_required = True
    conditional = respect_paint or respect_stars
    source_color=state.grid[row][col].region_color
    if respect_paint and source_color is None: raise ValueError('Paint the source square before using paint constraints.')
    painted_components=[(region['color'],{r*SIZE+c for r,c in region['cells']}) for region in state.connected_regions()]
    required_paint=next((cells for color,cells in painted_components if row*SIZE+col in cells),set())
    started=time.monotonic();deadline=started+max(0,time_limit)
    deductions=state.deductions()
    if not deductions['available'] or deductions['contradictions']:
        raise ValueError('Resolve invalid or contradictory clues before candidate search.')
    clues={r*SIZE+c:cell.starting_number for r,rr in enumerate(state.grid) for c,cell in enumerate(rr) if cell.starting_number is not None}
    lower={r*SIZE+c:deductions['minimum_state_sizes'][r][c] for r in range(SIZE) for c in range(SIZE)}
    forced={r*SIZE+c for r,c in deductions['forced_singletons']}
    zeros={i for i,n in clues.items() if n==0}
    groups=[{r*SIZE+c for r,c in g['candidates']} for g in deductions['one_clues']]
    root=row*SIZE+col
    proven_upper=1 if root in forced else SIZE*SIZE
    limit=min(max_area,proven_upper)
    examined=0;completed_area=0;survivors=[];counts=Counter();examples={};levels=[]
    intersection=None;union=0;frequency=[0]*(SIZE*SIZE)
    truncated=False
    generated=0;max_examined_area=0
    strategy=strategy or 'symmetry_orbits'
    if strategy not in ('symmetry_orbits','connected_growth'): raise ValueError('Unknown enumeration strategy.')

    # These failures remain failures in EVERY strict superset. In particular,
    # never prune a small shape merely for missing area, symmetry or paint.
    forced_mask = sum(1 << i for i in forced)
    zero_mask = sum(1 << i for i in zeros)
    singleton_groups = [sum(1 << i for i in group) for group in groups]
    positive_stars = sorted((n, (1 << i) | sum(1 << j for j in NEIGHBORS[i]))
                            for i, n in clues.items() if n > 0)
    branch_prunes = Counter()

    def can_extend(mask):
        reason = None
        if mask & forced_mask:
            reason = 'Forced singleton'
        elif (mask & zero_mask).bit_count() > 1:
            reason = 'Multiple zero clues'
        elif any(mask & group == group for group in singleton_groups):
            reason = 'Clue 1 blocked'
        else:
            size = mask.bit_count()
            for number, star in positive_stars:
                if number >= size:
                    break
                if mask & star == star:
                    # A positive clue is not a capitol. Every first step stays
                    # in this state and costs its final area, already > clue.
                    reason = 'Enclosed positive clue'
                    break
        if reason is not None:
            branch_prunes[reason] += 1
            return False
        return True

    border_checks = 0
    border_grid = None
    if check_borders:
        from model import GridState
        border_grid = GridState.from_dict(state.to_dict())
        for rr in border_grid.grid:
            for cell in rr:
                # Only this candidate has final borders. All other paint is
                # a partial footprint: its eventual area and symmetry may change.
                # Membership/color constraints are enforced separately in assess().
                cell.region_color = None
                cell.is_capital = cell.capital_required
        used_colors = {cell.region_color for rr in border_grid.grid for cell in rr}
        color_number = 0
        while '#%06x'%color_number in used_colors:
            color_number += 1
        overlay_color = '#%06x'%color_number

    def border_failure(cells):
        nonlocal border_checks
        border_checks += 1
        previous = []
        try:
            for i in cells:
                rr,cc = divmod(i,SIZE)
                cell = border_grid.grid[rr][cc]
                previous.append((cell,cell.region_color))
                cell.region_color = overlay_color
            checked = border_grid.validate_partial()
            for number in checked['checks']:
                if number['status']=='contradiction':
                    rr,cc = number['cell']
                    return f"R{rr+1} C{cc+1}: " + ' '.join(number['reasons'])
            for region in checked['regions']:
                if region['issues']:
                    rr,cc = region['cells'][0]
                    return f"Painted state at R{rr+1} C{cc+1}: " + ' '.join(region['issues'])
            return None
        finally:
            for cell,color in previous:
                cell.region_color = color

    def fail(kind,detail): return kind,detail,None

    def assess(mask):
        cells=set(indices(mask));size=len(cells)
        if respect_paint:
            if not required_paint<=cells:
                return fail('Missing painted cells','The candidate must include the entire connected painted region containing the source.')
            for paint_color,component in painted_components:
                if cells & component:
                    if paint_color!=source_color:
                        return fail('Other painted state','The candidate overlaps squares painted a different state color.')
                    if not component<=cells:
                        return fail('Splits painted state','The candidate includes only part of another connected painted component.')
        oversized=next((i for i in cells if lower[i]>size),None)
        if oversized is not None:
            return fail('Area bound',f'R{oversized//SIZE+1} C{oversized%SIZE+1} requires area at least {lower[oversized]}, but this shape has {size}.')
        if size>1 and cells & forced:
            return fail('Forced singleton','This shape absorbs a square already proved to be a singleton capitol.')
        if size>1 and any(group <= cells for group in groups):
            return fail('Clue 1 blocked','This shape absorbs every possible singleton neighbor of a clue 1.')
        symmetry=state.shape_symmetry(coordinates(mask))
        if not symmetry['symmetric']:
            return fail('Asymmetric','The shape has no nonidentity symmetry.')
        ops=symmetry['operations']
        cap=None
        if all(op['fixed_count']==1 for op in ops):
            first=ops[0]['fixed_cells'][0]
            if all(op['fixed_cells'][0]==first for op in ops): cap=first[0]*SIZE+first[1]
        if any(z!=cap for z in cells & zeros):
            return fail('Zero not capitol','A zero clue in this shape is not its symmetry-derived capitol.')
        if cap in clues and clues[cap]>0:
            return fail('Positive clue at capitol','The derived capitol contains a positive clue, but its true cost would be 0.')

        # Exact internal edges; an exit is bounded below by neighboring area bounds.
        # Upper routes use the candidate's capitol or established outside capitols.
        lo={i:float('inf') for i in cells};hi=lo.copy()
        if cap is not None: lo[cap]=hi[cap]=0
        for i in cells:
            for j in NEIGHBORS[i]:
                if j in cells: continue
                lo[i]=min(lo[i],min(size,lower[j]))
                if j in forced: hi[i]=min(hi[i],1)
                elif j in zeros: hi[i]=min(hi[i],size)
        def spread(dist):
            q=[(d,i) for i,d in dist.items() if d<float('inf')];heapq.heapify(q)
            while q:
                d,i=heapq.heappop(q)
                if d!=dist[i]: continue
                for j in NEIGHBORS[i]:
                    if j in cells and d+size<dist[j]:
                        dist[j]=d+size;heapq.heappush(q,(d+size,j))
        spread(lo);spread(hi)
        for i in cells:
            n=clues.get(i)
            if n is not None and n<lo[i]:
                return fail('No cheap enough exit',f'Clue {n} at R{i//SIZE+1} C{i%SIZE+1} needs cost below the minimum possible {lo[i]} to leave this state or reach its capitol.')
            if n is not None and n>hi[i]:
                return fail('Cheaper capitol route',f'Clue {n} at R{i//SIZE+1} C{i%SIZE+1} has a guaranteed route costing at most {hi[i]}.')
            if hi[i]<float('inf'):
                for j in NEIGHBORS[i]:
                    if j not in cells and j in clues and clues[j]>hi[i]+size:
                        return fail('Cheaper neighboring route',f'Outside clue {clues[j]} at R{j//SIZE+1} C{j%SIZE+1} can enter this state and reach a capitol for at most {hi[i]+size}.')
        inside=[i for i in cells if i in clues]
        for source in inside:
            distance={source:0};queue=deque([source])
            while queue:
                i=queue.popleft()
                for j in NEIGHBORS[i]:
                    if j in cells and j not in distance:
                        distance[j]=distance[i]+1;queue.append(j)
            for target in inside:
                if abs(clues[source]-clues[target])>size*distance[target]:
                    return fail('Clue distance difference','Two clues in this state differ by more than the cost of an internal path between them.')
        if check_borders:
            failure = border_failure(cells)
            if failure:
                return fail('Border check',failure)
        return None,None,{'cells':coordinates(mask),'area':size,'capitol':None if cap is None else list(divmod(cap,SIZE)),
                          'rotations':symmetry['rotations'],'reflections':symmetry['reflections']}

    if strategy=='symmetry_orbits':
        from symmetric_shapes import symmetric_masks, connected
        seen=set();by_area=Counter();accepted_area=Counter()
        for mask in symmetric_masks(root,limit,can_extend,size=SIZE):
            generated+=1
            if generated>node_limit or time.monotonic()>=deadline:
                truncated=True;break
            if mask in seen:continue
            seen.add(mask)
            if not connected(mask,size=SIZE):continue
            examined+=1;size=mask.bit_count();max_examined_area=max(max_examined_area,size)
            by_area[size]+=1
            reason,detail,candidate=assess(mask)
            if reason:
                counts[reason]+=1;examples.setdefault(reason,{'reason':detail,'cells':coordinates(mask)})
            else:
                accepted_area[size]+=1;survivors.append(candidate)
                intersection=mask if intersection is None else intersection & mask
                union |= mask
                for i in indices(mask):frequency[i]+=1
        completed_area=0 if truncated else limit
        levels=[{'area':size,'examined':by_area[size],'survivors':accepted_area[size],'complete':not truncated} for size in range(1,limit+1)]
    else:
        level={1<<root}
        for size in range(1,limit+1):
            accepted=0;level_examined=0
            for mask in sorted(level):
                if examined>=node_limit or time.monotonic()>=deadline:
                    truncated=True;break
                examined+=1;level_examined+=1
                reason,detail,candidate=assess(mask)
                if reason:
                    counts[reason]+=1
                    examples.setdefault(reason,{'reason':detail,'cells':coordinates(mask)})
                else:
                    accepted+=1;survivors.append(candidate)
                    intersection=mask if intersection is None else intersection & mask
                    union |= mask
                    for i in indices(mask): frequency[i]+=1
            levels.append({'area':size,'examined':level_examined,'survivors':accepted,'complete':not truncated})
            if truncated: break
            completed_area=size
            if size==limit: break
            # Rejected small shapes must STILL grow: adding cells can restore symmetry,
            # change a capitol, or meet an area bound. Never prune those extensions.
            next_level=set()
            for mask in sorted(level):
                if time.monotonic()>=deadline:
                    truncated=True;break
                for i in indices(mask):
                    for j in NEIGHBORS[i]:
                        if not mask & (1<<j): next_level.add(mask | (1<<j))
                if len(next_level)>node_limit:
                    truncated=True;break
            if truncated: break
            level=next_level
        max_examined_area=max((entry['area'] for entry in levels if entry['examined']),default=0)
        generated=examined
    within_complete=not truncated and completed_area==limit
    exhaustive=within_complete and limit>=proven_upper
    common=coordinates(intersection or 0)
    total=len(survivors)
    # Statistics cover ALL survivors, even when only a preview subset is sent.
    heat=[[frequency[r*SIZE+c] for c in range(SIZE)] for r in range(SIZE)]
    return {'heatmap':heat,'source':[row,col],'max_area':max_area,'proven_upper_area':proven_upper,
            'completed_through_area':completed_area,'complete_within_limit':within_complete,
            'exhaustive':exhaustive,'truncated':truncated,'examined':examined,'survivor_count':total,
            'survivors':survivors if preview_limit is None else survivors[:preview_limit],'preview_limited':preview_limit is not None and total>preview_limit,'common_cells':common,'possible_cells':coordinates(union),
            'forced_cells':common if exhaustive and total and not conditional else [],
            'respect_stars':respect_stars, 'conditional':conditional,
            'paint_mode':'partial' if respect_paint else 'ignored',
            'respect_paint':respect_paint, 'paint_required_cells':[list(divmod(i,SIZE)) for i in sorted(required_paint)] if respect_paint else [],
            'conditional_common_cells':common if within_complete and (not exhaustive or conditional) and total else [],
            'rejections':dict(counts),'rejection_examples':examples,'levels':levels,
            'branch_prunes':dict(branch_prunes),
            'border_check_enabled':check_borders,'border_checks':border_checks,
            'elapsed_seconds':round(time.monotonic()-started,3), 'strategy':strategy,
            'generated':generated, 'max_examined_area':max_examined_area,
            'max_survivor_area':max((c['area'] for c in survivors),default=0),
            'frequency':[[frequency[r*SIZE+c]/total if total else 0 for c in range(SIZE)] for r in range(SIZE)],
            'scope':('CONDITIONAL ON PAINT: source component must be included; other colors excluded; connected painted groups kept intact. ' if respect_paint else 'Paint ignored. ')+('Manual stars required as capitals. ' if respect_stars else 'Manual stars ignored. ')+('Only the candidate has final borders in the border check; outside squares use optimistic cost 1. Other painted groups can grow and change symmetry or capitol. ' if check_borders else '')+'Survivors are locally compatible, not proven global solutions.',
            'conclusion':('Assuming the selected constraints: ' if conditional else '')+('No state satisfies these rules.' if exhaustive and not total else
                          ('Exhaustive under selected assumptions; common cells are conditional.' if conditional else 'Exhaustive for this square; common cells are forced.') if exhaustive else
                          'Search interrupted; common cells are observational only.' if truncated else
                          f'Complete only through area {limit}. Common cells are conditional on this area limit; larger states remain possible.')}
