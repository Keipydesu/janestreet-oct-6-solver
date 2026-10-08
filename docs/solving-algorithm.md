Grid Studio • Implementation guide • 7 October 2026

# How our puzzle solver works

Our current **Decompose board** tool searches for a partition of the board into connected, symmetric states, then verifies that the partition reproduces every numbered clue. It combines shape enumeration, exact-cover backtracking, and weighted shortest-path bounds.

This guide explains the algorithm used by the editor on both the 5 × 5 and 11 × 11 boards. It includes mathematical examples and a verified solution to the smaller puzzle. A verified result establishes a valid solution under the implemented rules; a search that runs out of time does not establish impossibility or uniqueness.

Committed clues → Area bounds → Candidate states → Exact cover → Verified partition

## The mathematical model

A **state** is a connected group of squares, using edge adjacency. Every board square must belong to exactly one state. Its area is its number of squares. Each state must have at least one nonidentity symmetry: a reflection or a rotation that maps its cells onto themselves.

The code tests all seven nonidentity square-grid transformations: rotations through 90, 180, and 270 degrees, and horizontal, vertical, and two diagonal reflections. Transformed shapes are translated to a common origin before comparison.

A state has a **capitol** only if every symmetry that the shape possesses fixes exactly one square, and that square is the same for all of those symmetries. “Fixed” means the whole square maps to itself. A symmetric state may have no capitol. A singleton is its own capitol.

### Movement and numbered clues

Let A(u) be the area of the state containing square u. For adjacent squares u and v, the movement cost is:

w(u, v) = min(A(u), A(v))

A step within one state therefore costs that state’s area. Crossing a boundary costs the smaller of the two state areas. A clue at square u specifies the minimum total movement cost from u to *any* capitol, not necessarily one in its own state. Denote that distance by d(u).

For example, crossing between states of areas 7 and 3 costs 3. A route with two such crossings costs 6. A longer route can be cheaper than a shorter one, so counting steps alone is insufficient. The solver uses Dijkstra’s algorithm with these positive edge weights.

## Clue deductions before shape search

The editor’s solver calls `GridState.deductions()` to derive necessary conditions. These reduce the number of shapes worth considering:

- A positive clue cannot be a singleton because a singleton’s distance to a capitol is zero.
- A zero clue must be a capitol. Its state has odd area, but need not have area one.
- A clue of 1 must have a neighboring singleton capitol. Other clues and area bounds can eliminate neighbors until one is forced.
- Adjacent clue values constrain both endpoint state areas.

The last rule follows from the shortest-path inequality:

|d(u) − d(v)| ≤ w(u, v) = min(A(u), A(v))

In the smaller puzzle, R1C1 = 12 and R2C1 = 8 differ by 4. Both squares must therefore belong to states of area at least 4. This does not establish whether they belong to the same state.

The rule engine also propagates bounds near forced singletons and rounds a zero-clue state’s area lower bound up to an odd number. Invalid clues or detected contradictions stop the search.

## Generating candidate states

A candidate is a connected symmetric shape containing a selected root square, together with its area and its derived capitol, if any. The whole-board solver generates candidates around multiple roots and deduplicates shapes into one shared pool.

### Build symmetry into the enumeration

The default generator uses reflections and half-turns. Under one such transformation, a square either maps to itself or pairs with another square. These one- or two-square groups are called *orbits*. Adding complete orbits preserves the chosen symmetry automatically.

The generator grows sets of orbits, cycling among axes and centers so one family does not consume the entire budget. It permits intermediate sets whose actual squares are disconnected, because later additions can connect them. Actual connectivity is checked before a shape is assessed as a candidate. Quarter-turn-symmetric shapes are covered because they also have half-turn symmetry.

### Reject shapes that cannot work

Each candidate must respect the derived area bounds, required singleton squares, zero clues, and capitol geometry. It cannot place a positive clue at its capitol. Local path bounds also reject shapes whose internal travel or exits would force a clue distance to be too high or too low.

The generator distinguishes rejecting a shape from stopping its entire growth branch. Only failures that persist under every enlargement justify stopping growth. Examples include absorbing a forced singleton into a larger state, containing two zero clues, or enclosing a positive clue so every first step already costs more than the clue permits.

