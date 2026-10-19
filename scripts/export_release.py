"""Export a committed, LF-validated source archive without workspace files."""
import argparse,io,subprocess,tarfile,tempfile
from pathlib import Path

def export(root,commit,output):
    revision=subprocess.check_output(['git','rev-parse',commit+'^{commit}'],cwd=root,text=True).strip()
    if output.exists():raise ValueError('Output already exists')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as folder:
        archive=Path(folder)/'source.tar'
        subprocess.run(['git','archive','--format=tar','--output',str(archive),revision],cwd=root,check=True)
        with tarfile.open(archive) as source:
            for member in source:
                if member.isfile() and member.name.endswith('.sh'):
                    data=source.extractfile(member).read()
                    if b'\r' in data or data.startswith(b'\xef\xbb\xbf'):raise ValueError('Non-LF shell file: '+member.name)
        with tarfile.open(archive,'a') as target:
            data=(revision+'\n').encode();entry=tarfile.TarInfo('.source-commit');entry.size=len(data);entry.mode=0o644
            target.addfile(entry,io.BytesIO(data))
        archive.replace(output)
    return revision

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--commit',required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    print(export(Path(__file__).resolve().parents[1],args.commit,args.output.resolve()))
