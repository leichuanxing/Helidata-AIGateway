"""Disposable container only: ciphertext survives restart; missing/wrong master key fails closed."""
from pathlib import Path
import hashlib,secrets,subprocess,time,uuid
NAME='helidata-stage5-key-recovery'
DATA=Path('/opt/AIGateway/.deployment')/('stage5-key-recovery-'+uuid.uuid4().hex[:8])
DATA.mkdir(mode=0o700)
KEY=DATA/'config/provider-encryption.key'

def run(*args): return subprocess.check_output(list(args),text=True,stderr=subprocess.DEVNULL).strip()

def ready():
    for _ in range(90):
        r=subprocess.run(['docker','exec',NAME,'python','-c',"import urllib.request; assert urllib.request.urlopen('http://127.0.0.1/health',timeout=4).status==200"],capture_output=True)
        if r.returncode==0: return
        if run('docker','inspect','-f','{{.State.Running}}',NAME)!='true': raise AssertionError('Recovery test container failed startup')
        time.sleep(1)
    raise AssertionError('Recovery test startup timed out')

def exited():
    for _ in range(45):
        if run('docker','inspect','-f','{{.State.Running}}',NAME)=='false': return
        time.sleep(1)
    raise AssertionError('Unsafe missing/wrong-key startup was not stopped')

seed="""import asyncio
from app.core.database import session_factory
from app.models.user import Provider
from app.services.provider_crypto import encrypt_secret
async def main():
    async with session_factory.begin() as db:
        db.add(Provider(name='recovery-fixture',provider_type='custom_openai',protocol='openai',base_url='http://127.0.0.1:1',api_key_encrypted=encrypt_secret('Stage5-Recovery-Test-Secret')))
asyncio.run(main())
"""
verify="""import asyncio
from sqlalchemy import select
from app.core.database import session_factory
from app.models.user import Provider
from app.services.provider_crypto import decrypt_secret
async def main():
    async with session_factory() as db:
        value=await db.scalar(select(Provider.api_key_encrypted).where(Provider.name=='recovery-fixture'))
        assert decrypt_secret(value)=='Stage5-Recovery-Test-Secret'
asyncio.run(main())
"""
run('docker','run','-d','--name',NAME,'--network','none','-v',str(DATA)+':/data:Z','helidata-ai-gateway:stage5')
try:
    ready();run('docker','exec',NAME,'python','-c',seed)
    original=KEY.read_bytes();assert len(original)==32
    run('docker','restart','-t','60',NAME);ready();run('docker','exec',NAME,'python','-c',verify)
    assert KEY.read_bytes()==original
    print('PASS: AES-GCM ciphertext and persistent 256-bit key survive container restart',flush=True)
    run('docker','stop','-t','60',NAME)
    KEY.unlink()
    run('docker','start',NAME);exited()
    assert not KEY.exists(), 'Master key unexpectedly regenerated over existing ciphertext'
    print('PASS: missing key with existing ciphertext blocks startup without replacement',flush=True)
    KEY.write_bytes(secrets.token_bytes(32));KEY.chmod(0o600)
    run('docker','start',NAME);exited()
    print('PASS: wrong key blocks startup; authenticated decryption catches mismatch',flush=True)
    KEY.write_bytes(original);KEY.chmod(0o600)
    run('docker','start',NAME);ready();run('docker','exec',NAME,'python','-c',verify)
    print('PASS: restoring original protected key recovers existing provider credentials',flush=True)
finally:
    subprocess.run(['docker','stop','-t','60',NAME],stdout=subprocess.DEVNULL,check=True)
    subprocess.run(['docker','rm',NAME],stdout=subprocess.DEVNULL,check=True)
