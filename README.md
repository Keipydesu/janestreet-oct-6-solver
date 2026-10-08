# Jane Street grid puzzle solver

A local grid editor and CPU solver for the supplied 11-by-11 state/capitol puzzle.
The default solver uses Python's standard library only; no pip packages or GPU
are required. It runs in one process (no multicore parallelism). An optional
experimental constraint solver is described below.
This is an independent puzzle-solving project, not an official Jane Street tool.

## Run on Windows

Install Python 3.10 or newer and Git, then run in PowerShell:

```powershell
git clone https://github.com/Keipydesu/janestreet-oct-6-solver.git
cd janestreet-oct-6-solver
py -3 solver.py --seconds 600 --output solver-report.json
```

On macOS/Linux, use `python3` instead of `py -3`.
The search is bounded and may finish without finding a solution; a timeout does
not mean the puzzle is impossible. Only `verified_solution` is a solved result.

## Grid editor

```powershell
py -3 app.py
```

The browser opens a local editor at `http://127.0.0.1:8000`.
Use the **5 × 5** link in the header or open `http://127.0.0.1:8000/small`
to work on the smaller puzzle with all the same editor tools. Its main grid and
history save separately to `project-small.json`; the original puzzle stays at `/`.

It starts from the clues in `starting_grid.py`. Save stores your local work in
`project.json`; saved sessions, backups, and generated reports are ignored by Git.
The server binds only to localhost and generates a fresh edit token at startup.

## State counts layer

Choose **State counts** to color every square by how many distinct candidate
states include it, using committed starting clues only. Blue means fewer,
orange means more; colors use a logarithmic scale. Adjust **Maximum state area**
(default 98, or 25 on the small board) and use **Recount states** to run again.
Paint and manual stars do not affect the result. Editing clues invalidates counts.

The eight-second search combines and deduplicates shapes found from every root.
A `~` prefix means the count is sampled; `~0` means none found, not impossibility.
Unprefixed counts exhaust the local checks within the selected area limit.
These are connected symmetric candidates passing local clue checks and capitol
exclusions, not states proven to occur in a complete solution. The selected-cell
panel explains this scope. The layer never edits your grid or history.

## Whole-board decomposition

Build the Rust engine once (Rust 1.90 or newer):

```sh
cargo build --release --manifest-path rust-solver/Cargo.toml
```

Restart `app.py` after building. Click **Decompose board** in the editor's right panel to combine candidate states
into a complete, non-overlapping partition and independently check all clue
distances. It uses committed starting clues, ignoring paint. Search is bounded to eight seconds; an unsuccessful
search does not prove impossibility or uniqueness.

A verified result stays hidden behind **Reveal verified decomposition**.
The preview does not change your painted grid or saved files.
The solver supports both the 5×5 and 11×11 routes.

## Check current borders

Choose **Check current borders** in the layer list. Enable **Paint while checking** to edit directly in this view; leave it off
to inspect cells. Checks refresh after each stroke and region undo.

Candidate states and Candidate heatmap treat paint as partial regions. With
**Use paint as a constraint** enabled, candidates must include the source’s
connected painted group, avoid other colors, and never split a painted group.
Other painted regions can grow: their current sizes, symmetries, and derived
capitols are not final. Only the candidate under consideration has fixed borders
in the border check; outside squares use optimistic cost 1. Failed candidates
appear under the **Border check** rejection reason.

**Consider manual stars** in either candidate view requires marked squares to be
symmetry-derived capitols, with or without paint constraints. Unmarked squares
may still be capitols. Results are conditional on these optional assumptions;
manual stars do not change the saved clues.

The candidate heatmap combines different shapes; its outline is not itself a
candidate state. Painted source cells are required in every candidate, but the
candidate can add cells to complete their symmetry. A capitol need not be a
rotation center: reflection-only states are allowed when every symmetry fixes
exactly that one square. Expand **Inspect individual shapes** to view one
candidate, its symmetry, and its derived capitol (☆).

