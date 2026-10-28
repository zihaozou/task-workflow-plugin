#!/usr/bin/env python3
"""Create and enter this installed skill's owned, standard-library runtime."""
import contextlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

SKILL = Path(__file__).resolve().parents[1]
RUNTIME = SKILL / '.venv'
MARKER = '.task-workflow-runtime.json'


def clean_environment():
    return {key: value for key, value in os.environ.items()
            if key not in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', '__PYVENV_LAUNCHER__', 'UV_PROJECT_ENVIRONMENT')}


def probe(python):
    result = subprocess.run([str(python), '-I', '-c',
        'import json,sys,importlib.metadata; print(json.dumps({"prefix":sys.prefix,"base_prefix":sys.base_prefix,'
        '"base_python":sys._base_executable,"version":list(sys.version_info[:2]),"distributions":[d.metadata.get("Name","") for d in importlib.metadata.distributions()]}))'],
        env=clean_environment(), capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('The existing host Python could not verify its standard library.')
    return json.loads(result.stdout)


def host_python():
    python = Path(sys._base_executable).resolve(strict=True)
    facts = probe(python)
    if facts['prefix'] != facts['base_prefix'] or facts['version'] < [3, 9]:
        raise RuntimeError('Task Workflow needs an existing base Python 3.9 or later.')
    return python


@contextlib.contextmanager
def creation_lock():
    path = SKILL / '.runtime-bootstrap.lock'
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, 'r+b') as stream:
        if os.name == 'nt':
            import msvcrt
            if not stream.read(1):
                stream.write(b'0'); stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def write_owner(owner):
    temporary = RUNTIME / '.runtime-owner.tmp'
    with temporary.open('w') as stream:
        json.dump(owner, stream, sort_keys=True)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, RUNTIME / MARKER)


def runtime_python():
    """Return a verified plugin interpreter; never adopt an unrelated directory."""
    base = host_python()
    owner = {'schema': 1, 'skill_root': str(SKILL), 'base_python': str(base)}
    python = RUNTIME / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    with creation_lock():
        if RUNTIME.is_symlink():
            raise RuntimeError('The plugin runtime must be an owned directory, not a symlink.')
        pending = dict(owner, status='creating')
        if RUNTIME.exists():
            marker = RUNTIME / MARKER
            if not marker.is_file() or marker.is_symlink():
                raise RuntimeError('The plugin runtime has no valid ownership marker.')
            recorded = json.loads(marker.read_text())
            if recorded == pending:
                shutil.rmtree(RUNTIME)
            elif recorded != owner:
                raise RuntimeError('The plugin runtime ownership does not match this installation and host Python.')
        if not RUNTIME.exists():
            RUNTIME.mkdir(mode=0o700)
            write_owner(pending)
            result = subprocess.run([str(base), '-I', '-m', 'venv', '--without-pip', str(RUNTIME)],
                                    env=clean_environment(), capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError('The existing host Python could not create the plugin runtime: ' + result.stderr)
            write_owner(owner)
        verify_runtime()
    return python


def verify_runtime():
    """Read-only ownership and interpreter verification for installed release inspection."""
    base = host_python()
    owner = {'schema': 1, 'skill_root': str(SKILL), 'base_python': str(base)}
    marker = RUNTIME / MARKER
    if RUNTIME.is_symlink() or not RUNTIME.is_dir() or marker.is_symlink() or not marker.is_file() or json.loads(marker.read_text()) != owner:
        raise RuntimeError('The installed plugin runtime has no matching ownership proof.')
    config = (RUNTIME / 'pyvenv.cfg').read_text()
    if 'include-system-site-packages = false' not in config.lower():
        raise RuntimeError('The plugin runtime must exclude host site packages.')
    if any(RUNTIME.glob('lib/python*/site-packages/*.pth')) or any(RUNTIME.glob('Lib/site-packages/*.pth')):
        raise RuntimeError('The plugin runtime must not contain package path injections.')
    python = RUNTIME / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    facts = probe(python)
    if facts['distributions'] or Path(facts['prefix']).resolve() != RUNTIME or Path(facts['base_python']).resolve() != base or facts['prefix'] == facts['base_prefix']:
        raise RuntimeError('The plugin runtime interpreter ownership proof changed.')
    return {'runtime': str(RUNTIME), 'python': str(python), **owner}


def main():
    python = runtime_python()
    args = sys.argv[1:]
    if args == ['--print-python']:
        print(python)
        return
    if args and args[0] != '--':
        args.insert(0, '--')
    if len(args) >= 2 and args[0] == '--':
        requested = Path(args[1])
        script = ((Path(__file__).parent / requested) if len(requested.parts) == 1 else requested).resolve()
        if script.parent != Path(__file__).resolve().parent or script.name == 'bootstrap.py' or not script.is_file():
            raise RuntimeError('Select an installed Task Workflow script.')
        os.execve(str(python), [str(python), '-B', '-E', '-s', str(script), *args[2:]], clean_environment())
    raise RuntimeError('Use --print-python or -- followed by an installed script.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Task Workflow bootstrap: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
