#!/usr/bin/env python3
"""Exercise hf.py isolation using synthetic canaries, without rendering a video."""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from skill_config import DATA_DIR, CACHE_DIR, ENV_FILE, RUNTIME, setting, require_key
import subprocess
import sys
import tempfile
import time
from unittest import mock
import uuid

sys.dont_write_bytecode = True
WRAPPER = Path(__file__).with_name('hf.py')
spec = importlib.util.spec_from_file_location('hf_under_test', WRAPPER)
hf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hf)

PROBE = r'''
import fs from 'node:fs';
import net from 'node:net';
import {spawnSync} from 'node:child_process';
const cfg = JSON.parse(process.argv[1]);
const result = {
  outsideVisible: fs.existsSync(cfg.outside),
  fakeSecretInherited: Object.hasOwn(process.env, 'HF_SANDBOX_FAKE_SECRET'),
  networkNamespace: fs.readlinkSync('/proc/self/ns/net'),
};
try { fs.readFileSync('/project/escape-canary.txt'); result.escapeReadable = true; }
catch (error) { result.escapeReadable = false; result.escapeError = error.code; }
const writeProbe = '/runtime/' + cfg.runtimeProbe;
try {
  fs.writeFileSync(writeProbe, 'synthetic canary', {flag: 'wx'});
  result.runtimeWrite = 'SUCCEEDED';
  fs.unlinkSync(writeProbe);
} catch (error) { result.runtimeWrite = error.code; }
fs.writeFileSync('/project/inside-canary.txt', 'sandbox project write', {flag: 'wx'});
result.tcp = await new Promise(resolve => {
  const socket = net.connect({host: '1.1.1.1', port: 443});
  const finish = code => { socket.destroy(); resolve(code); };
  socket.once('connect', () => finish('CONNECTED'));
  socket.once('error', error => finish(error.code));
  socket.setTimeout(2000, () => finish('TIMEOUT'));
});
try {
  await fetch('https://1.1.1.1/', {signal: AbortSignal.timeout(2500)});
  result.fetch = 'SUCCEEDED';
} catch (error) {
  result.fetch = error.cause?.code || error.cause?.errors?.[0]?.code || error.name;
}
const ffmpeg = spawnSync('/usr/bin/ffmpeg', ['-version'], {encoding: 'utf8', timeout: 10000});
result.ffmpegCode = ffmpeg.status;
result.ffmpegVersion = (ffmpeg.stdout || '').split('\n')[0];
console.log(JSON.stringify(result));
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/hyperframes-sandbox-test.json'))
    args = parser.parse_args()
    checks = []

    def record(name, passed, **details):
        checks.append({'name': name, 'passed': bool(passed), **details})

    def rejected(project, message):
        try:
            hf.sandbox(project)
        except ValueError as error:
            return message in str(error)
        return False

    def cli_rejected(project, options, message):
        # A rejected command must never reach any subprocess.
        with mock.patch.object(sys, 'argv', [str(WRAPPER), str(project), *options]),\
                mock.patch.object(hf.subprocess, 'run', side_effect=AssertionError('unexpected execution')),\
                contextlib.redirect_stderr(io.StringIO()) as stderr:
            try:
                hf.main()
            except ValueError as error:
                return message in str(error)
            except SystemExit as error:
                return error.code == 2 and message in stderr.getvalue()
        return False

    with tempfile.TemporaryDirectory(prefix='hyperframes-sandbox-test-') as temporary:
        root = Path(temporary)
        project = root / 'video'
        project.mkdir()
        (project / 'index.html').write_text('<!doctype html><title>Synthetic sandbox test</title>')
        outside = root / 'outside-canary.txt'
        outside.write_text('synthetic outside canary; not a credential')
        (project / 'escape-canary.txt').symlink_to(outside)
        runtime_probe = '.sandbox-canary-' + uuid.uuid4().hex
        configuration = json.dumps({'outside': str(outside), 'runtimeProbe': runtime_probe})
        process = subprocess.run(
            hf.sandbox(project) + ['--', '/opt/node', '--input-type=module', '-e', PROBE, configuration],
            env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'HF_SANDBOX_FAKE_SECRET': uuid.uuid4().hex},
            capture_output=True, text=True, timeout=20,
        )
        record('canary_process_completed', process.returncode == 0,
               exit_code=process.returncode, stderr=process.stderr.strip())
        if process.returncode == 0:
            result = json.loads(process.stdout)
            record('outside_canary_hidden', outside.is_file() and not result['outsideVisible'])
            record('outside_symlink_unreadable', not result['escapeReadable'], code=result.get('escapeError'))
            record('inherited_fake_secret_removed', not result['fakeSecretInherited'])
            record('separate_network_namespace', result['networkNamespace'] != Path('/proc/self/ns/net').readlink().as_posix())
            unreachable = {'ENETUNREACH', 'EHOSTUNREACH'}
            record('external_tcp_blocked', result['tcp'] in unreachable, code=result['tcp'])
            record('external_fetch_blocked', result['fetch'] in unreachable, code=result['fetch'])
            record('runtime_read_only', result['runtimeWrite'] == 'EROFS', code=result['runtimeWrite'])
            record('project_writable', (project / 'inside-canary.txt').read_text() == 'sandbox project write')
            record('ffmpeg_runs', result['ffmpegCode'] == 0 and result['ffmpegVersion'].startswith('ffmpeg version'),
                   version=result['ffmpegVersion'])
        leaked_probe = hf.RUNTIME / runtime_probe
        if leaked_probe.exists():
            leaked_probe.unlink()  # Only our uniquely named synthetic file, if isolation failed.
            record('runtime_probe_absent_on_host', False)
        else:
            record('runtime_probe_absent_on_host', True)

        for name in ('.env', 'nested/.env.local'):
            path = project / name
            path.parent.mkdir(exist_ok=True)
            path.write_text('HF_TEST_CANARY=synthetic-value\n')
            record('reject_' + name, rejected(project, 'contains an .env'))
            path.unlink()

        existing = project / 'existing-r1.mp4'
        existing.write_bytes(b'synthetic existing output, not a video')
        original_hash = hashlib.sha256(existing.read_bytes()).hexdigest()
        record('reject_existing_output', cli_rejected(project, ['render', '-o', existing.name], 'already exists'))
        record('existing_output_preserved', hashlib.sha256(existing.read_bytes()).hexdigest() == original_hash)
        record('reject_output_escape', cli_rejected(project, ['render', '-o', '../outside.mp4'], 'inside the video project'))
        for flag in ('--docker', '--docker-image=x', '--batch'):
            record('reject_' + flag, cli_rejected(project, ['render', flag, '-o', 'new.mp4'], 'Docker and batch'))
        record('reject_unapproved_command', cli_rejected(project, ['init'], 'Allowed commands'))
        record('reject_too_many_workers', cli_rejected(project, ['render', '--workers', '9', '-o', 'new.mp4'], '--workers must be'))
        record('reject_bad_quality', cli_rejected(project, ['render', '--quality', 'ultra', '-o', 'new.mp4'], '--quality must be'))
        record('reject_upgrade', cli_rejected(project, ['upgrade'], 'Allowed commands'))
        # This real upstream folder contains index.html; no file there is changed.
        protected_project = hf.RUNTIME / 'node_modules/hyperframes/dist/studio'
        record('reject_runtime_descendant', rejected(protected_project, 'Refusing to mount'))

        heartbeat = project / 'timeout-heartbeat.txt'
        child_script = "const fs=require('node:fs');setInterval(()=>fs.appendFileSync('/project/timeout-heartbeat.txt','x'),50)"
        sleeper = "require('node:child_process').spawn('/opt/node',['-e'," + json.dumps(child_script) + "]);setInterval(()=>{},1000)"
        # Exercise the wrapper's real timeout handler and real namespace. Only
        # substitute a harmless sleeper for the CLI; never render or modify it.
        sleeper_command = hf.sandbox(project) + ['--', '/opt/node', '-e', sleeper]
        started = time.monotonic()
        with mock.patch.object(hf, 'sandbox', return_value=sleeper_command),\
                mock.patch.object(sys, 'argv', [str(WRAPPER), '--timeout', '1', str(project), '--version']),\
                contextlib.redirect_stderr(io.StringIO()) as stderr:
            timeout_code = hf.main()
        elapsed = time.monotonic() - started
        record('wrapper_timeout', timeout_code == 124 and elapsed < 5 and 'timed out' in stderr.getvalue(),
               exit_code=timeout_code, elapsed_seconds=round(elapsed, 3))
        first = heartbeat.read_bytes() if heartbeat.exists() else b''
        time.sleep(0.35)
        second = heartbeat.read_bytes() if heartbeat.exists() else b''
        record('timeout_terminated_descendant', bool(first) and first == second, heartbeat_bytes=len(second))

    report = {
        'passed': all(check['passed'] for check in checks),
        'wrapper': str(WRAPPER),
        'wrapper_sha256': hashlib.sha256(WRAPPER.read_bytes()).hexdigest(),
        'checks': checks,
        'scope': 'Synthetic isolation and guard checks only; no real secrets, no video render, no claim of complete security.',
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': report['passed'], 'checks': len(checks), 'report': str(args.output)}, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