Percentages describe membership among candidates found, not solution
probabilities. A `~` prefix marks a non-exhaustive search. Near-100% values never
round up to 100%; changing constraints hides stale percentages and colors.

In the separate **Check current borders** view, each painted component is
treated as a finished state with fixed borders.
Red means an invalid shape, capitol conflict, or a contradicted starting clue.
Yellow means a clue is unresolved; green means no local contradiction was found.
Click a clue to highlight its cheapest route to a known/required capitol and
see its cost and destination. Use **Highlight path** to inspect the minimum
possible route or the painted-only route instead. Routes through unpainted
cells are provisional; a minimum-possible route may end at a future capitol.

Unpainted squares use area 1 for optimistic distances and can contain future
capitols. A clue smaller than that optimistic distance cannot work with these
borders. A clue larger than a fixed route through painted states also fails.
Cheap routes through unpainted squares alone do not prove a failure, because
those routes can get more expensive when the board is completed. Passing the
check is necessary consistency, not a guarantee of a full solution.

The My numbers layer has been removed. Older project files still load: notes
and their history are ignored, and the next save omits them. Starting clues,
regions, capitols, and their histories are preserved.

## Bounding the largest state

```bash
.venv/bin/python largest_state_bound.py --seconds 60 --output solver-largest-state-report.json
```

This optional OR-Tools analysis tests states larger than half the 11×11 board.
It first checks every possible reflection or half-turn against the small-clue
escape requirements. It then uses exact area inventory and distance constraints,
actual templates for areas 2 through 4, per-area capitol budgets, and geometric
checks with sound cuts on returned assignments. The report distinguishes a
proved upper bound from a fully verified witness and from a timeout.

On the original clues, the symmetry/escape stage proved an upper bound of 98.
A 60-second-budget run did not improve that bound in the combined model; it
returned no full assignment to check. This does not establish that area 98 is
achievable. The previously proved lower bound remains 26. These bounds concern
the original clues, and are not automatically imposed on edited puzzles.

## Tests

```powershell
py -3 -m unittest test_model test_candidates test_solver test_deduction_engine
```

## Paint on candidate views

In Candidate heatmap or Candidate states, enable **Paint on candidate view**
to click/drag using the normal palette and eraser. Colored inset borders show
region paint without replacing the heatmap colors. A stroke is one region undo
step; Undo/Redo and history in this view control Regions (or Experimental when
working inside that copy). Main save and experimental isolation still apply.
Turn painting off to select an origin without painting it.

Optionally enable **Use paint as a constraint**, paint the source square, and
search. Candidates must contain the source's whole connected painted component,
exclude other colors, and never split any other painted component they touch.
Disconnected components of the same color are not automatically required.
Results are explicitly conditional on these painted assumptions, even if the
bounded search finishes. No paint-conditioned intersection is called globally
forced. Paint does not override symmetry or clue checks.

With a completed search and paint constraints enabled, each stroke and undo
reruns the search for the pinned search origin. The last heatmap stays available
while painting with constraints off, because those searches ignore colors.
Searches can take up to eight seconds, during which painting is disabled.
Python: `state.candidate_states(row, col, max_area=20, respect_paint=True)`.

### Combined solver

The editor now uses the Rust engine through `rust_solver.py`. Run it from the
project directory:

```sh
python3 rust_solver.py --seconds 120 --output solver-rust-report.json
python3 rust_solver.py --size 5 --seconds 10 --output solver-small-report.json
# Use your saved editor clues:
python3 rust_solver.py --input project.json --seconds 600 --max-area 98
```

Or run the native executable directly (input is a clue matrix, editor grid, or
project JSON):

```sh
./rust-solver/target/release/decomposition --input project.json --seconds 600 --max-area 98 --output solver-rust-report.json
```

Progress is now saved automatically. Running the same command again continues
from its checkpoint; repeated **Decompose board** clicks do the same. Automatic
checkpoints live in `.solver-checkpoints/`, keyed by starting clues, board size and
maximum area, so paint changes do not reset progress and changed clues get a
separate search. Restarting the editor also preserves these files.

