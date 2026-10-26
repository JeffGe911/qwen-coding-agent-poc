"""Task-local supervisor for the unchanged qa-v1 evaluator; never changes its scoring or prompts."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

p = argparse.ArgumentParser()
p.add_argument('root')
p.add_argument('split', choices=['dev', 'holdout'])
a = p.parse_args()
root = Path(a.root)
sys.path.insert(0, str(root))
from qwen_ops import resources

out = root / 'evidence' / 'doc-qa' / 'sessions' / 'qa-v1' / a.split
out.mkdir(parents=True, exist_ok=False)
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
origin = 'http://127.0.0.1:11437'

def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def save(name, value):
    (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')

pre = resources.require()
save('preflight.json', {'utc': stamp(), **pre})
command = [sys.executable, '-u', '-m', 'doc_qa', 'eval', '--contract', 'evidence/doc-qa/contract/qa-v1.json', '--split', a.split, '--unload']
save('command.json', {'started_utc': stamp(), 'command': command, 'cwd': str(root)})
started = time.monotonic()
aborted = None
proc = None
try:
    with (out / 'console.txt').open('w', encoding='utf-8', newline='\n') as console, (out / 'resources.jsonl').open('w', encoding='utf-8', newline='\n') as samples:
        proc = subprocess.Popen(command, cwd=root, env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1'}, stdout=console, stderr=subprocess.STDOUT)
        while proc.poll() is None:
            mem = resources.memory()
            samples.write(json.dumps({'utc': stamp(), 'elapsed_s': round(time.monotonic() - started, 2), 'memory': mem}) + '\n')
            samples.flush()
            if resources.must_abort(mem):
                aborted = {'utc': stamp(), 'reason': 'existing memory stop threshold reached', 'memory': mem}
                proc.terminate()
                proc.wait(timeout=20)
                break
            time.sleep(2)
        code = proc.wait()
    save('session.json', {'finished_utc': stamp(), 'seconds': round(time.monotonic()-started, 2), 'exit_code': code, 'aborted': aborted})
    print((out / 'console.txt').read_text(encoding='utf-8'), flush=True)
    print(json.dumps({'split': a.split, 'exit_code': code, 'aborted': aborted, 'session': str(out)}), flush=True)
finally:
    if proc is not None and proc.poll() is None:
        proc.terminate()
        proc.wait(timeout=20)
    cleanup = {'utc': stamp(), 'unloaded': [], 'errors': []}
    try:
        before = json.load(opener.open(origin + '/api/ps', timeout=10))
        for m in before.get('models', []):
            name = m.get('name') or m.get('model')
            if name not in ('qwen2.5-coder:7b', 'bge-m3:latest', 'bge-m3'):
                continue
            path, body = ('/api/embed', {'model': name, 'input': [], 'keep_alive': 0}) if name.startswith('bge-m3') else ('/api/generate', {'model': name, 'keep_alive': 0})
            req = urllib.request.Request(origin + path, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
            opener.open(req, timeout=60).read()
            cleanup['unloaded'].append(name)
        cleanup['after'] = json.load(opener.open(origin + '/api/ps', timeout=10))
    except Exception as exc:
        cleanup['errors'].append(str(exc))
    save('unload.json', cleanup)
sys.exit(code if aborted is None else 3)
