#!/usr/bin/env python3
"""WPO fast delete for standalone XHTTP/Hysteria users, with rollback.

Other protocols, primary WEB Proxy and managed subscriptions use the existing
trusted deletion paths. An Xray profile is committed to users.json only after
the Xray configuration has been successfully applied.
"""
import argparse
import ast
from pathlib import Path

MARKER="# wpo-fast-standalone-delete-v1"
BEGIN="def delete(uid):\n"
END="\ndef edit_user(uid,enabled=None,name=None):\n"
OLD='''    d["users"]=[u for u in d["users"] if u.get("id")!=uid]
    save(d)
    try:
        apply(d,True,before)
    except Exception:
        save(before)
        try: apply(before,True,d)
        except Exception: pass
        raise
    return True
'''
NEW='''    d["users"]=[u for u in d["users"] if u.get("id")!=uid]
    # wpo-fast-standalone-delete-v1: no expensive full WEB/MTProxy/AWG
    # unit discovery or firewall table rebuild for an ordinary Xray user.
    removed=next(u for u in before["users"] if u.get("id")==uid)
    if removed.get("protocol") in ("vless","hysteria"):
        old_hysteria=any(u.get("enabled",True) and u.get("protocol")=="hysteria"
                         for u in before["users"])
        new_hysteria=any(u.get("enabled",True) and u.get("protocol")=="hysteria"
                         for u in d["users"])
        firewall_changed=old_hysteria!=new_hysteria
        try:
            if firewall_changed:
                sync_firewall(d)
            sync_xray(d)
            save(d)
        except Exception:
            # sync_xray performs its own verified config rollback. Restore
            # previous credentials and listeners if any later step failed.
            try:
                if firewall_changed:
                    sync_firewall(before)
                sync_xray(before)
            except Exception:
                raise RuntimeError("Не удалось восстановить VPN после ошибки удаления.")
            raise
        return True
    save(d)
    try:
        apply(d,True,before)
    except Exception:
        save(before)
        try: apply(before,True,d)
        except Exception: pass
        raise
    return True
'''

def patch(source):
    if MARKER in source:
        return source
    if source.count(BEGIN)!=1 or source.count(END)!=1:
        raise ValueError("Unknown WPO manager version")
    start=source.index(BEGIN)
    end=source.index(END,start)
    block=source[start:end]
    if block.count(OLD)!=1:
        raise ValueError("Unexpected WPO delete implementation; no changes")
    result=source[:start]+block.replace(OLD,NEW,1)+source[end:]
    if source.startswith("#!/usr/bin/env python3"):
        ast.parse(result,filename="web-proxy-panelctl")
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    updated=patch(args.input.read_text(encoding="utf-8"))
    args.output.write_text(updated,encoding="utf-8")
    print("✓ Отдельные VLESS/Hysteria удаляются без общего перезапуска других служб")
    print("✓ При удалении последнего Hysteria сохраняется обязательное обновление firewall")
    print("✓ Ключи и Xray применяются до подтверждения удаления")

if __name__=="__main__":
    main()
