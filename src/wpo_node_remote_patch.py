#!/usr/bin/env python3
"""Attach remote-native profile creation, download, cards and revocation to WPO."""
import argparse
import ast
from pathlib import Path
import shutil

MARKER = "# wpo-remote-native-v04"
IMPORT = "import wpp_nodes as node_api\n"
GET = '        if path==PANEL_PATH+"/users":'
USERS = '            self.send_html(layout("Клиенты",body,"users")); return'
CREATE = '            if kind=="subscription":'
POST = '        if path==PANEL_PATH+"/create-account":'


def once(src,old,new,label):
    count=src.count(old)
    if count!=1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return src.replace(old,new,1)


def patch(source):
    if MARKER in source:
        return source
    source=once(source,IMPORT,IMPORT+"import wpo_node_remote\n","import remote module")
    getter = '''        # wpo-remote-native-v04: authenticated AWG config download.
        if path==PANEL_PATH+"/remote-user-config":
            uid=parse_qs(urlparse(self.path).query).get("id",[""])[0]
            try:
                config,filename=wpo_node_remote.config(uid)
            except ValueError:
                self.send_data("Not found",404); return
            body=config.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type","text/plain; charset=utf-8")
            self.send_header("Cache-Control","no-store")
            self.send_header("Content-Disposition",'attachment; filename="'+filename+'"')
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

'''
    source=once(source,GET,getter+GET,"download route")
    source=once(source,USERS,
        '''            body+=wpo_node_remote.cards(PANEL_PATH,self.csrf())
''' + USERS,"remote user cards")
    post = '''        if path==PANEL_PATH+"/remote-user-action":
            uid=form.get("id","")
            try:
                wpo_node_remote.remove(uid,node_api.load_nodes(NODES_FILE))
                self.redirect("/users")
            except (ValueError,node_api.NodeError) as exc:
                self.send_html(esc(str(exc)),409)
            return

'''
    source=once(source,POST,post+POST,"remote deletion route")
    create = '''            # Remote native protocols are separate node profiles, not Happ
            # subscription lines. A single node must be selected.
            if (kind in wpo_node_remote.NATIVE
                    and form.get("nodes_selector_present")=="1"):
                chosen=selected_node_ids(form)
                if len(chosen)!=1:
                    create_error("Для этого протокола выберите ровно одну ноду."); return
                if chosen[0]!="local":
                    try:
                        wpo_node_remote.create(chosen[0],name,kind,
                            node_api.load_nodes(NODES_FILE),form.get("expires_at",0))
                    except (ValueError,node_api.NodeError) as exc:
                        create_error(str(exc),409); return
                    except OSError:
                        create_error("Нода создала профиль, но панель не сохранила его. Проверьте журнал.",503); return
                    if async_create: self.send_json({"ok":True})
                    else: self.redirect("/users")
                    return
'''
    source=once(source,CREATE,create+CREATE,"remote creation")
    ast.parse(source,filename="panel.py")
    return source


def apply(app,helper):
    panel=app/"panel.py"
    target=app/"wpo_node_remote.py"
    if not helper.is_file():
        raise RuntimeError("Remote user module missing")
    source=panel.read_text()
    modified=patch(source)
    ast.parse(helper.read_text(),filename=str(helper))
    if modified==source and target.is_file() and target.read_bytes()==helper.read_bytes():
        return []
    backups=[]
    try:
        if modified!=source:
            backup=panel.with_suffix(".remote-v04.bak")
            shutil.copy2(panel,backup)
            backups.append((panel,backup))
            tmp=panel.with_suffix(".remote-v04.tmp")
            tmp.write_text(modified)
            tmp.chmod(panel.stat().st_mode&0o777)
            tmp.replace(panel)
        if not target.is_file() or target.read_bytes()!=helper.read_bytes():
            if target.is_file():
                backup=target.with_suffix(".remote-v04.bak")
                shutil.copy2(target,backup)
                backups.append((target,backup))
            else:
                backups.append((target,None))
            shutil.copy2(helper,target)
            target.chmod(0o644)
    except Exception:
        for p,backup in reversed(backups):
            if backup is None: p.unlink(missing_ok=True)
            else: shutil.copy2(backup,p)
        raise
    return [str(p) for p,_ in backups]


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--app",type=Path,default=Path("/opt/tproxy-panel"))
    p.add_argument("--helper",type=Path,default=Path(__file__).with_name("wpo_node_remote.py"))
    args=p.parse_args()
    print("Remote native patch:",apply(args.app,args.helper))
