"""Export public build/API/schema artifacts from an isolated fixture only."""
from pathlib import Path
import subprocess,shutil,uuid,argparse
parser=argparse.ArgumentParser();parser.add_argument('--container',required=True);args=parser.parse_args()
root=Path('/opt/AIGateway/.deployment').resolve();fixture=args.container
assert fixture.startswith('helidata-stage20-persistence-')
subprocess.check_call(['docker','exec','-e','PYTHONPATH=/app/backend',fixture,'python','-c',"import json;from app.main import app;print(json.dumps(app.openapi(),ensure_ascii=False,indent=2))"],stdout=(root/'stage20-openapi.json').open('w'))
subprocess.check_call(['docker','exec',fixture,'runuser','-u','postgres','--','pg_dump','--schema-only','--no-owner','--no-acl','-d','helidata_gateway'],stdout=(root/'stage20-database-schema.sql').open('w'))
name='helidata-stage20-assets-'+uuid.uuid4().hex[:8];target=root/name;target.mkdir(mode=0o700)
try:
    subprocess.check_call(['docker','create','--name',name,'helidata-ai-gateway:stage20-release'],stdout=subprocess.DEVNULL)
    subprocess.check_call(['docker','cp',name+':/app/frontend/.',str(target)])
    subprocess.check_call(['docker','cp',str(target)+'/.',fixture+':/app/frontend/'])
    print('PASS: final image static assets copied to isolated browser fixture; OpenAPI and database DDL exported without records or credentials')
finally:
    subprocess.run(['docker','rm',name],check=True,stdout=subprocess.DEVNULL)
    assert target.resolve().parent==root and target.name==name
    shutil.rmtree(target)
