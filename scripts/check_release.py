"""Reject non-portable shell files before releasing a source tree or bundle."""
import argparse
from pathlib import Path

def check_shell_files(root):
    failures=[]
    for path in root.rglob('*.sh'):
        if any(part in ('.git','.deployment','node_modules','.venv','__pycache__','releases') for part in path.relative_to(root).parts):continue
        data=path.read_bytes()
        if b'\r' in data or data.startswith(b'\xef\xbb\xbf'):failures.append(str(path.relative_to(root)))
    if failures:raise ValueError('Shell scripts require LF without BOM: '+', '.join(failures))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('root',type=Path,nargs='?',default=Path(__file__).resolve().parents[1]);args=parser.parse_args()
    check_shell_files(args.root.resolve());print('Release shell LF check PASS')