The Python CLI defaults to `--checkpoint auto`. Its path is
`<repository>/.solver-checkpoints/<24-character hash>.json`, regardless of the
directory you run the command from. In this checkout the default directory is
`/Users/thekpokay/projects/janestreet-puzzles/oct-6/.solver-checkpoints/`.
The hash depends on the clues, board size and maximum area. An explicit relative
path such as `--checkpoint my-search.json` is relative to your current directory.
The default report, `solver-rust-report.json`, is separate from the checkpoint.

```sh
# Run for another ten minutes, resuming previous progress automatically:
python3 rust_solver.py --seconds 600 --max-area 98
# Choose a checkpoint explicitly:
python3 rust_solver.py --seconds 600 --checkpoint my-search.json
# Deliberately start over for the selected puzzle/checkpoint:
python3 rust_solver.py --seconds 600 --fresh
# One-off run without saving or resuming:
python3 rust_solver.py --seconds 10 --no-checkpoint
```

For the native executable, add `--checkpoint my-search.json` to enable resume.
Keep checkpoint paths separate from report/output paths. Checkpoints retain
candidate shapes, per-root symmetry-enumeration stacks and visited sets, remaining
partition-search branches, explored equivalent partitions, and cumulative stats.
The current candidate pool's search is resumed before generating more candidates.
When the pool grows, its partition search must restart because earlier rejections
were conditional on the old pool; generated candidates and enumeration progress
are retained. An area stage grows only after its enumeration finishes.

Checkpoints are written atomically about every five seconds at work-unit
boundaries and at normal completion. After Ctrl+C or a crash, rerun the same
command to recover the last completed checkpoint; work since that save can be
lost. Time limits are cooperative and checkpoint I/O adds overhead. Large searches
can produce large checkpoint files. A file lock prevents two processes from
using the same checkpoint simultaneously. Explicit checkpoints with mismatched
clues/area limits or unreadable contents are rejected without being overwritten;
`--fresh` deliberately replaces the selected checkpoint. Old runs started before
this feature cannot have their in-memory progress recovered.

The Rust core uses `u128` masks for shapes, occupied squares and capitols,
precomputed adjacency masks, a deduplicated candidate vector, and per-cell
candidate indexes. Area and distance data use flat vectors. The 2D grid remains
the editor/JSON format. Candidate enumeration, mathematical pruning and exact
cover all run in Rust; the Python bridge independently validates returned
solutions before the editor can display or apply them. Direct native CLI output
is validated by the Rust geometry and shortest-path checks.

The Python reference remains available as
`python3 solver.py --seconds 120 --output solver-report.json`. Both engines combine
clue deductions, symmetric candidate states (up to 98 cells by default), non-overlapping
full-board coverage, and global weighted shortest-path bounds. The search
chooses the uncovered cell with fewest distinct remaining areas, breaking ties by
smaller maximum area and fewer shapes, and tries smaller candidates first.
Every completed solution is independently checked by `validate_puzzle()`.
This uses the supplied starting clues and ignores paint; it does not modify the
running editor, saved project, or experimental layer.

At every search node, compatible candidates give each uncovered cell a minimum
and maximum state area. They also restrict possible capitols and identify cells
that are capitols in every remaining candidate. Chosen states have exact areas
and symmetry-derived capitols. These bounds are conditional on the sampled pool.

Weighted path propagation checks all clue pairs: their distance difference
cannot exceed the cost of any route between them, including routes through
multiple states. A multi-source shortest-path pass checks these inequalities
using maximum possible areas. A second pass rules out capitol locations that
would make a clue too cheap; minimum possible areas then bound the distance to
the remaining possible capitols. Contradictory bounds prune the branch before
further partition search. Reports include `clue_path_prunes`, `capitol_prunes`,
and `distance_prunes` when those rejection types occur.

