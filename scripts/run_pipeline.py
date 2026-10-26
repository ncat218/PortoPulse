"""Run one explicit, bounded phase of the independent 10 km experiment."""
import argparse
import json
import sys
import traceback
import shutil
from pathlib import Path

import yaml
from portoflow import pipeline as region


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=['all', 'graph', 'scan', 'match', 'report'], required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--plan', type=Path, default=Path('configs/study_area.yaml'))
    parser.add_argument('--config', type=Path, default=Path('configs/default.yaml'))
    parser.add_argument('--authorize-run', choices=[region.TOKEN], required=True)
    args = parser.parse_args()
    plan = yaml.safe_load(args.plan.read_text(encoding='utf-8')); region.validate_plan(plan)
    config = region.scientific_config(plan, args.config)
    args.work.mkdir(parents=True, exist_ok=True)
    try:
        phases = ['graph', 'scan', 'match', 'report'] if args.phase == 'all' else [args.phase]
        if 'scan' in phases and args.source is None:
            parser.error('--source is required for scan/all')
        if 'match' in phases and sys.version_info[:2] != (3, 12):
            raise ValueError('Native matching uses the verified Python 3.12 runtime')
        if ('graph' in phases and not (args.work/'region.json').is_file() and
                not (args.work/'graph/graph_metadata.json').is_file() and
                (Path(__file__).resolve().parents[1]/'data/region.json').is_file()):
            source = Path(__file__).resolve().parents[1]/'data'
            for name in ('graph', 'context_graph'):
                shutil.copytree(source/name, args.work/name, dirs_exist_ok=True)
            shutil.copyfile(source/'region.json', args.work/'region.json')
        for phase in phases:
            if phase == 'graph':
                result = region.fetch_region(args.work, plan)
            elif phase == 'scan':
                result = region.scan_source(args.source, args.work, plan, config)
            elif phase == 'match':
                result = region.run_matching(args.work, plan, config)
            else:
                from report_recovery import recover
                result = recover(args.work, args.work/'portoflow_recovery', plan['report_timeout_seconds'])
                region.atomic_json(args.work/'result_summary.json', result)
            if phase == 'match' and not result['all_eligible_complete'] and args.phase == 'all':
                print('Matching session partial; generating current report. Resume the same work for remaining parents.', flush=True)
        print(json.dumps(result, default=str, indent=2), flush=True)
    except Exception:
        (args.work/'BLOCKER.txt').write_text(traceback.format_exc(), encoding='utf-8')
        raise


if __name__ == '__main__':
    main()
