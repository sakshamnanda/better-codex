"""Enter via the registered package context, then run the reviewed launcher."""
from pathlib import Path
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import os
import sys
import traceback

ROOT = Path(__file__).resolve().parent
SUPPORT = ROOT / 'support'
k = C.WinDLL('kernel32',use_last_error=True)
k.CreateMutexW.argtypes = [C.c_void_p,W.BOOL,W.LPCWSTR]; k.CreateMutexW.restype = W.HANDLE
k.WaitForSingleObject.argtypes = [W.HANDLE,W.DWORD]
k.ReleaseMutex.argtypes = [W.HANDLE]
k.CloseHandle.argtypes = [W.HANDLE]
k.GetCurrentPackageFullName.argtypes = [C.POINTER(W.UINT),W.LPWSTR]
mutex = k.CreateMutexW(None,False,'Local\\CodexProviders_' + hashlib.sha256(str(ROOT).lower().encode()).hexdigest()[:24])
if not mutex: raise C.WinError(C.get_last_error())
if k.WaitForSingleObject(mutex,0) not in (0,0x80):
    k.CloseHandle(mutex)
    sys.exit(0)  # Preserve the already queued/running launch and its state.
try:
    with (SUPPORT / 'Package-Launch.stdout.log').open('w',encoding='utf-8') as stdout, (SUPPORT / 'Package-Launch.stderr.log').open('w',encoding='utf-8') as stderr:
        sys.stdout = stdout; sys.stderr = stderr
        try:
            deployment = json.loads((ROOT / 'Deployment.json').read_text())
            count = W.UINT(); k.GetCurrentPackageFullName(C.byref(count),None)
            value = C.create_unicode_buffer(max(1,count.value))
            result = k.GetCurrentPackageFullName(C.byref(count),value)
            if result != 0 or value.value != Path(deployment['source_app']).parent.name:
                raise RuntimeError('Registered Codex package context unavailable; no activation performed')
            (SUPPORT / 'Launch-Context.json').write_text(json.dumps({'package_identity_verified':True,'helper_pid':os.getpid(),'registered_windows_launch':True}))
            import launcher
            launcher.main()
        except Exception as error:
            traceback.print_exc()
            (SUPPORT / 'Last-Launch-Error.txt').write_text(str(error))
            (SUPPORT / 'Last-Launch-Traceback.txt').write_text(traceback.format_exc())
            (SUPPORT / 'Activation-State.json').write_text(json.dumps({'status':'failed','error':str(error),'package_files_replaced':False}))
finally:
    k.ReleaseMutex(mutex); k.CloseHandle(mutex)