Before branching, the decomposition solver also checks the shortest-path
(Bellman) equality for each candidate shape. Every non-capitol cell must have
at least one possible descending step whose edge cost plus neighbor distance
can equal its own distance. Internal edges use the shape's exact area; external
edges use bounds from remaining candidates. Its derived capitol must permit
distance zero, and every adjacent pair must permit the distance inequality.
Unsupported shapes are removed from every cell's options, then tighter bounds
are recomputed for up to three rounds per search node. This also checks chosen
states. Reports count `candidate_support_prunes`, `support_rounds`, and
`bellman_prunes`. These are necessary conditions, not a guarantee that surviving
shapes can form a solution; sampled-pool restrictions are rebuilt after expansion.

Generation starts with states up to area 4 (forced singletons first), with
larger required areas deferred to later rounds. Per-root limits then grow
roughly by doubling up to the configured maximum; completing a smaller stage
does not mark that root exhausted at the full limit. The initial generation
pass uses at most half the time budget, leaving time for decomposition search.
Reports include `largest_generation_limit` and `initial_forbidden_capitols`.
Initial capitol exclusions use the full configured area bound, never the
smaller temporary generation limit, and count `initial_capitol_prunes`.

Failed partial partitions are cached by per-cell area and capitol locations,
ignoring alternative equal-area borders only when those quantities agree.
This preserves travel costs while retaining real symmetric shapes for final
validation. The cache resets when the pool grows; `equivalent_partition_prunes`
counts repeated failed configurations skipped within a pool.

The solver caches starting-clue deductions once for backtracking. When a sampled
pool is exhausted, it uses remaining time to expand candidate generation in
batches, prioritizing smaller next area limits and fewer clue-compatible areas,
then less-explored roots and cells with coverage failures.
Longer generation budgets reach beyond earlier samples. Each enlarged pool
restarts partition search because earlier pool-dependent rejections do not
apply to the new candidates. Reports count `search_rounds`, `expansion_batches`,
and `generation_calls`. Generation remains bounded, not exhaustive.

Candidate generation stops growing a shape when a condition cannot be repaired
by adding squares: it contains a forced singleton, contains two zero clues,
absorbs all possible singleton neighbors of a clue 1, or encloses a positive
clue smaller than its current area. For the last rule, every orthogonal neighbor
of the clue is already inside the shape, so every first step costs at least the
current area; the positive clue itself cannot be a capitol. These tests also
apply at board edges, using only neighbors inside the board. They preserve all
locally compatible candidates in a completed search. Candidate reports expose
`branch_prunes` as counts of stopped growth branches, including repeated shapes
from different symmetry families; these are separate from examined rejections.
Small shapes rejected only for symmetry, area, or missing painted cells still
grow, since those failures can be repaired. Exhaustive connected-shape tests
cross-check the pruned generator on clue-bearing grids.

`shape_symmetry` tests each rotation/reflection by translating the transformed
shape onto the original's corner and comparing cells. The translation offset
is computed once per transform directly from the original shape's row/column
extrema (a fixed formula per transform), instead of rescanning the transformed
points for their own minimum row and column. The same pass checks for a fixed
cell under that same translation, so a shape's full symmetry and operation
metadata come from one O(size) pass per transform rather than several.
A randomized test cross-checks this against a naive brute-force version on
shapes with negative and disconnected coordinates.

The candidate pool is sampled, not exhaustive. `time_limit` and
`sample_exhausted` mean no solution was found in this run; neither proves
impossibility. States larger than the chosen maximum remain possible.
`best_partial_coverage` is only search progress, not a deduction or solution.
Increase `--per-root-seconds` (default 0.3) to spend more time generating
candidates, and increase `--seconds` to give the full run more time.
A verified solution, when found, is written in the separate report's `solution`
field as an 11-by-11 array of cell objects.

