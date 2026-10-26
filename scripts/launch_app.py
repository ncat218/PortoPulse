"""Launch this project's own app and optional reviewed/candidate export."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', type=Path)
    parser.add_argument('--port', type=int, default=8502)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Invalid port')
    environment = dict(os.environ, PYTHONPATH=str(ROOT/'src'), STREAMLIT_BROWSER_GATHER_USAGE_STATS='false')
    if args.export:
        export = args.export.resolve()
        if not (export/'run_metadata.json').is_file():
            parser.error('Export manifest is missing')
        environment['PORTOFLOW_ARTIFACTS'] = str(export)
    return subprocess.call([sys.executable, '-m', 'streamlit', 'run', str(ROOT/'app/streamlit_app.py'),
        '--server.address', 'localhost', '--server.port', str(args.port), '--browser.gatherUsageStats', 'false'],
        cwd=ROOT, env=environment)


if __name__ == '__main__':
    raise SystemExit(main())
