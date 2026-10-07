"""Export the complete locally built image and an offline installation bundle."""
import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGE = 'helidata-ai-gateway:v1.0.2-offline'
IMAGE_FILE = 'helidata-ai-gateway-v1.0.2-image.tar.gz'
BUNDLE = 'helidata-ai-gateway-v1.0.2-linux-amd64-offline.tar.gz'
CHECKSUMS = 'helidata-ai-gateway-v1.0.2-linux-amd64-SHA256SUMS'

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
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for name in (IMAGE_FILE, BUNDLE, CHECKSUMS):
        if (output / name).exists():
            parser.error(f'输出文件已存在：{output / name}')
    info = json.loads(subprocess.check_output(['docker', 'image', 'inspect', IMAGE]))[0]
    if (info['Os'], info['Architecture']) != ('linux', 'amd64'):
        parser.error('镜像必须为 linux/amd64')
    with tempfile.TemporaryDirectory(dir=output, prefix='.offline-build-') as temporary:
        stage = Path(temporary) / 'helidata-ai-gateway-v1.0.2-linux-amd64'
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
        archive = stage / 'images' / IMAGE_FILE
        archive.parent.mkdir()
        with archive.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', compresslevel=1, mtime=0) as compressed:
            with subprocess.Popen(['docker', 'save', IMAGE], stdout=subprocess.PIPE) as process:
                shutil.copyfileobj(process.stdout, compressed, 1024 * 1024)
                if process.wait():
                    raise RuntimeError('docker save 失败')
        (stage / 'image-id.txt').write_text(info['Id'] + '\n', encoding='utf-8')
        manifest = dict(version='1.0.2', database_revision='0031', image=IMAGE,
                        image_id=info['Id'], platform='linux/amd64', source_commit=args.commit,
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
