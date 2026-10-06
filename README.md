# Jane Street grid puzzle solver

A local grid editor and CPU solver for the supplied 11-by-11 state/capitol puzzle.
Uses Python's standard library only; no pip packages or GPU are required.
The solver currently runs in one process (no multicore parallelism).
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
It starts from the clues in `starting_grid.py`. Save stores your local work in
`project.json`; saved sessions, backups, and generated reports are ignored by Git.
The server binds only to localhost and generates a fresh edit token at startup.

## Tests

```powershell
py -3 -m unittest test_model test_candidates test_solver
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

Run `python3 solver.py --seconds 120 --output solver-report.json` to combine
clue deductions, symmetric candidate states (up to 121 cells), non-overlapping
full-board coverage, and global weighted shortest-path bounds. The search
chooses the uncovered cell with fewest compatible candidates and backtracks.
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

The solver caches starting-clue deductions once for backtracking. When a sampled
pool is exhausted, it uses remaining time to expand candidate generation in
batches, prioritizing less-explored roots and cells with coverage failures.
Longer generation budgets reach beyond earlier samples. Each enlarged pool
restarts partition search because earlier pool-dependent rejections do not
apply to the new candidates. Reports count `search_rounds`, `expansion_batches`,
and `generation_calls`. Generation remains bounded, not exhaustive.

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
defaults to 121. Searches remain bounded samples even when the area limit covers
the entire board. Travel uses minimum total weighted cost, never fewest steps.
