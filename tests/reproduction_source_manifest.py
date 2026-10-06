"""Record public candidate source hashes without modifying the previous release archive."""
import argparse,hashlib,json,re
from pathlib import Path

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--preview-image',required=True);args=parser.parse_args()
assert re.fullmatch(r'sha256:[0-9a-f]{64}',args.preview_image),'Use the verified Docker image ID'
files=[]
for folder in ('backend','frontend','docker','tests'):
    for p in (root/folder).rglob('*'):
        if p.is_file() and not any(part in ('node_modules','dist','__pycache__','.git','.venv') for part in p.relative_to(root).parts):
            if p.suffix in ('.py','.ts','.vue','.css','.json','.mjs','.conf','.sh','.txt','.ini','.mako','.html','.svg','.yaml','.yml','.toml') or p.name.startswith('Dockerfile'):
                files.append(p)
files.extend(p for p in (root/'docs').glob('reproduction-*') if p.is_file() and p.name!='reproduction-candidate-manifest.json')
files.extend(root/p for p in ('README.md','.dockerignore','config/config.yaml.example','docs/product-reproduction.md','docs/current-status.md') if (root/p).is_file())
manifest={'status':'in_progress_not_deployed','verified_date':'2026-10-06','migration':'0022',
    'preview_image':args.preview_image,
    'production_image':'sha256:c0c485786bcc56cfe8874f689be93cd5cb9be7c543bee3dcf40a5f1ec4451204',
    'files':{p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(files))}}
target=root/'docs/reproduction-candidate-manifest.json';target.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Candidate manifest:',len(manifest['files']),'public source/evidence files; previous release untouched.')
