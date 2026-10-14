"""Launch the registered installation with reversible settings and a RAM-only UI."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
from config_transaction import activate,rollback

ROOT = Path(__file__).resolve().parent
SUPPORT = ROOT / 'support'
TRANSACTION = SUPPORT / 'Live-Transaction.json'
POWERSHELL = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'

def shell(script,*arguments):
    return subprocess.run([str(POWERSHELL),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT / script),*arguments],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)

def verify_files():
    deployment = json.loads((ROOT / 'Deployment.json').read_text())
    for name,expected in deployment['installed_file_hashes'].items():
        with (Path(deployment['source_app']) / name).open('rb') as handle:
            if hashlib.file_digest(handle,'sha256').hexdigest() != expected: raise RuntimeError('Installed Codex build changed. Customization refused; the signed installation remains intact.')
    checks = json.loads((ROOT / 'Helper-Checksums.json').read_text())
    for name,expected in checks.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected: raise RuntimeError('Provider helper verification failed; customization refused')
    return deployment

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rollback',action='store_true')
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--preflight',action='store_true')
    parser.add_argument('--wait-for-close',action='store_true')
    args = parser.parse_args()
    deployment = json.loads((ROOT / 'Deployment.json').read_text())
    cancel_path = SUPPORT / 'Cancel-Activation.flag'
    if args.rollback and (SUPPORT / 'Activation-State.json').exists():
        state = json.loads((SUPPORT / 'Activation-State.json').read_text())
        if state.get('status') == 'waiting_for_installed_app_to_close':
            cancel_path.write_text('User requested rollback; cancel pending activation.\n')
            print('Pending activation cancelled. No live configuration was changed.')
            return
    if args.check:
        verify_files(); print('CHECK PASSED: exact installed build and helper hashes verified; no changes made.'); return
    if args.preflight:
        verify_files()
        result = shell('Check-Closed.ps1','-InstalledApp',deployment['source_app'])
        print('READ-ONLY PREFLIGHT: ' + ('ready for launch' if result.returncode == 0 else 'installed Codex is still running; close it before activation') + '. No configuration or processes changed.')
        return
    if args.wait_for_close:
        if args.rollback: raise RuntimeError('Wait mode is only for the approved initial activation')
        verify_files()
        if cancel_path.exists(): cancel_path.unlink()
        activation_path = SUPPORT / 'Activation-State.json'
        activation_path.write_text(json.dumps({'status':'waiting_for_installed_app_to_close','helper_pid':os.getpid(),'live_configuration_changed':False}))
        print('Approved activation queued. Quit installed Codex once; it will reopen automatically. No live settings changed while waiting.',flush=True)
        deadline = time.monotonic() + 1800
        while time.monotonic() < deadline:
            if cancel_path.exists():
                activation_path.write_text(json.dumps({'status':'cancelled_without_activation','live_configuration_changed':False}))
                print('Pending activation cancelled without changing live settings.',flush=True)
                return
            result = shell('Check-Closed.ps1','-InstalledApp',deployment['source_app'])
            if result.returncode == 0: break
            if result.returncode != 2: raise RuntimeError('Installed-app readiness check failed; no activation performed')
            time.sleep(3)
        else:
            activation_path.write_text(json.dumps({'status':'expired_without_activation','live_configuration_changed':False}))
            raise RuntimeError('Activation wait expired without making changes. Use the prepared launcher after quitting Codex.')
        activation_path.write_text(json.dumps({'status':'activating','helper_pid':os.getpid()}))
    if shell('Check-Closed.ps1','-InstalledApp',deployment['source_app']).returncode:
        raise RuntimeError('Close installed Codex first; its running window and agents were left untouched.')
    if args.rollback:
        if shell('Stop-Provider-Service.ps1').returncode: raise RuntimeError('Owned helper stop verification failed')
        rollback(TRANSACTION)
        print('ROLLBACK COMPLETE: original settings restored; installed files, sign-in and chats retained.'); return
    verify_files()
    if shell('Stop-Provider-Service.ps1').returncode: raise RuntimeError('Existing provider helper does not match')
    # Recover an interrupted prior launch before taking a fresh verified backup.
    rollback(TRANSACTION)
    from provider_service import Service
    from signed_overlay import PrivatePipe
    service = None
    child = None
    pipe = None
    try:
        service = Service()
        service.start()
        config = Path(os.environ['USERPROFILE']) / '.codex/config.toml'
        activate(config,service.base_url,ROOT / 'models.json',ROOT / 'backups',TRANSACTION)
        environment = {key:os.environ[key] for key in ('SystemRoot','WINDIR','PATH','PATHEXT','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA','COMSPEC','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE') if key in os.environ}
        environment['CODEX_HOME'] = str(config.parent)
        environment['CODEX_CLI_PATH'] = str(Path(deployment['source_app']) / 'resources/codex.exe')
        pipe = PrivatePipe()
        # No user-data override: use the installed app's actual signed-in profile.
        child = pipe.launch([str(Path(deployment['source_app']) / 'ChatGPT.exe')],cwd=config.parent,env=environment)
        overlay = json.loads((ROOT / 'Provider-Overlay.json').read_text())
        source = (ROOT / 'Provider-Overlay.source.js').read_text(encoding='utf-8')
        if hashlib.sha256(source.encode()).hexdigest() != overlay['overlay_source_sha256']: raise RuntimeError('UI source verification failed')
        ui_applied = pipe.patch(overlay['filename'],overlay['original_source_sha256'],source,SUPPORT / 'Live-Overlay-Check.json')
        state = json.loads((SUPPORT / 'Gateway-State.json').read_text())
        state.update(app_pid=child.pid,mode='installed_signed_app',package_files_replaced=False)
        (SUPPORT / 'Gateway-State.json').write_text(json.dumps(state))
        print('Installed Codex remains open; ' + ('provider categories applied' if ui_applied else 'category update failed; native window and working provider service retained') + '. Closing it restores ordinary launch settings.',flush=True)
        (SUPPORT / 'Activation-State.json').write_text(json.dumps({'status':'active' if ui_applied else 'running_without_categories','helper_pid':os.getpid(),'app_pid':child.pid,'package_files_replaced':False,'configuration_backup_verified':True,'ui_customization_passed':ui_applied}))
        child.wait()
    finally:
        if child and child.poll() is None:
            if pipe:
                try: pipe.call('Browser.close',timeout=3)
                except (OSError,RuntimeError,TimeoutError): pass
            try: child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.terminate()
                child.wait(timeout=5)
        if pipe: pipe.close()
        rollback(TRANSACTION)
        if service: service.stop()
        state_path = SUPPORT / 'Gateway-State.json'
        if state_path.exists() and json.loads(state_path.read_text()).get('helper_pid') == os.getpid(): state_path.unlink()
        print('Ordinary installed Codex settings restored. No chat databases or sign-in stores changed by rollback.',flush=True)
        (SUPPORT / 'Activation-State.json').write_text(json.dumps({'status':'restored','package_files_replaced':False}))

if __name__ == '__main__':
    try: main()
    except Exception as error:
        (SUPPORT / 'Last-Launch-Error.txt').write_text(str(error))
        (SUPPORT / 'Last-Launch-Traceback.txt').write_text(traceback.format_exc())
        (SUPPORT / 'Activation-State.json').write_text(json.dumps({'status':'failed','error':str(error),'package_files_replaced':False}))
        print(str(error),flush=True)
        sys.exit(1)
