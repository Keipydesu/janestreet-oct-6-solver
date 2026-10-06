"""Bounded, complete-by-size enumeration of connected states containing a square.
No paint or manual capital markers are assumed correct. No external dependencies.
"""
from collections import Counter, deque
import heapq
import time
from model import SIZE

NEIGHBORS = {r*SIZE+c: tuple(rr*SIZE+cc for rr,cc in ((r-1,c),(r+1,c),(r,c-1),(r,c+1))
                           if 0 <= rr < SIZE and 0 <= cc < SIZE)
             for r in range(SIZE) for c in range(SIZE)}

def indices(mask):
    while mask:
        bit=mask & -mask
        yield bit.bit_length()-1
        mask ^= bit

def coordinates(mask):
    return [list(divmod(i,SIZE)) for i in indices(mask)]

def search_candidates(state, row, col, max_area=7, time_limit=8.0, node_limit=100000, strategy=None, respect_paint=False, preview_limit=150):
    if any(type(v) is not int or not 0 <= v < SIZE for v in (row,col)):
        raise ValueError('Select a square inside the grid.')
    if type(max_area) is not int or not 1 <= max_area <= SIZE*SIZE:
        raise ValueError('Choose a maximum candidate area from 1 to 121.')
    if type(respect_paint) is not bool: raise ValueError('Paint constraint must be true or false.')
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
        return None,None,{'cells':coordinates(mask),'area':size,'capitol':None if cap is None else list(divmod(cap,SIZE)),
                          'rotations':symmetry['rotations'],'reflections':symmetry['reflections']}

    if strategy=='symmetry_orbits':
        from symmetric_shapes import symmetric_masks, connected
        seen=set();by_area=Counter();accepted_area=Counter()
        for mask in symmetric_masks(root,limit,can_extend):
            generated+=1
            if generated>node_limit or time.monotonic()>=deadline:
                truncated=True;break
            if mask in seen:continue
            seen.add(mask)
            if not connected(mask):continue
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
            'forced_cells':common if exhaustive and total and not respect_paint else [],
            'respect_paint':respect_paint, 'paint_required_cells':[list(divmod(i,SIZE)) for i in sorted(required_paint)] if respect_paint else [],
            'conditional_common_cells':common if within_complete and (not exhaustive or respect_paint) and total else [],
            'rejections':dict(counts),'rejection_examples':examples,'levels':levels,
            'branch_prunes':dict(branch_prunes),
            'elapsed_seconds':round(time.monotonic()-started,3), 'strategy':strategy,
            'generated':generated, 'max_examined_area':max_examined_area,
            'max_survivor_area':max((c['area'] for c in survivors),default=0),
            'frequency':[[frequency[r*SIZE+c]/total if total else 0 for c in range(SIZE)] for r in range(SIZE)],
            'scope':('CONDITIONAL ON PAINT: source component must be included; other colors excluded; connected painted groups kept intact. ' if respect_paint else 'Clues only; painted states and manual markers ignored. ')+'Survivors are locally compatible, not proven global solutions.',
            'conclusion':('Assuming the painted constraints: ' if respect_paint else '')+('No state satisfies these rules.' if exhaustive and not total else
                          ('Exhaustive under painted assumptions; common cells are conditional.' if respect_paint else 'Exhaustive for this square; common cells are forced.') if exhaustive else
                          'Search interrupted; common cells are observational only.' if truncated else
                          f'Complete only through area {limit}. Common cells are conditional on this area limit; larger states remain possible.')}
