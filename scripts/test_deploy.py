"""无Docker/SSH条件下测试部署流程控制。使用假Docker，不代表容器运行验证。"""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
RELEASE_ID='a'*40+'-123-1'
MOCK='''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
args=sys.argv[1:]
with open(os.environ['MOCK_LOG'],'a') as f:f.write(json.dumps(args)+'\\n')
if args[0]=='info':print(os.getenv('MOCK_ARCH','x86_64'))
if 'ps' in args and '-aq' in args:print('old-fuseki-container')
if 'cp' in args:
 p=Path(args[-1]);p.mkdir(parents=True);(p/'test-database').write_text('backup')
if 'up' in args and os.getenv('MOCK_FAIL')=='1':
 directory=args[args.index('--project-directory')+1]
 if directory.endswith(os.environ['CANDIDATE_ID']):sys.exit(1)
'''


class DeploymentFlow(unittest.TestCase):
    def exercise(self, *, fail=False, arch='x86_64', previous=True):
        temp=tempfile.TemporaryDirectory(prefix='airdeploy-')
        self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        binary=root/'bin';binary.mkdir()
        executable=binary/'docker';executable.write_text(MOCK);executable.chmod(0o755)
        incoming=root/'incoming'/RELEASE_ID;incoming.mkdir(parents=True)
        package=incoming/'bundle.tar'
        with tarfile.open(package,'w') as archive:
            for name,content in [('compose.ecs.yaml','name: airontology\n'),('images.env','APP_IMAGE=test\n'),
                                 ('images.tar.gz','fake images'),('.env.example','APP_PORT=8092\n')]:
                payload=content.encode();entry=tarfile.TarInfo(name);entry.size=len(payload)
                archive.addfile(entry,io.BytesIO(payload))
        old=root/'releases'/'previous'
        if previous:
            old.mkdir(parents=True)
            (old/'compose.ecs.yaml').write_text('name: airontology\n')
            (old/'images.env').write_text('APP_IMAGE=previous\n')
            (old/'demo.enabled').touch()
            (root/'current').symlink_to(old)
        log=root/'commands.jsonl'
        result=subprocess.run(['bash',str(ROOT/'scripts/deploy-ecs.sh'),str(root),RELEASE_ID,
            hashlib.sha256(package.read_bytes()).hexdigest(),'amd64','true'],
            env={**os.environ,'PATH':str(binary)+':'+os.environ['PATH'],'MOCK_LOG':str(log),
                 'MOCK_FAIL':'1' if fail else '0','MOCK_ARCH':arch,'CANDIDATE_ID':RELEASE_ID},
            text=True,capture_output=True)
        commands=[json.loads(line) for line in log.read_text().splitlines()]
        return root,old,result,commands

    def test_success_imports_before_stopping_and_keeps_volumes(self):
        root,old,result,commands=self.exercise()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual((root/'current').resolve().name,RELEASE_ID)
        self.assertTrue((root/'backups'/RELEASE_ID/'fuseki-data'/'test-database').is_file())
        self.assertTrue((root/'shared'/'.env').is_file())
        load=next(i for i,c in enumerate(commands) if c[0]=='load')
        stop=next(i for i,c in enumerate(commands) if 'stop' in c)
        self.assertLess(load,stop)
        self.assertFalse(any('down' in c or 'prune' in c for c in commands))
        self.assertFalse((root/'incoming'/RELEASE_ID/'bundle.tar').exists())

    def test_failed_candidate_restores_previous_configuration(self):
        root,old,result,commands=self.exercise(fail=True)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual((root/'current').resolve(),old)
        self.assertTrue(any('up' in c and str(old) in c for c in commands))
        self.assertTrue((root/'backups'/RELEASE_ID/'fuseki-data').is_dir())

    def test_wrong_architecture_never_stops_services(self):
        root,old,result,commands=self.exercise(arch='aarch64')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any('stop' in c or c[0]=='load' for c in commands))
        self.assertEqual((root/'current').resolve(),old)

    def test_first_deployment_can_start_without_previous_release(self):
        root,old,result,commands=self.exercise(previous=False)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertTrue((root/'current').is_symlink())


if __name__=='__main__':
    unittest.main()
