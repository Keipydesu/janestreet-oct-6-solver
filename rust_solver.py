"""JSON boundary to the native decomposition engine; Python validates solutions."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
from model import GridState
from starting_grid import new_workspace

ROOT = Path(__file__).resolve().parent
BINARY = ROOT / 'rust-solver' / 'target' / 'release' / 'decomposition'


def resolve_checkpoint(state, max_area, checkpoint):
    if checkpoint == 'auto':
        clues = [[cell.starting_number for cell in row] for row in state.grid]
        identity = json.dumps([state.size, max_area, clues], separators=(',', ':'))
        digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
        checkpoint = ROOT / '.solver-checkpoints' / f'{digest}.json'
    return checkpoint


def solve(state, seconds=120, max_area=None, per_root_seconds=.3, checkpoint=None, fresh=False):
    if not BINARY.is_file():
        raise ValueError('Build the Rust solver first: cargo build --release --manifest-path rust-solver/Cargo.toml')
    if not math.isfinite(seconds) or not 0 <= seconds <= 86400:
        raise ValueError('Seconds must be between 0 and 86400.')
    if max_area is None:
        max_area = min(98, state.size * state.size)
    if type(max_area) is not int or not 1 <= max_area <= state.size * state.size:
        raise ValueError('Maximum area is outside the board range.')
    command = [str(BINARY), '--input', '-', '--seconds', str(seconds),
               '--max-area', str(max_area), '--per-root-seconds', str(per_root_seconds)]
    checkpoint = resolve_checkpoint(state, max_area, checkpoint)
    if checkpoint is not None:
        command += ['--checkpoint', str(checkpoint)]
    if fresh:
        command += ['--fresh']
    try:
        process = subprocess.run(
            command,
            input=json.dumps(state.to_dict()), capture_output=True, text=True,
            timeout=seconds + 30,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError('Rust solver exceeded its time budget.') from exc
    if process.returncode:
        raise ValueError(process.stderr.strip() or 'Rust solver failed.')
    report = json.loads(process.stdout)
    if report.get('status') == 'verified_solution':
        result = GridState.from_dict(report['solution'])
        if result.size != state.size or any(
            result.grid[r][c].starting_number != state.grid[r][c].starting_number
            for r in range(state.size) for c in range(state.size)
        ) or not result.validate_puzzle()['puzzle_valid']:
            raise ValueError('Rust result failed independent Python validation.')
        report['independent_validation'] = 'Python model passed'
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--size', type=int, choices=(5, 11), default=11)
    parser.add_argument('--input', help='Optional editor grid or project JSON; default is supplied puzzle.')
    parser.add_argument('--seconds', type=float, default=120)
    parser.add_argument('--max-area', type=int)
    parser.add_argument('--per-root-seconds', type=float, default=.3)
    parser.add_argument('--output', default='solver-rust-report.json')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--checkpoint', default='auto', help='Checkpoint file (default: automatic file per clue set and area limit).')
    group.add_argument('--no-checkpoint', action='store_true', help='Run without saving or resuming progress.')
    parser.add_argument('--fresh', action='store_true', help='Discard the selected checkpoint and start a new search.')
    args = parser.parse_args()
    state = new_workspace(args.size).saved
    if args.input:
        value = json.loads(Path(args.input).read_text())
        state = GridState.from_dict(value.get('grid', value.get('saved')) if isinstance(value, dict) else value)
    if args.fresh and args.no_checkpoint:
        parser.error('--fresh cannot be combined with --no-checkpoint')
    checkpoint = resolve_checkpoint(state, args.max_area if args.max_area is not None else min(98, state.size ** 2),
                                    None if args.no_checkpoint else args.checkpoint)
    if checkpoint is not None and Path(checkpoint).resolve() == Path(args.output).resolve():
        parser.error('Checkpoint and output must be different files')
    report = solve(state, args.seconds, args.max_area, args.per_root_seconds,
                   checkpoint=checkpoint, fresh=args.fresh)
    Path(args.output).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'solution'}, indent=2))
