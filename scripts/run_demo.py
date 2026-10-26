"""Prepare the included real-data preview once, then launch the local app."""
import argparse
import subprocess
import sys
from pathlib import Path

from prepare_app_preview import prepare,sha
from portoflow.storage import verify_checkpoint

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review',type=Path,default=ROOT/'notebooks/portoflow_final_review.zip')
    parser.add_argument('--output',type=Path,default=ROOT/'runs/demo')
    parser.add_argument('--port',type=int,default=8502)
    args=parser.parse_args()
    if not args.review.is_file():
        parser.error('Missing bundled review ZIP: '+str(args.review))
    if args.output.exists():
        metadata=verify_checkpoint(args.output)
        if not metadata.get('preview_only') or metadata.get('source_review_zip_sha256')!=sha(args.review):
            parser.error('Existing preview belongs to another source; choose a new --output folder')
    else:
        prepare(args.review,args.output)
    return subprocess.call([sys.executable,str(ROOT/'scripts/launch_app.py'),'--export',str(args.output),
                            '--port',str(args.port)],cwd=ROOT)


if __name__=='__main__':
    raise SystemExit(main())
