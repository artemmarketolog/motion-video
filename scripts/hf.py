#!/usr/bin/env python3
"""Run the pinned local HyperFrames CLI in an offline filesystem sandbox."""
import argparse
from pathlib import Path
from skill_config import RUNTIME, setting
import shutil
import subprocess
import sys

CHROME = Path(setting('MOTION_VIDEO_CHROME', str(RUNTIME / 'chrome/chrome-linux64/chrome'))).expanduser().resolve().parent
SKILL_SCRIPTS = Path(__file__).resolve().parent
COMMANDS = {'--version', '--help', 'lint', 'check', 'snapshot', 'timeline', 'render', 'probe'}
QUALITIES = {'draft', 'standard', 'delivery'}
MAX_WORKERS = 6  # 6 cores / 11 GB VPS; see references/cache-and-edits.md benchmark


def sandbox(project):
    node = Path(shutil.which('node') or '/missing-node').resolve()
    for path in (RUNTIME / 'node_modules/hyperframes/bin/hyperframes.mjs', CHROME / 'chrome', node):
        if not path.is_file():
            raise ValueError(f'Missing runtime dependency: {path}; see references/runtime.md')
    if not shutil.which('bwrap'):
        raise ValueError('bubblewrap is required; do not fall back to an unsandboxed render')
    # Never mount a general project/credential directory. Symlinks escaping the
    # dedicated media folder also fail inside this sandbox; copy assets locally.
    if not (project / 'index.html').is_file():
        raise ValueError('Use a dedicated video directory containing index.html')
    protected = (RUNTIME, CHROME, node.parent, Path('/usr'), Path('/etc'))
    if any(path.is_relative_to(project) or project.is_relative_to(path) for path in protected) or project in (Path.home(), Path.home() / 'projects', Path.home() / 'workspace'):
        raise ValueError('Refusing to mount a home, runtime, workspace or projects root')
    for pattern in ('.env', '.env.*', '**/.env', '**/.env.*'):
        if next(project.glob(pattern), None) is not None:
            raise ValueError('Render directory contains an .env file; use a clean media directory')
    # Render temp files go to disk, not to a tmpfs in RAM: on a 2 GB server the tmpfs is ~1 GB and
    # HyperFrames refuses to render ("Low disk space"); on any server they would eat memory.
    tmp = project / '.cache' / 'tmp'
    tmp.mkdir(parents=True, exist_ok=True)
    args = ['bwrap', '--unshare-all', '--die-with-parent', '--new-session', '--clearenv',
            '--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin',
            '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib64', '/lib64',
            '--proc', '/proc', '--dev', '/dev', '--bind', str(tmp), '/tmp', '--tmpfs', '/home',
            '--dir', str(Path.home()), '--dir', '/etc', '--dir', '/opt',
            '--ro-bind', str(node), '/opt/node',
            '--ro-bind', str(CHROME), '/opt/chrome',
            '--ro-bind', str(RUNTIME), '/runtime',
            '--ro-bind', str(SKILL_SCRIPTS), '/skill',
            '--bind', str(project), '/project', '--chdir', '/project']
    for path in ('/etc/ld.so.cache', '/etc/fonts', '/etc/alternatives'):
        if Path(path).exists():
            args += ['--ro-bind', path, path]
    environment = {
        'HOME': str(Path.home()), 'PATH': '/opt:/usr/bin:/bin', 'LANG': 'C.UTF-8',
        'HYPERFRAMES_BROWSER_PATH': '/opt/chrome/chrome',
        'PRODUCER_HEADLESS_SHELL_PATH': '/opt/chrome/chrome',
        'HYPERFRAMES_FFMPEG_PATH': '/usr/bin/ffmpeg',
        'HYPERFRAMES_FFPROBE_PATH': '/usr/bin/ffprobe',
        'HYPERFRAMES_NO_TELEMETRY': '1', 'DO_NOT_TRACK': '1',
        'HYPERFRAMES_NO_UPDATE_CHECK': '1', 'HYPERFRAMES_NO_AUTO_INSTALL': '1',
        'HYPERFRAMES_SKIP_SKILLS': '1', 'CI': '1', 'NO_COLOR': '1',
        # Encode while capturing with several workers (measured 01.10.2026: −20…35 % render time,
        # same frames); upstream falls back to the disk path by itself if streaming fails.
        'HF_DE_PARALLEL_STREAM': 'true',
    }
    for key, value in environment.items():
        args += ['--setenv', key, value]
    return args


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=int, default=1800, help='Maximum seconds for this command')
    parser.add_argument('project', type=Path, help='Dedicated video folder; mounted as /project')
    parser.add_argument('cli', nargs=argparse.REMAINDER, help='lint/check/snapshot/timeline/render and relative paths')
    args = parser.parse_args()
    cli = args.cli
    if cli and cli[0] == '--':
        cli = cli[1:]
    if not cli or cli[0] not in COMMANDS:
        parser.error('Allowed commands: ' + ', '.join(sorted(COMMANDS)))
    if any(item.split('=')[0] in ('--docker', '--batch', '--docker-image') for item in cli):
        parser.error('This wrapper runs one local composition; Docker and batch flags are excluded')
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    project = args.project.resolve()
    if cli[0] == 'snapshot':
        cli += ['--describe', 'false', '--no-browser-gpu']
    if cli[0] == 'check':
        cli += ['--no-browser-gpu']
    if cli[0] == 'probe':
        # Frame fingerprints for the incremental cache (scripts/probe.mjs); no screenshots.
        command = sandbox(project) + ['--', '/opt/node', '/skill/probe.mjs'] + cli[1:]
        return execute(command, args.timeout)
    if cli[0] == 'render':
        output = None
        workers, quality, rest = '1', 'delivery', []
        index = 1
        while index < len(cli):
            item = cli[index]
            value = cli[index + 1] if index + 1 < len(cli) else None
            if item in ('-o', '--output'):
                output = value
            elif item.startswith('--output='):
                output = item.split('=', 1)[1]
            if item in ('-w', '--workers', '-q', '--quality'):
                if value is None:
                    raise ValueError(f'{item} needs a value')
                if item in ('-w', '--workers'):
                    workers = value
                else:
                    quality = value
                index += 2
                continue
            if item.startswith('--workers=') or item.startswith('--quality='):
                key, val = item[2:].split('=', 1)
                workers, quality = (val, quality) if key == 'workers' else (workers, val)
                index += 1
                continue
            rest.append(item)
            index += 1
        if not workers.isdigit() or not 1 <= int(workers) <= MAX_WORKERS:
            raise ValueError(f'--workers must be 1..{MAX_WORKERS} on this VPS')
        if quality not in QUALITIES:
            raise ValueError('--quality must be draft, standard or delivery')
        if not output:
            raise ValueError('render requires an explicit -o relative/path-r1.mp4')
        destination = (project / output).resolve()
        if not destination.is_relative_to(project):
            raise ValueError('Output must be a relative path inside the video project')
        if destination.exists():
            raise ValueError(f'Output already exists: {output}; choose a new revision')
        cli = [cli[0], *rest, '--quality', quality, '--workers', workers,
               '--no-browser-gpu', '--strict', '--no-best-effort']
    command = sandbox(project) + ['--', '/opt/node', '/runtime/node_modules/hyperframes/bin/hyperframes.mjs'] + cli
    return execute(command, args.timeout)


def execute(command, timeout):
    try:
        return subprocess.run(command, env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        print('HyperFrames timed out; its isolated process namespace was terminated', file=sys.stderr)
        return 124


if __name__ == '__main__':
    try:
        sys.exit(main())
    except ValueError as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
