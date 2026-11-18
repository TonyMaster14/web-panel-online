"""Advertise WPO Sweden's verified REALITY direct-TCP443 mode via Node Agent.

Safely modifies ONLY the lightweight agent status response, after auth. If
the managed marker is absent, Xray is down, or HAProxy owns 443, no direct
REALITY capability is reported. No writes to Xray, ports, TLS or subscribers.
"""
from __future__ import annotations
import ast

MARKER="# WPO_REAL443_SITE_STATUS_V1"
RUN="ThreadingHTTPServer(('127.0.0.1',9088),H).serve_forever()"

INJECTION = '''
# WPO_REAL443_SITE_STATUS_V1
# Report the mode only when the confirmed Sweden canary actively owns TCP443.
import pathlib as _wpo_real443_pathlib
import json as _wpo_real443_json
import socket as _wpo_real443_socket
import subprocess as _wpo_real443_subprocess

def _wpo_real443_live():
    try:
        path=_wpo_real443_pathlib.Path("/etc/wpo-reality-remna-test/managed.json")
        if path.is_symlink() or not path.is_file():
            return False
        mode=_wpo_real443_json.loads(path.read_text(encoding="utf-8"))
        if (mode.get("domain") != "swejeep.goodarielservice.xyz" or
            mode.get("mode") != "remna-443-mirror-v1"):
            return False
        if _wpo_real443_subprocess.run(
               ["systemctl","is-active","--quiet","wpo-reality-remna-xray-test.service"],
               stdin=_wpo_real443_subprocess.DEVNULL,
               stdout=_wpo_real443_subprocess.DEVNULL,
               stderr=_wpo_real443_subprocess.DEVNULL,timeout=2).returncode:
            return False
        if _wpo_real443_subprocess.run(
               ["systemctl","is-active","--quiet","wpo-tls-router.service"],
               stdin=_wpo_real443_subprocess.DEVNULL,
               stdout=_wpo_real443_subprocess.DEVNULL,
               stderr=_wpo_real443_subprocess.DEVNULL,timeout=2).returncode==0:
            return False
        with _wpo_real443_socket.create_connection(("127.0.0.1",443),timeout=1):
            pass
        return True
    except (OSError,ValueError,TypeError,KeyError,
            _wpo_real443_subprocess.SubprocessError):
        return False

_wpo_real443_out_old=H.out
def _wpo_real443_out(self,data,code=200):
    if (self.path == "/wpp-api/v1/status" and code==200
        and isinstance(data,dict) and data.get("ok") is True
        and _wpo_real443_live()):
        caps=data.get("capabilities",[])
        if isinstance(caps,list) and "reality-direct-443" not in caps:
            data=dict(data)
            data["capabilities"]=caps+["reality-direct-443"]
    return _wpo_real443_out_old(self,data,code)
H.out=_wpo_real443_out
'''


def patch(source):
    """Insert before agent's only serve_forever entrypoint; fail closed."""
    if MARKER in source:
        raise ValueError("REALITY mode status already installed")
    if source.count(RUN)!=1 or "class H(BaseHTTPRequestHandler):" not in source:
        raise ValueError("Unrecognized WPO node agent; refusing to patch")
    updated=source.replace(RUN,INJECTION+"\n"+RUN,1)
    ast.parse(updated)
    return updated
