"""Run with python3 app.py; only Python's standard library is required."""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import threading
import webbrowser
from model import Workspace, GridState
from starting_grid import new_workspace

ROOT = Path(__file__).resolve().parent

def make_server(project, port=8000, workspace=None):
    project = Path(project)
    workspace = workspace if workspace is not None else (Workspace.load(project) if project.exists() else new_workspace())
    projects = {'': project, '/small': project.with_name(project.stem + '-small' + project.suffix)}
    workspaces = {'': workspace}
    decompositions = {}
    def get_workspace(prefix):
        if prefix not in workspaces:
            path = projects[prefix]
            workspaces[prefix] = Workspace.load(path) if path.exists() else new_workspace(5)
        return workspaces[prefix]
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, body, content_type='application/json'):
            body = body.encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)

        def allowed_host(self):
            return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

        def do_GET(self):
            if not self.allowed_host():
                return self.respond(403, '{}')
            prefix = '/small' if self.path == '/small' or self.path.startswith('/small/') else ''
            path = self.path[len(prefix):] or '/'
            workspace = get_workspace(prefix)
            if path == '/':
                return self.respond(200, (ROOT / 'index.html').read_text().replace('__TOKEN__', token).replace('__SIZE__', str(workspace.saved.size)).replace('__AREA__', str(workspace.saved.size ** 2)).replace('__API_BASE__', prefix + '/api/'), 'text/html')
            if path == '/api/state':
                return self.respond(200, json.dumps(workspace.payload()))
            self.respond(404, '{}')

        def do_POST(self):
            prefix = '/small' if self.path.startswith('/small/') else ''
            path = self.path[len(prefix):]
            workspace = get_workspace(prefix)
            project = projects[prefix]
            if not self.allowed_host() or self.headers.get('X-Grid-Token') != token:
                return self.respond(403, json.dumps({'error': 'Invalid request token.'}))
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length < 100000:
                    raise ValueError('Invalid request size.')
                data = json.loads(self.rfile.read(length))
                if path == '/api/decompose':
                    from rust_solver import solve
                    mode = data.get('mode', 'main')
                    if mode not in ('main', 'experimental'):
                        raise ValueError('Unknown grid mode.')
                    grid = workspace.experimental if mode == 'experimental' else workspace.saved
                    report = solve(grid, seconds=8, per_root_seconds=.08, checkpoint='auto')
                    decompositions[prefix] = report
                    return self.respond(200, json.dumps(report))
                if path == '/api/apply-decomposition':
                    report = decompositions.get(prefix, {})
                    if report.get('status') != 'verified_solution':
                        raise ValueError('Find a verified decomposition first.')
                    workspace.experimental = GridState.from_dict(report['solution'])
                    workspace.histories['experimental'].record(
                        workspace.experimental.to_dict(), 'Verified whole-board decomposition')
                    return self.respond(200, json.dumps(workspace.payload()))
                if path == '/api/heatmap':
                    mode = data.get('mode', 'main')
                    if mode not in ('main', 'experimental'):
                        raise ValueError('Unknown grid mode.')
                    grid = workspace.experimental if mode == 'experimental' else workspace.saved
                    kind = data.get('kind', 'heatmap')
                    if kind == 'statecounts':
                        from state_counts import state_count_heatmap
                        return self.respond(200, json.dumps(state_count_heatmap(grid, data.get('max_area'))))
                    if kind == 'candidates':
                        row, col = data['source']
                        return self.respond(200, json.dumps(grid.candidate_states(row,col,data.get('max_area',7),respect_paint=data.get('respect_paint',False),respect_stars=data.get('respect_stars',False),check_borders=True)))
                    if kind == 'deductions':
                        return self.respond(200, json.dumps(grid.deductions()))
                    if kind == 'partial':
                        return self.respond(200, json.dumps(grid.validate_partial(include_paths=True)))
                    if kind == 'validation':
                        return self.respond(200, json.dumps(grid.validate_puzzle()))
                    if kind == 'allheat':
                        return self.respond(200, json.dumps(grid.all_clues_heatmap(data.get('aggregation', 'count'), data.get('use_region_sizes', True))))
                    if kind == 'smartheat':
                        return self.respond(200, json.dumps(grid.smart_heatmap(data.get('use_derived_capitals', True))))
                    if kind != 'heatmap':
                        raise ValueError('Unknown heatmap type.')
                    row, col = data['source']
                    weighted = data.get('use_region_sizes', True)
                    method = grid.weighted_movement_heatmap if weighted else grid.movement_heatmap
                    heatmap = method(row, col, data.get('within_region', False))
                    return self.respond(200, json.dumps({'heatmap': heatmap, 'source': [row, col],
                        'budget': grid.grid[row][col].starting_number, 'use_region_sizes':weighted,
                        'uncolored_count':sum(cell.region_color is None for row in grid.grid for cell in row)}))
                if path == '/api/edit':
                    workspace.edit(data['layer'], data['cells'], data['value'], data.get('target'))
                elif path == '/api/history':
                    workspace.restore_history(data['layer'], data['index'])
                elif path == '/api/reset-experiment':
                    workspace.reset_experiment()
                elif path == '/api/save':
                    workspace.save(project)
                elif path == '/api/load':
                    workspace = Workspace.load(project)
                    workspaces[prefix] = workspace
                else:
                    return self.respond(404, '{}')
                self.respond(200, json.dumps(workspace.payload()))
            except (ValueError, KeyError, TypeError, OSError, OverflowError) as exc:
                self.respond(400, json.dumps({'error': str(exc)}))

    return HTTPServer(('127.0.0.1', port), Handler)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--project', type=Path, default=ROOT / 'project.json')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    try:
        server = make_server(args.project, args.port)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f'Could not open editor: {exc}\n')
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Grid editor: {url}\nProject: {args.project}\nPress Ctrl+C to stop.', flush=True)
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
