"""Export the complete locally built image and an offline installation bundle."""
import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGE = 'helidata-ai-gateway:v1.0.9-offline'
IMAGE_FILE = 'helidata-ai-gateway-v1.0.9-image.tar.gz'
BUNDLE = 'helidata-ai-gateway-v1.0.9-linux-amd64-offline.tar.gz'
CHECKSUMS = 'helidata-ai-gateway-v1.0.9-linux-amd64-SHA256SUMS'

def digest(path):
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'releases')
    parser.add_argument('--commit', required=True)
    parser.add_argument('--source-dirty', action='store_true', help='构建包含尚未提交的源码修改')
    args = parser.parse_args()
    sys.path.insert(0,str(ROOT/'scripts'))
    from check_release import check_shell_files
    check_shell_files(ROOT)
    # The scripts packaged below must belong to the recorded immutable commit.
    if args.source_dirty:parser.error('发布包必须使用干净的指定提交；请先提交，再使用 git archive 解压目录构建')
    if (ROOT/'.git').exists():
        revision=subprocess.check_output(['git','rev-parse',args.commit],cwd=ROOT,text=True).strip()
        if revision!=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip():parser.error('指定提交与当前检出不一致')
        if subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=ROOT,text=True).strip():parser.error('工作区存在未提交修改，请使用 git archive 构建')
    elif not (ROOT/'.source-commit').is_file() or (ROOT/'.source-commit').read_text().strip()!=args.commit:
        parser.error('请使用 scripts/export_release.py 导出的源码，并传入其完整提交 SHA')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for name in (IMAGE_FILE, BUNDLE, CHECKSUMS):
        if (output / name).exists():
            parser.error(f'输出文件已存在：{output / name}')
    info = json.loads(subprocess.check_output(['docker', 'image', 'inspect', IMAGE]))[0]
    if (info['Os'], info['Architecture']) != ('linux', 'amd64'):
        parser.error('镜像必须为 linux/amd64')
    revision=subprocess.check_output(['docker','run','--rm','--pull=never','--network','none','--entrypoint','python',IMAGE,
        '-c',"from alembic.config import Config; from alembic.script import ScriptDirectory; print(ScriptDirectory.from_config(Config('/app/backend/alembic.ini')).get_current_head())"],text=True).strip()
    if revision!='0036':parser.error('镜像数据库迁移与发布源码不一致')
    with tempfile.TemporaryDirectory(dir=output, prefix='.offline-build-') as temporary:
        stage = Path(temporary) / 'helidata-ai-gateway-v1.0.9-linux-amd64'
        stage.mkdir()
        for source, target in (
            ('offline/deploy-offline.sh', 'deploy-offline.sh'),
            ('offline/start-offline.sh', 'start-offline.sh'),
            ('offline/stop-offline.sh', 'stop-offline.sh'),
            ('offline/README.md', 'README.md'),
            ('start.sh', 'start.sh'), ('stop.sh', 'stop.sh'),
            ('scripts/application.sh', 'scripts/application.sh'),
        ):
            destination = stage / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source, destination)
            destination.chmod(0o755 if target.endswith('.sh') else 0o644)
        check_shell_files(stage)
        archive = stage / 'images' / IMAGE_FILE
        archive.parent.mkdir()
        with archive.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', compresslevel=1, mtime=0) as compressed:
            with subprocess.Popen(['docker', 'save', IMAGE], stdout=subprocess.PIPE) as process:
                shutil.copyfileobj(process.stdout, compressed, 1024 * 1024)
                if process.wait():
                    raise RuntimeError('docker save 失败')
        (stage / 'image-id.txt').write_text(info['Id'] + '\n', encoding='utf-8')
        manifest = dict(version='1.0.9', database_revision='0036', image=IMAGE,
                        image_id=info['Id'], platform='linux/amd64', source_commit=args.commit,
                        source_dirty=args.source_dirty,
                        image_sha256=digest(archive), image_bytes=archive.stat().st_size)
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        entries = sorted(path for path in stage.rglob('*') if path.is_file())
        (stage / 'SHA256SUMS').write_text(''.join(f'{digest(path)}  {path.relative_to(stage).as_posix()}\n' for path in entries), encoding='utf-8')
        bundle = Path(temporary) / BUNDLE
        with tarfile.open(bundle, 'w:gz', compresslevel=1) as tar:
            tar.add(stage, arcname=stage.name)
        shutil.move(bundle, output / BUNDLE)
        shutil.move(archive, output / IMAGE_FILE)
        (output / CHECKSUMS).write_text(''.join(f'{digest(output / name)}  {name}\n' for name in (BUNDLE, IMAGE_FILE)), encoding='utf-8')
    print(json.dumps({'bundle': str(output / BUNDLE), 'image': str(output / IMAGE_FILE), 'image_id': info['Id']}))

if __name__ == '__main__':
    main()
