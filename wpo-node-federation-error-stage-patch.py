#!/usr/bin/env python3
"""Patch installed WPO node federation with secret-free POST failure stages.

No keys, profile names, URLs, user IDs, domains or subprocess stderr appear
in the new log lines. All original provisioning and rollback logic is kept.
"""
import argparse
import ast
from pathlib import Path

MARKER="# wpo-federation-safe-failure-stage-v1"

BEFORE_APPLY='''    try:
        result = command(XRAY_BIN, "run", "-test", "-config", str(XRAY), timeout=15)
        if result.returncode:
            raise RuntimeError("Xray configuration validation failed: " + result.stderr[-600:])
        result = command("systemctl", "restart", UNIT, timeout=30)
        if result.returncode or not live():
            raise RuntimeError("Xray did not become ready")
    except Exception:
        if previous is None:'''

AFTER_APPLY='''    # wpo-federation-safe-failure-stage-v1
    phase = "xray-config-validation"
    try:
        result = command(XRAY_BIN, "run", "-test", "-config", str(XRAY), timeout=15)
        if result.returncode:
            raise RuntimeError("Xray configuration validation failed: " + result.stderr[-600:])
        phase = "systemctl-restart"
        result = command("systemctl", "restart", UNIT, timeout=30)
        phase = "post-restart-health"
        if result.returncode or not live():
            raise RuntimeError("Xray did not become ready")
    except Exception as exc:
        # No attacker-controlled strings or credentials in systemd journal.
        print("WPO_FED_APPLY_FAILURE phase=" + phase +
              " type=" + type(exc).__name__ +
              " errno=" + str(getattr(exc, "errno", None)), flush=True)
        if previous is None:'''

BEFORE_API='''        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            self.respond({"ok": False, "message": "VPN provisioning failed: " + str(exc)[:160]}, 503)'''

AFTER_API='''        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            # Do not log exception text: it may contain sensitive data.
            print("WPO_FED_REQUEST_FAILURE type=" + type(exc).__name__ +
                  " errno=" + str(getattr(exc, "errno", None)), flush=True)
            self.respond({"ok": False, "message": "VPN provisioning failed: " + str(exc)[:160]}, 503)
        except Exception as exc:
            print("WPO_FED_REQUEST_CRASH type=" + type(exc).__name__, flush=True)
            self.respond({"ok": False, "message": "VPN provisioning failed: server handler error"}, 503)'''

def patch(src):
    if MARKER in src:
        ast.parse(src,filename="wpo_node_vpn.py")
        return src
    if src.count(BEFORE_APPLY)!=1 or src.count(BEFORE_API)!=1:
        raise ValueError("Unexpected Node VPN version; no changes made")
    result=src.replace(BEFORE_APPLY,AFTER_APPLY,1).replace(BEFORE_API,AFTER_API,1)
    ast.parse(result,filename="wpo_node_vpn.py")
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    args.output.write_text(patch(args.input.read_text(encoding="utf-8")),
                           encoding="utf-8")
    print("✓ Включена безопасная диагностика этапа сбоя VPN Federation")
    print("✓ Содержимое ключей и профилей не записывается в журнал")

if __name__=="__main__":
    main()
