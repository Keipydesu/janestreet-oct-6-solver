"""Native integration checks: build release binary before running."""
import json
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from model import GridState
from starting_grid import new_workspace
from rust_solver import BINARY, solve


@unittest.skipUnless(BINARY.is_file(), 'Build Rust release binary first')
class RustSolverTests(unittest.TestCase):
    def test_small_solution_independently_validated_and_input_unchanged(self):
        state = new_workspace(5).saved
        before = state.to_dict()
        report = solve(state, seconds=5)
        self.assertEqual(report['status'], 'verified_solution')
        self.assertEqual(report['independent_validation'], 'Python model passed')
        self.assertTrue(GridState.from_dict(report['solution']).validate_puzzle()['puzzle_valid'])
        self.assertEqual(state.to_dict(), before)

    def test_timeout_does_not_claim_impossible(self):
        report = solve(new_workspace().saved, seconds=0)
        self.assertEqual(report['status'], 'time_limit')
        self.assertEqual(report['max_area'], 98)
        self.assertIsNone(report['solution'])

    def test_invalid_native_input_is_error(self):
        for value in ([[True]], [[-1]], [[0, 1]], [[1.5]]):
            result = subprocess.run([str(BINARY), '--input', '-'], input=json.dumps(value),
                                    text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(result.stdout)

    def test_bridge_rejects_false_verified_report(self):
        state = new_workspace(5).saved
        result = subprocess.CompletedProcess([], 0, json.dumps({
            'status': 'verified_solution', 'solution': state.to_dict()}), '')
        with patch('rust_solver.subprocess.run', return_value=result):
            with self.assertRaisesRegex(ValueError, 'independent Python validation'):
                solve(state)

    def test_saved_run_resumes_and_rejects_changed_clues(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'progress.json'
            state = new_workspace().saved
            first = solve(state, seconds=.1, checkpoint=path)
            second = solve(state, seconds=.1, checkpoint=path)
            self.assertFalse(first['resumed'])
            self.assertTrue(second['resumed'])
            self.assertEqual(second['checkpoint_runs'], 2)
            self.assertGreater(second['generation_nodes'], first['generation_nodes'])
            self.assertGreaterEqual(second['candidate_count'], first['candidate_count'])
            self.assertGreater(second['total_elapsed_seconds'], first['total_elapsed_seconds'])
            changed = GridState.from_dict(state.to_dict())
            changed.grid[0][0].starting_number = 0
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'does not match'):
                solve(changed, seconds=0, checkpoint=path)
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaisesRegex(ValueError, 'does not match'):
                solve(state, seconds=0, max_area=97, checkpoint=path)
            fresh = solve(state, seconds=0, checkpoint=path, fresh=True)
            self.assertFalse(fresh['resumed'])
            self.assertEqual(fresh['generation_nodes'], 0)
            self.assertEqual(fresh['checkpoint_runs'], 1)

    def test_saved_solution_is_revalidated_on_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'progress.json'
            state = new_workspace(5).saved
            first = solve(state, seconds=5, checkpoint=path)
            second = solve(state, seconds=0, checkpoint=path)
            self.assertEqual(first['status'], 'verified_solution')
            self.assertEqual(second['status'], 'verified_solution')
            self.assertEqual(second['independent_validation'], 'Python model passed')
            self.assertEqual(first['solution'], second['solution'])
            self.assertEqual(first['generation_nodes'], second['generation_nodes'])

    def test_corrupt_checkpoint_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'progress.json'
            path.write_text('{broken')
            with self.assertRaisesRegex(ValueError, 'Cannot read checkpoint'):
                solve(new_workspace().saved, seconds=0, checkpoint=path)
            self.assertEqual(path.read_text(), '{broken')

    def test_concurrent_checkpoint_is_locked(self):
        import fcntl
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'progress.json'
            with Path(str(path) + '.lock').open('w') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(ValueError, 'already in use'):
                    solve(new_workspace().saved, seconds=0, checkpoint=path)

    def test_periodic_checkpoint_survives_process_termination(self):
        import time
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'progress.json'
            state = new_workspace().saved
            process = subprocess.Popen(
                [str(BINARY), '--input', '-', '--seconds', '30', '--checkpoint', str(path)],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                process.stdin.write(json.dumps(state.to_dict()))
                process.stdin.close()
                deadline = time.monotonic() + 15
                saved = None
                while time.monotonic() < deadline and process.poll() is None:
                    if path.exists():
                        current = json.loads(path.read_text())
                        if current['generation_nodes'] > 0:
                            saved = current
                            break
                    time.sleep(.05)
                self.assertIsNotNone(saved, 'No periodic progress checkpoint appeared')
                process.terminate()
                process.wait(timeout=5)
                resumed = solve(state, seconds=0, checkpoint=path)
                self.assertTrue(resumed['resumed'])
                self.assertGreater(resumed['generation_nodes'], 0)
                self.assertEqual(resumed['generation_nodes'], saved['generation_nodes'])
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                process.stderr.close()

    def test_native_rejects_checkpoint_output_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'progress.json'
            result = subprocess.run([str(BINARY), '--input', '-', '--seconds', '0',
                                     '--checkpoint', str(path), '--output', str(path)],
                                    input='[[0]]', text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('different files', result.stderr)
            self.assertFalse(path.exists())

    def test_native_rejects_new_output_through_symlink_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / 'real'
            real.mkdir()
            alias = root / 'alias'
            alias.symlink_to(real, target_is_directory=True)
            result = subprocess.run([str(BINARY), '--input', '-', '--seconds', '0',
                                     '--checkpoint', str(real / 'new.json'),
                                     '--output', str(alias / 'new.json')],
                                    input='[[0]]', text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('different files', result.stderr)
            self.assertFalse((real / 'new.json').exists())

    def test_checkpoint_named_lock_does_not_replace_lock_inode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'progress.lock'
            solve(new_workspace().saved, seconds=0, checkpoint=path)
            self.assertTrue(path.exists())
            lock = Path(str(path) + '.lock')
            self.assertTrue(lock.exists())
            before = lock.stat().st_ino
            solve(new_workspace().saved, seconds=0, checkpoint=path)
            self.assertEqual(lock.stat().st_ino, before)

    def test_clue_one_contradiction(self):
        result = subprocess.run([str(BINARY), '--input', '-'], input='[[1]]',
                                text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no possible adjacent singleton', result.stderr)


if __name__ == '__main__':
    unittest.main()