The supplied puzzle fails an optional 20-cell limit before enumeration: R11C9 has clue
77 and is three steps from the mandatory capitol at R11C6. With every state
of area at most 20, this route costs at most 60. Consequently some state has
area at least ceil(77/3) = 26. The solver returns `area_limit_contradiction`
with this witness immediately. The candidate generator and heatmap now accept areas 1–121; the combined solver
defaults to 98 (or the board area on smaller boards). Searches remain bounded samples even when the area limit covers
the entire board. Travel uses minimum total weighted cost, never fewest steps.


### Experimental area-first constraint solver

`area_solver.py` is an exact constraint-and-geometry formulation. Its mathematical
advantage is that it preserves all legal shapes up to the stated area limit,
instead of selecting a bounded sample. It remains experimental software;
a speed improvement is not required for this mathematical guarantee.
It uses OR-Tools CP-SAT to choose an area and a distance-to-capitol for every
cell before constructing large states. For every size `s`, the number of cells
assigned that area must equal `s` times an integer number of states. Each
non-capitol cell has a neighbor whose distance plus the edge cost equals its
own distance, and no adjacent route may be cheaper. Edge cost is always the
minimum of the two cell areas, including edges inside one state. Positive edge
costs make each witness chain strictly descend to a zero-distance capitol;
together these constraints characterize exact shortest-path distances.

Geometry is checked separately within each connected component of equal-area
cells. A component of `s` cells assigned area `s` has a uniquely determined
state. A larger component may contain several adjacent states of the same
size and is partitioned exhaustively within that component. If impossible,
the solver adds a constraint requiring its membership, boundary, or relevant
capitol pattern to change. A timed-out geometry check never adds a rejection.
Every completed partition still passes the existing independent validator.
This avoids an upfront pool of arbitrary large shapes, but both the numeric
constraint problem and geometric subproblems can still be expensive.

