#!/usr/bin/env python3
"""Fast WPO manager subscription create and Happ first fetch, without weaker activation.

Only remove redundant firewall rebuilds on VLESS/Hysteria-only mutations, and
skip runtime changes for first HWID claim which only renames a preallocated
profile. No keys, device IDs, endpoints, TLS or Xray reload safety is changed.
Works on installed /usr/local/sbin/web-proxy-panelctl and bundled install-panel.sh.
"""
import argparse
import ast
from pathlib import Path

MARKER="# wpo-fast-subscription-runtime-v1"
ENTRY="def subscription_command():\n"
END="\ncmd=sys.argv[1] if len(sys.argv)>1 else \"init\""
OLD='''        changed=before["users"]!=after["users"]
        if changed:
            if any(u.get("enabled",True) and u.get("protocol")=="hysteria" for u in after["users"]):
                run(XRAY_TLS_SYNC,check=True)
            collect_traffic(before)
            try:
                sync_firewall(after)
                sync_xray(after)
                save(after)
            except Exception:
                # Database remains unchanged until both runtime components pass.
                # Restore only managed Xray/firewall; never restart WEB backends.
                try:
                    sync_firewall(before)
                    sync_xray(before)
                except Exception:
                    raise RuntimeError("Не удалось восстановить службы после ошибки; требуется диагностика VPS.")
                raise
        elif after!=before:
            save(after)
'''
NEW='''        # wpo-fast-subscription-runtime-v1
        # First Happ HWID claim of a preallocated slot only renames its user.
        # The existing keys were already applied by the successful create.
        # Do not restart Xray or rewrite nftables for a display-name update.
        changed=before["users"]!=after["users"]
        if changed and request.get("operation")=="fetch":
            def runtime_users(data):
                return [{k:v for k,v in user.items() if k!="name"}
                        for user in data["users"]]
            if runtime_users(before)==runtime_users(after):
                changed=False
        if changed:
            if any(u.get("enabled",True) and u.get("protocol")=="hysteria" for u in after["users"]):
                run(XRAY_TLS_SYNC,check=True)
            # Xray restart resets in-memory counters. Capture before reload.
            collect_traffic(before)
            # VLESS client records never create new firewall ports. Hysteria
            # changes need an nft/UFW update only when UDP listener goes
            # from zero users to active (or vice versa). Native user changes
            # retain a full firewall update, including all port rules.
            def firewall_signature(data):
                enabled=[u for u in data["users"] if u.get("enabled",True)]
                non_xray=[u for u in enabled
                          if u.get("protocol","web") not in ("vless","hysteria")]
                return (any(u.get("protocol")=="hysteria" for u in enabled),
                        non_xray)
            firewall_changed=(firewall_signature(before)!=firewall_signature(after))
            try:
                if firewall_changed:
                    sync_firewall(after)
                sync_xray(after)
                save(after)
            except Exception:
                # State is not committed until Xray is successfully active.
                # Do not recreate unrelated firewall tables on pure Xray edits.
                try:
                    if firewall_changed:
                        sync_firewall(before)
                    sync_xray(before)
                except Exception:
                    raise RuntimeError("Не удалось восстановить службы после ошибки; требуется диагностика VPS.")
                raise
        elif after!=before:
            save(after)
'''

def patch(source):
    if MARKER in source:
        return source
    if source.count(ENTRY)!=1 or source.count(END)!=1:
        raise ValueError("Unknown manager version; no changes")
    start=source.index(ENTRY)
    end=source.index(END,start)
    segment=source[start:end]
    if segment.count(OLD)!=1:
        raise ValueError("Unknown subscription runtime block; no changes")
    result=source[:start]+segment.replace(OLD,NEW,1)+source[end:]
    # Both the standalone manager and the embedded installer must stay valid.
    if source.startswith("#!/usr/bin/env python3"):
        ast.parse(result,filename="web-proxy-panelctl")
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    output=patch(args.input.read_text(encoding="utf-8"))
    args.output.write_text(output,encoding="utf-8")
    print("✓ Happ: первая регистрация устройства без лишнего перезапуска Xray")
    print("✓ Создание VLESS: без полного пересоздания nftables, если порты не изменились")
    print("✓ Настоящие изменения ключей и протоколов по-прежнему применяются и проверяются")

if __name__=="__main__":
    main()
