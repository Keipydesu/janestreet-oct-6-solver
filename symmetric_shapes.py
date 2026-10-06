"""Enumerate symmetric cell sets via involution orbits, then test connectivity.

Every square-grid state symmetry contains either a reflection or a half-turn
(a quarter-turn implies a half-turn). Enumerating these five transform families
therefore covers ALL symmetric shapes, without requiring a particular symmetry.
"""
from collections import deque
from candidate_search import NEIGHBORS, indices
from model import SIZE

NEIGHBOR_MASK = {i:sum(1<<j for j in cells) for i,cells in NEIGHBORS.items()}

def connected(mask):
    reached=front=mask & -mask
    while front:
        adjacent=0
        for i in indices(front): adjacent |= NEIGHBOR_MASK[i]
        front=adjacent & mask & ~reached
        reached |= front
    return reached==mask

def orbit_walk(root, max_area, transform):
    """Connected quotient-graph subsets. Actual cell connectivity checked later.

    The starting orbit can be two disconnected cells. Do NOT require intermediate
    masks to be connected: later orbits can connect the two halves of a state.
    """
    r,c=divmod(root,SIZE);rr,cc=transform(r,c)
    if not (0<=rr<SIZE and 0<=cc<SIZE) or abs(rr-r)+abs(cc-c)>max_area-1:
        return
    orbits={}
    for i in range(SIZE*SIZE):
        ar,ac=divmod(i,SIZE);br,bc=transform(ar,ac)
        if 0<=br<SIZE and 0<=bc<SIZE:
            orbits[i]=(1<<i)|(1<<(br*SIZE+bc))
    initial=orbits[root]
    if initial.bit_count()>max_area:return
    stack=[initial];seen={initial}
    while stack:
        mask=stack.pop()
        yield mask
        # All orbit extensions are symmetric. Quotient connectivity is enough
        # for generation, but a disconnected final set is never a candidate.
        border=0
        for i in indices(mask): border |= NEIGHBOR_MASK[i]
        border &= ~mask
        extensions={mask|orbits[i] for i in indices(border) if i in orbits}
        for child in sorted(extensions):
            if child.bit_count()<=max_area and child not in seen:
                seen.add(child);stack.append(child)

def symmetric_masks(root,max_area):
    """Round-robin DFS across axes/centers; visits large shapes early.

    Duplicates across symmetry families are deliberately left to the caller.
    Yielding intermediate disconnected sets allows bounded search accounting.
    """
    transforms=[]
    for k in range(2*SIZE-1):
        transforms.extend((lambda r,c,k=k:(k-r,c), lambda r,c,k=k:(r,k-c),
                           lambda r,c,k=k:(k-c,k-r)))
    for k in range(-(SIZE-1),SIZE):
        transforms.append(lambda r,c,k=k:(c+k,r-k))
    for kr in range(2*SIZE-1):
        for kc in range(2*SIZE-1):
            transforms.append(lambda r,c,kr=kr,kc=kc:(kr-r,kc-c))
    walkers=deque(orbit_walk(root,max_area,t) for t in transforms)
    while walkers:
        walker=walkers.popleft()
        try:
            mask=next(walker)
        except StopIteration:
            continue
        walkers.append(walker)
        yield mask
