"""Windows shell environment recovery; no app launch, profile writes or network."""
from pathlib import Path
import os
import subprocess
import sys

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / 'src/desktop'))
from launcher import app_environment

if '--sanitized-child' in sys.argv:
    import ctypes
    assert 'SystemDrive' not in os.environ
    environment = app_environment()
    for name in ('SystemDrive', 'ProgramData', 'ProgramFiles', 'CommonProgramFiles',
                 'ALLUSERSPROFILE', 'PUBLIC', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA'):
        assert name in environment and '%' not in environment[name] and Path(environment[name]).is_dir(), name
    assert environment['PATH'] == os.environ['PATH']
    assert environment['TEMP'] == os.environ['TEMP']
    assert not any(name in environment for name in (
        'OPENAI_API_KEY', 'PROVIDER_TOKEN', 'PRIVATE_SETTING', 'NODE_OPTIONS',
        'ELECTRON_RUN_AS_NODE', 'CODEX_HOME', 'CODEX_CLI_PATH'))
    # A shell extension's normal environment expansion must resolve to a real
    # directory, rather than creating a literal %SystemDrive% subtree.
    os.environ.clear()
    os.environ.update(environment)
    buffer = ctypes.create_unicode_buffer(32768)
    assert ctypes.windll.kernel32.ExpandEnvironmentStringsW(
        '%SystemDrive%\\ProgramData', buffer, len(buffer))
    assert '%' not in buffer.value and Path(buffer.value).is_dir()
    print('PASS: sanitized launcher recovers Windows shell paths, retains tool paths and excludes secrets/runtime overrides.')
else:
    environment = {name: os.environ[name] for name in (
        'SystemRoot', 'WINDIR', 'PATH', 'PATHEXT', 'TEMP', 'TMP', 'USERPROFILE',
        'LOCALAPPDATA', 'APPDATA', 'COMSPEC') if name in os.environ}
    environment.update(OPENAI_API_KEY='dummy-private-fixture', PROVIDER_TOKEN='dummy-private-fixture',
                       PRIVATE_SETTING='dummy-private-fixture', NODE_OPTIONS='--invalid-fixture',
                       ELECTRON_RUN_AS_NODE='1', CODEX_HOME='dummy-fixture', CODEX_CLI_PATH='dummy-fixture')
    subprocess.run([sys.executable, str(Path(__file__).resolve()), '--sanitized-child'],
                   env=environment, check=True)