Optional installation and run on macOS/Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-cp.txt
.venv/bin/python area_solver.py --seconds 120 --workers 4 --output solver-area-report.json
.venv/bin/python -m unittest test_model test_candidates test_solver test_area_solver test_deduction_engine
```

On Windows, use `py -3 -m venv .venv` and `.venv\Scripts\python.exe` for the
remaining commands. The original `solver.py` and editor need no new packages.
The area solver defaults to one worker; `--workers 4` permits four CPU workers.
Only `verified_solution` is solved. `last_relaxed_assignment`, when present,
is diagnostic numeric data and is **not** a legal partition or solution.
`infeasible_within_area_limit` is conditional on `--max-area` (default 121);
`time_limit` proves neither feasibility nor impossibility.

Initial measurements on the supplied puzzle: the bare area-first model timed
out after both 30 and 90 seconds with four workers, before its first complete
numeric assignment. These results do **not** establish a speed improvement over the default solver.
They do not undermine the formulation's exactness or its stronger constraints;
performance and mathematical guarantees are separate criteria.

Two strengthenings were added after that measurement. A capitol can only
exist in an odd-area state (any nontrivial symmetry admitting one is an
involution, or generates one, so non-capitol cells pair up evenly and
area = 1 + 2k); crediting even-area state counts toward the total capitol
budget left extra slack, not merely a restatement of the per-cell
parity rule, so the capitol count is now bounded by odd-area state counts
only. Separately, sizes 2 and 3 are given every one of their actual
symmetric placements on the board as selectable templates (220 dominoes,
598 trominoes), with per-cell coverage tied exactly to that cell's area
indicator and each placement forcing its real capitol pattern; this removes
"fake" small-area patterns with no possible geometric realization, which the
bare numeric relaxation could not otherwise distinguish from real ones.

Re-measuring on the supplied puzzle with both strengthenings (4 workers):
still no first feasible assignment within 30 seconds at the full `max_area`
(121), nor within 20 seconds at smaller limits (30, 60). These bounded runs do not establish a speedup. The area-first idea remains theoretically sound; it has not yet
been shown to outperform the default solver in practice.


### Mathematical guarantees of the area formulation

This argument concerns the supplied connected board with finite distance clues,
so at least one capitol must exist. It does not represent clue-free partitions
with no capitols and hence undefined/infinite nearest-capitol distances.
Assume positive integer state areas at most `M = max_area`.

**Exact distances from local equations.** Let `A(v)` be a cell's state area,
`C(v)` its capitol flag, and `D(v)` its nonnegative integer distance. Every
edge has weight `w(u,v) = min(A(u), A(v))`: when two cells share a state their
areas are equal, so the formula also gives the stipulated internal cost.
The model requires:

- `D(v) = 0` exactly at flagged capitols.
- `D(v) <= D(u) + w(u,v)` on every directed adjacency.
- At each non-capitol, equality holds for at least one adjacent cell `u`.

Summing the inequalities along any route to a capitol proves `D(v)` is no
greater than that route's cost. Conversely, repeatedly following an equality
edge strictly decreases `D`, because every edge costs at least one. On a
finite board this chain must reach a capitol; telescoping gives a route of
cost exactly `D(v)`. Therefore `D(v)` is precisely the shortest distance,
not just a lower or upper bound. A shortest route is simple and has at most
120 edges, so the domain bound `D <= 120*M` loses no solution. Upper bounds
from known clues/capitols using maximum edge costs are also necessary bounds.

**Every legal partition satisfies the numeric model.** Its true areas, capitols
and distances satisfy the equations above and the starting clues. If `n_s`
states have size `s`, exactly `s*n_s` cells have that size. Every cell in a
multi-cell connected state has a same-area neighbor. A singleton is its own
capitol. A capitol-bearing state has odd area: some reflection or half-turn
symmetry is present (a quarter-turn also implies a half-turn), and an
involution with exactly one fixed square pairs all the other squares.
Each state has at most one capitol, so their total cannot exceed the number
of odd-area states. Exact small-state placement constraints retain every
legal size-2 and size-3 state because those placement lists are exhaustive.
The existing clue deductions used as initial bounds are necessary conditions.

**Why geometry can be checked component by component.** Every connected state
of area `s` lies wholly inside a connected component of cells labeled `s`.
Such a component may contain several adjacent states; its cell count must be
a multiple of `s`. The geometric subproblem enumerates every connected size-s
subset containing the least-index remaining cell, checks its full symmetry
and derived capitol, and recursively covers the remainder. Each valid cover
has such a first state, so this recursion omits none. Different components
are independent for geometry. Choosing a different valid partition inside
one component changes neither its cell areas nor its agreed capitol flags,
and therefore changes none of the weighted distances.

**Why learned rejections are sound.** For a rejected component, the added
constraint permits a member to change area, a boundary neighbor to join its
area, or (when relevant) its capitol pattern to change. If none changes,
exactly the same impossible local geometry remains, regardless of the rest
of the board. Rejecting that conjunction cannot discard a legal partition.
Area-only failures do not need a capitol-pattern condition. A geometry timeout
is never treated as failure and never justifies a rejection.

**What a result proves.** A returned partition passes all component checks and
the independent puzzle validator. Conversely, every legal partition has a
numeric assignment that survives every sound rejection. There are finitely
many area/capitol assignments, and each rejection removes the current one;
with exhaustive subproblem solving and sufficient resources the procedure
can find a solution or exhaust them. This is a completeness statement about
the formulation, not a promise that a chosen time budget is enough.
`infeasible_within_area_limit` rules out legal partitions with areas at most
`M`; when `M=121`, that covers every possible state on this board. A timeout
or an unfinished numeric assignment proves no such conclusion.

The sampled solver's exhausted pool cannot give that impossibility guarantee,
even with a 121-cell area limit. Both solvers independently validate any
solution they return. Neither the tests nor this argument establish uniqueness
of a returned solution; uniqueness would require excluding it and solving again.


### Explained deduction without branching

`python3 deduction_engine.py --output solver-deduction-report.json` repeatedly
shrinks full area domains and distance intervals using necessary conditions.
It considers all state areas from 1 to 121 and makes no speculative assignments.
Every change records the rule, affected cell, eliminated areas or tightened
interval, and its explanation. The output is a trace of sound eliminations,
not a machine-checked formal proof certificate.

The weighted distance inequalities propagate in both directions using maximum
possible edge costs. Minimum possible edge costs to every still-possible
capitol give additional lower bounds. To test an area value at a cell, the
engine bounds every adjacent edge under that value and checks whether the cell
can still be a capitol or have a neighbor satisfying the exact descending
shortest-path equation. If neither is possible, that area is eliminated.
Allowing extra hypothetical capitols or independently supported neighbors
only weakens these deductions; it cannot remove a real solution.

The process repeats until no rule changes anything. Domains and intervals
only shrink, so on the finite board it reaches a fixed point or a contradiction.
`deduction_fixed_point` means these rules have no further deduction; it does
not mean the puzzle is solved or every surviving area can be realized.
`contradiction` means the rules have derived inconsistent necessary conditions
from the supplied clues. No arbitrary area cutoff or sampled-shape assumption
is involved. The same finite-distance scope as the area formulation applies.

Three further rules narrow domains without any branching. A named two-step
route bound gives the same conclusion the general rule above would reach, but
with a short, specific reason: for a cell with two distinct neighbors u, v,
the two-edge route u-to-cell-to-v has each edge costing at
most the cell's own area, so twice that area is at least `distance(u) -
distance(v)`. On the supplied puzzle this names, for example, why R3C4 and
R4C3 (each adjacent to both R3C3=7 and R4C4=51) must have area at least 22.

An inventory rule tracks, for each area value `s`, the connected region of
cells whose domain still admits `s`. Let `L` be the cells in that region
already forced to exactly `s`, and `U` the region's whole size. The number
of area-`s` cells eventually realized there is some multiple of `s` in
`[L, U]`: if no such multiple exists the clues are contradictory now (domains
only shrink, so an empty range never reopens); if the only such multiple
equals `L`, no other cell in the region can become area `s`; if it equals
`U`, every remaining cell in the region must become area `s`. A multiple
strictly between `L` and `U` fixes the eventual count without saying which
cells realize it, so no domain action follows from that case alone.

A global capitol-count rule bounds every cell's largest possible area from
a lower bound `K` on the total number of distinct capitols: cells already
certain to be capitols, plus clue-1 cells whose still-possible singleton
neighbors are pairwise disjoint (overlapping neighbor sets can share one
capitol; only disjoint ones force separate ones, greedily packed smallest
first). Any single state leaves room for the other capitol-bearing states
elsewhere on the board, so an odd-area state is at most `121-K+1` and an
even-area state (which can never itself hold a capitol) is at most `121-K`.
On the supplied puzzle K is at least 4: the two zero clues, the forced
singleton at R6C11, and at least one more required by the clue 1 at R3C6,
whose neighbors avoid those three known capitols. The clue-1 neighbor groups
at R3C6 and R4C7 overlap, so they are not counted as two extra capitols.

Together with the original rules, these currently remove 609 area
possibilities from the 14,225 remaining across all 121 cells after the
initial clue deductions over 3 rounds, leaving only the already-known
forced singleton pinned to a single area. That is real, verified progress
through pure deduction, not a solved puzzle -- most cells still have a wide
range of possible areas.


The exact `area_solver.py` now runs this deduction engine before constructing
its search model. The resulting area domains and distance intervals become
hard constraints. Thus these mathematical deductions strengthen the solving
process as well as providing a separately readable explanation report.
The existing correctness argument applies because every added restriction is
a necessary condition for a legal partition. Historical timings above predate
this preprocessing; no new speed claim is being made.

Rust verification:

```sh
cargo test --manifest-path rust-solver/Cargo.toml
python3 -m unittest test_rust_solver
```

The Rust geometry tests compare all 511 nonempty 3×3 cell sets against frozen
Python reference results and compare orbit enumeration with brute force. Native
integration tests independently validate the supplied 5×5 solution and check
timeouts, invalid clues, and rejection of incorrectly claimed solutions. Neither
engine guarantees a solution within a time limit; sampled failure is inconclusive.
