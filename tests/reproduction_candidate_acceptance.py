"""Host runner: verify isolated mount identity before executing candidate regressions."""
import json,subprocess
from pathlib import Path
root=Path('/opt/AIGateway/.deployment').resolve()
info=json.loads((root/'reproduction-ui-active.json').read_text())
name=info['name'];data=Path(info['data']).resolve()
assert name.startswith('helidata-reproduction-ui-') and data.parent==root and data.name==name
assert (data/'.reproduction-ui-isolated').read_text().strip()=='reproduction-ui-isolated'
inspect=json.loads(subprocess.check_output(['docker','inspect',name]))[0]
assert any(m['Destination']=='/data' and Path(m['Source']).resolve()==data for m in inspect['Mounts'])
assert inspect['State']['Running']
candidate=root/'reproduction-ui-candidate'
scripts=['reproduction_provider_acceptance.py','reproduction_model_groups.py','reproduction_priority.py','reproduction_users.py','reproduction_route_samples.py','reproduction_route_reporting.py','reproduction_group_access.py']
for script in scripts:
    subprocess.run(['docker','cp',str(candidate/'tests'/script),name+':/tmp/'+script],check=True,stdout=subprocess.DEVNULL)
    result=subprocess.run(['docker','exec','-e','PYTHONPATH=/app/backend',name,'python','/tmp/'+script],capture_output=True,text=True)
    log=root/(script.removesuffix('.py')+'-final.log');log.write_text(result.stdout+result.stderr)
    assert result.returncode==0,f'{script} failed; inspect isolated log {log.name}'
    print(result.stdout.strip(),flush=True)
result=subprocess.run(['docker','exec','-w','/app/backend',name,'alembic','current'],capture_output=True,text=True,check=True)
assert result.stdout.strip().startswith('0022'),result.stdout
print('PASS: fresh candidate image boots and migrations reach0022; seven isolated suites passed; production never mounted.',flush=True)
