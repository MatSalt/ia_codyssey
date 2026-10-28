"""Exercise orchestration with fake tools; never contacts Docker, GitHub or production."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SHA = 'a' * 40
DIGEST = 'ghcr.io/jimchoi9/mori_ai@sha256:' + 'b' * 64

class DeploymentTest(unittest.TestCase):
    def run_deploy(self, fail='', invalid=False):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'scripts').mkdir()
            shutil.copy(ROOT/'scripts/lightsail-deploy.sh',root/'scripts')
            (root/'scripts/lightsail.sh').write_text('exec docker compose "$@"\n')
            (root/'scripts/lightsail-backup.sh').write_text('echo backup >> "$TRACE"\n[ "$FAIL" != backup ]\n')
            (root/'.env.production').write_text('MORI_IMAGE=old-image\nAI_REAL_CALLS_ENABLED=false\nPOSTGRES_PASSWORD=sentinel\n')
            bindir=root/'bin';bindir.mkdir()
            fake='''#!/usr/bin/env python3
import os, sys
from pathlib import Path
name=Path(sys.argv[0]).name
args=sys.argv[1:]
with open(os.environ['TRACE'],'a') as f:f.write(name+' '+' '.join(args)+'\\n')
fail=os.environ['FAIL']
if name=='git':
 if 'rev-parse' in args:print('a'*40)
 if 'status' in args and fail=='dirty':print(' M compose.lightsail.yaml')
 if 'merge' in args and fail=='merge':sys.exit(1)
if name=='docker':
 if args[0]=='pull' and fail=='pull':sys.exit(1)
 if args[:2]==['image','inspect']:
  if 'RepoDigests' in args[3]:print('ghcr.io/jimchoi9/mori_ai@sha256:'+'b'*64)
  else:print('c'*40 if fail=='revision' else 'a'*40)
 if args[0]=='compose':
  if args[-1]=='migrate' and fail=='migration':sys.exit(1)
  if 'up' in args and fail=='startup':sys.exit(1)
if name=='curl':
 if fail=='https':sys.exit(1)
 print('{"status":"ok"}')
'''
            for name in ['docker','git','flock','curl']:
                p=bindir/name;p.write_text(fake);p.chmod(0o755)
            trace=root/'trace'
            env=dict(os.environ, PATH=str(bindir)+os.pathsep+os.environ['PATH'],TRACE=str(trace),FAIL=fail)
            r=subprocess.run(['bash','scripts/lightsail-deploy.sh','bad' if invalid else SHA],cwd=root,env=env,capture_output=True,text=True)
            return r,trace.read_text() if trace.exists() else '',(root/'.env.production').read_text()

    def test_success_order_and_persistence(self):
        r,t,e=self.run_deploy()
        self.assertEqual(r.returncode,0,r.stderr)
        order=['docker pull','backup','compose stop','migrate','compose up','curl']
        indexes=[t.index(x) for x in order]
        self.assertEqual(indexes,sorted(indexes))
        self.assertIn('MORI_IMAGE='+DIGEST,e)
        self.assertIn('AI_REAL_CALLS_ENABLED=false',e)
        self.assertNotIn('sentinel',r.stdout+r.stderr)
        self.assertNotIn('caddy',t)
        self.assertNotIn(' build ',t)

    def test_preflight_failures_do_not_stop_services(self):
        for failure in ['dirty','merge','pull','revision','backup']:
            with self.subTest(failure=failure):
                r,t,e=self.run_deploy(failure)
                self.assertNotEqual(r.returncode,0)
                self.assertNotIn('compose stop',t)
                self.assertIn('MORI_IMAGE=old-image',e)

    def test_migration_failure_does_not_start_or_claim_rollback(self):
        r,t,e=self.run_deploy('migration')
        self.assertNotEqual(r.returncode,0)
        self.assertNotIn('compose up',t)
        self.assertIn('no automatic DB rollback',r.stderr)
        self.assertIn('MORI_IMAGE=old-image',e)

    def test_health_failures_do_not_persist_new_image(self):
        for failure in ['startup','https']:
            with self.subTest(failure=failure):
                r,t,e=self.run_deploy(failure)
                self.assertNotEqual(r.returncode,0)
                self.assertIn('MORI_IMAGE=old-image',e)

    def test_invalid_revision_has_no_side_effects(self):
        r,t,e=self.run_deploy(invalid=True)
        self.assertEqual(r.returncode,2)
        self.assertEqual(t,'')

if __name__=='__main__':unittest.main()