The standalone candidate tool optionally respects painted regions. **Whole-board decomposition ignores paint** and searches from committed clues. Geometrically required capitol flags are still checked when a completed result is validated.

## Combining states into an exact cover

For each candidate state S, imagine a binary variable x<sub>S</sub>: one means we select it and zero means we do not. For every board cell c, we require:

∑<sub>S containing c</sub> x<sub>S</sub> = 1

This is the exact-cover condition. It enforces complete coverage without overlaps. It does not by itself enforce the numbered distances, so the solver adds travel checks during the search.

The implementation represents a shape as an integer bit mask, with one bit per board cell. Bit operations make intersection and coverage checks inexpensive. Recursive backtracking proceeds as follows:

1. For every uncovered cell, list the candidates that do not overlap states already chosen.
2. If any cell has no candidate, reject this branch.
3. Run the global area and travel bounds described below.
4. Choose the uncovered cell with the fewest distinct remaining state areas, then the smallest maximum area, then the fewest candidate shapes.
5. Try each of its candidates, smaller areas first, then recurse. Undo that choice when the branch fails.
6. When all cells are covered, independently validate the resulting board.

The search stops at the first verified solution. It does not enumerate every solution.

### Global travel bounds prune partial partitions

For each cell, remaining candidates give lower and upper bounds on its eventual state area. A chosen state fixes those areas exactly. The solver also tracks squares that must be capitols and squares that could still become capitols.

With maximum possible areas, it computes generous route costs from clues and certain capitols. A known route that is already cheaper than a clue rules out the branch. For instance, if a clue is 12 but even the upper bound on a route to a mandatory capitol is 10, the true minimum distance cannot be 12.

It also propagates clue-derived lower bounds on distances to exclude impossible capitol locations. Finally, using minimum possible areas and all remaining possible capitols, it computes an optimistic nearest-capitol distance. If even that optimistic distance exceeds a required upper bound, no completion of this branch can work.

Before choosing a branch, the solver checks each remaining candidate against
these distance intervals. Every non-capitol square must admit a neighbor with
`d(square) = d(neighbor) + movement cost`. Internal movement costs the candidate's
exact area; external costs use the remaining area bounds. The candidate's
capitol must admit distance zero. For example, a positive clue surrounded by
neighbors of equal or greater distance has no descending step and is impossible.
Rejected candidates are removed from all cell domains. Up to three rounds of
filtering and recalculating bounds run at each search node; the limit controls
work, and does not turn surviving candidates into proven feasible states.

These bounds are necessary conditions. They can leave impossible branches alive, but they are designed not to discard a completion represented by the current candidate pool. Bounds derived from a sampled pool apply only to completions using that pool.

Failed partial decompositions are cached by the occupied cells’ areas and the derived capitol locations. Different borders between equal-area states share a cache entry only when both agree. Actual symmetric states are still retained for final validation. The cache is cleared whenever the candidate pool grows. Initial clue-based forbidden capitol locations also filter candidates before they enter the pool; these exclusions use the full configured area limit, not an early generation stage.

## Time limits and expanding the candidate pool

The editor gives the solve call an eight-second budget and starts with about 0.08 seconds of generation per root. The maximum searched state area is 98 cells, capped at the board area (25 cells on the smaller puzzle). Generation starts with areas up to 4, prioritizing forced singletons and roots with fewer clue-compatible areas; roots requiring larger states wait for expansion. At most half the total budget is allocated to the initial generation pass.

If exact cover fails on the initial pool, the solver uses remaining time to expand it. It prioritizes smaller next area limits and fewer clue-compatible areas, then less-explored roots and coverage failures. Each root’s area limit grows roughly by doubling, up to the configured maximum, and the generation budget grows too. Search restarts when new shapes arrive. Earlier pool-based rejections cannot be carried over unchanged to a larger pool.

The generator has both time and node limits. Its symmetry construction is intended to cover the shape families in a completed enumeration, but a bounded run may examine only part of them. Repeating a short run can revisit the same deterministic search prefix; it is not a guarantee of cumulative progress.

