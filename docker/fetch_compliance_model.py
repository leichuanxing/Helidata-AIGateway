"""Download pinned official Hub artifacts; verify both files before atomic install."""
from pathlib import Path
import urllib.request,hashlib,os,json
root=Path(__file__).resolve().parents[1]/'models'/'compliance';root.mkdir(parents=True,exist_ok=True)
repo='Xenova/multilingual-e5-small';revision='761b726dd34fb83930e26aab4e9ac3899aa1fa78'
files=[('onnx/model_quantized.onnx','model.onnx','f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193'),('tokenizer.json','tokenizer.json','0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39')]
for source,name,digest in files:
 dest=root/name
 if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest()==digest:continue
 temp=root/(name+'.download')
 try:
  with urllib.request.urlopen(f'https://huggingface.co/{repo}/resolve/{revision}/{source}',timeout=40) as r,temp.open('wb') as w:
   while True:
    chunk=r.read(1024*1024)
    if not chunk:break
    w.write(chunk)
  assert hashlib.sha256(temp.read_bytes()).hexdigest()==digest,'model digest mismatch'
  os.replace(temp,dest)
 finally:
  if temp.exists():temp.unlink()
(root/'manifest.json').write_text(json.dumps({'repository':repo,'revision':revision,'files':{name:digest for _,name,digest in files}}),encoding='utf-8')
print('Pinned local compliance model verified')
