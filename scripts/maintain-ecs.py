#!/usr/bin/env python3
"""Reclaim TDB2 disk pages through Fuseki's supported online compaction API."""
import fcntl
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


def run(*args, timeout=30):
    return subprocess.check_output(args, text=True, timeout=timeout).strip()


def maintain(root, force=False):
    with (root / 'deploy.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Deployment/maintenance active; skip.', flush=True)
            return
        container = run('docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=airontology',
                        '--filter', 'label=com.docker.compose.service=fuseki').splitlines()
        if len(container) != 1:
            print('Fuseki is not running; skip.', flush=True)
            return
        container = container[0]
        mounts = json.loads(run('docker', 'inspect', '--format', '{{json .Mounts}}', container))
        data = Path(next(m['Source'] for m in mounts if m['Destination'] == '/data')) / 'database'
        size = int(run('du', '-sk', str(data)).split()[0]) * 1024
        print(f'TDB2 bytes={size}, free={shutil.disk_usage(data).free}', flush=True)
        if not force and size < 256 * 1024**2:
            return

        def request(path, post=False):
            args = ['docker', 'exec', container, 'curl', '-fsS', '--max-time', '20']
            if post:
                args += ['-X', 'POST']
            return json.loads(run(*args, 'http://127.0.0.1:3030/$/' + path))

        # A small logical dataset still grows physically without compaction.
        # Fuseki removes the old generation only after successful compaction.
        task_id = str(request('compact/counteruav?deleteOld=true', post=True)['taskId'])
        if not task_id.isalnum():
            raise RuntimeError('Unexpected compaction task identifier')
        for _ in range(90):
            tasks = request('tasks/' + task_id)
            task = tasks[0] if isinstance(tasks, list) else tasks
            if task.get('success') is False and (task.get('finished') or task.get('finishPoint')):
                raise RuntimeError(f'Compaction failed: {task}')
            if task.get('success') is True:
                print(f'Compaction succeeded: {task_id}; {run("du", "-sh", str(data))}', flush=True)
                return
            time.sleep(2)
        raise TimeoutError('Compaction did not finish within three minutes')


if __name__ == '__main__':
    maintain(Path(sys.argv[1] if len(sys.argv) > 1 else '/opt/airontology'), '--force' in sys.argv)