## Independent verification and result meanings

For a complete partition, `materialize()` builds a fresh colored board. `validate_puzzle()` then reconstructs connected regions, checks their symmetry and required capitols, derives the actual capitol set, recomputes weighted shortest paths, and compares every clue with its actual distance.

This final check is separate from the search’s pruning decisions, although both use the project’s common geometry and movement rules. It is a validation against our implemented model, not an independent formal proof of that model.

| Returned status | What it establishes |
| --- | --- |
| `verified_solution` | A full partition passed validation. Uniqueness was not checked. |
| `time_limit` | The allotted search time ended. A solution may still exist. |
| `sample_exhausted` | No solution was found in the explored pool. The current solver does not return this as a global impossibility proof. |
| `area_limit_contradiction` | A clue cannot be reached under the supplied maximum-area cap. This rejects that cap, not necessarily the puzzle. |

The editor keeps a verified result behind **Reveal verified decomposition**. Searching and revealing the preview do not edit the painted board or save it to disk.

## Where the algorithm lives

| File | Responsibility |
| --- | --- |
| `app.py` | Routes the editor request to the eight-second solve and returns the result for preview. |
| `solver.py` | Candidate pooling, exact-cover recursion, global travel bounds, pool expansion, and final validation. |
| `candidate_search.py` | Candidate checks, local distance bounds, and bounded generation accounting. |
| `symmetric_shapes.py` | Orbit-based symmetric shape generation and connectivity checks. |
| `model.py` | Clue deductions, symmetry and capitol rules, weighted distances, and board validation. |
| `index.html` | Search controls, candidate heatmaps, live border checks, and the hidden result preview. |

### Separate experimental solvers

The repository also contains `deduction_engine.py`, a stronger area-domain propagation engine, and `area_solver.py`, an experimental area-first constraint solver. These are separate command-line paths built around the original board size. The editor’s current decomposition button calls `solver.solve()`; it does not invoke either of those alternative engines.

### Evidence from the smaller board

During development, one 5 × 5 run found a verified solution in approximately 2.02 seconds, using 1,873 candidate states and 72 exact-cover search nodes. None of its root enumerations was marked complete. That illustrates why finding and verifying a solution can succeed without enumerating every possible state. Those measurements describe one run, not a performance guarantee.

At the end of the decomposition change, 76 tests passed. They included independent validation of a small-board solution, timeout semantics, route isolation, and undoing the Experimental replacement. Source references throughout this document describe the local implementation as of 7 October 2026.

## Verified solution to the 5 × 5 puzzle

Each letter identifies one state. An asterisk marks its symmetry-derived capitol. Coordinates below are one-based. This is one verified solution; uniqueness has not been checked.

```text
       C1  C2  C3  C4  C5
R1     A   B   B   C   C
R2     A   B   B   D   C
R3     A   A*  D   D*  C
R4     C   A   A   A   C
R5     C   C   C   C   C*
```

| State | Area | Capitol | Cells |
| --- | --- | --- | --- |
| A | 7 | R3C2 | R1C1, R2C1, R3C1, R3C2, R4C2, R4C3, R4C4 |
| B | 4 | None | R1C2, R1C3, R2C2, R2C3 |
| C | 11 | R5C5 | R1C4, R1C5, R2C5, R3C5, R4C1, R4C5, R5C1, R5C2, R5C3, R5C4, R5C5 |
| D | 3 | R3C4 | R2C4, R3C3, R3C4 |

### Verification of every clue

The validator recomputed shortest paths to the derived capitols using the state areas above. Every clue matches.

| Square | Given clue | Computed distance |
| --- | --- | --- |
| R1C1 | 12 | 12 |
| R1C5 | 17 | 17 |
| R2C1 | 8 | 8 |
| R2C3 | 6 | 6 |
| R2C4 | 3 | 3 |
| R4C2 | 7 | 7 |
| R4C3 | 6 | 6 |
| R4C5 | 10 | 10 |
| R5C1 | 25 | 25 |
| R5C5 | 0 | 0 |

All 25 cells are covered, all states satisfy the symmetry rules, and all required capitols are in the correct locations.
