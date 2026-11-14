#!/usr/bin/env python3
"""Install WPO v28 user creation / multi-node form after Nodes Lab v26.

Usage on a controller: python3 wpo_v28_apply.py --app /opt/tproxy-panel
No reset or loss of users/subscriptions; targeted, idempotent source patch.
"""
import argparse
import ast
from pathlib import Path
import py_compile
import shutil


MARKER = "# wpo-v28-new-user"
PICKER = """    creation=creation.replace('<section class="create-step" id="subscriptionFields">','<section class="create-step" id="subscriptionFields">'+picker,1)"""
CREATE = """                result=ctl_subscription({"operation":"create","name":name,"max_devices":form.get("max_devices","0"),
                                         "connections":connection_specs,"node_ids":chosen_nodes})"""
ISSUE = """    if sub is None or not sub['enabled']:
        raise SubscriptionError('Подписка не найдена или отключена.', 404, 'not_found')"""
MANAGER = """def enforce_traffic_limits(state):
    before=load(); after=copy.deepcopy(before); exceeded=[]"""
PANEL_EXPIRED = """            if subscription is None:
                self.send_data("Not found",404); return"""


def swap(src, old, new, label):
    count = src.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source anchor, found {count}")
    return src.replace(old, new, 1)


def patch_ui(src):
    if MARKER in src:
        return src
    src = swap(src, "import json\n", "import json\nimport wpo_user_v28\n", "import user form module")
    src = swap(src, PICKER,
               PICKER + "\n    " + MARKER + "\n"
               + "    creation=wpo_user_v28.form(path,csrf,subscription_connections,nodes,local_node)",
               "insert form after node picker")
    src = swap(src, '＋ Добавить клиента', '＋ Новый пользователь', "user button label")
    return src


def patch_panel(src):
    if MARKER in src:
        return src
    src = swap(src, CREATE,
               """                # wpo-v28-new-user: UTC expiry parsed in the browser's local zone.
                try:
                    end_timestamp=int(form.get("expires_at","0"))
                    selected_gb=float(form.get("traffic_limit_gb","0") or "0")
                    if (not end_timestamp or end_timestamp<=int(time.time())+59
                            or time.gmtime(end_timestamp).tm_year>2090):
                        create_error("Выберите будущую дату окончания до 2090 года."); return
                    if selected_gb!=0:
                        create_error("Общий трафик на всех нодах пока не учитывается. Укажите 0 ГБ."); return
                except (ValueError,OverflowError,TypeError):
                    create_error("Некорректная дата или ограничение трафика."); return
                result=ctl_subscription({"operation":"create","name":name,"max_devices":form.get("max_devices","0"),
                                         "connections":connection_specs,"node_ids":chosen_nodes,
                                         "expires_at":end_timestamp})""",
               "create with expiry")
    src = swap(src, PANEL_EXPIRED,
               PANEL_EXPIRED +
               '\n            if int(subscription.get("expires_at",0) or 0) and int(subscription["expires_at"])<=int(time.time()):'
               '\n                self.send_data("Срок действия истёк.",410); return',
               "reject expired public subscription URL")
    return src


def patch_subscriptions(src):
    if MARKER in src:
        return src
    helper = '''# wpo-v28-new-user
def validate_expiry(value):
    if value in (None, 0, "0", ""): return 0
    try:
        expiry=int(value)
        now=int(time.time())
        if expiry<=now+59 or time.gmtime(expiry).tm_year>2090:
            raise SubscriptionError("Дата окончания должна быть в будущем, до 2090 года.")
        return expiry
    except (ValueError,OverflowError,TypeError):
        raise SubscriptionError("Некорректная дата окончания.")

'''
    src = swap(src, 'def mutate(data, request):', helper + 'def mutate(data, request):',
               "validate expiry")
    src = swap(src, "'max_devices': limits(request.get('max_devices', 0)),",
               "'max_devices': limits(request.get('max_devices', 0)),\n"
               "               'expires_at':validate_expiry(request.get('expires_at',0)),",
               "persist expiry")
    src = swap(src, "            limit = limits(request.get('max_devices', sub['max_devices']))",
               "            if 'expires_at' in request: sub['expires_at']=validate_expiry(request['expires_at'])\n"
               "            limit = limits(request.get('max_devices', sub['max_devices']))",
               "update expiry")
    src = swap(src, ISSUE,
               ISSUE +
               "\n    if int(sub.get('expires_at',0) or 0) and int(sub['expires_at'])<=int(time.time()):"
               "\n        raise SubscriptionError('Срок действия подписки истёк.', 403, 'expired')",
               "reject expired device issue")
    return src


def patch_manager(src):
    if MARKER in src: return src
    new = """def enforce_traffic_limits(state):
    # wpo-v28-new-user: expiry is enforced for established local connections
    # as well as for new subscription fetches, not only in the browser.
    before=load(); after=copy.deepcopy(before); exceeded=[]
    now=int(time.time())
    for sub in after.get("subscriptions",[]):
        if not sub.get("enabled",True): continue
        deadline=int(sub.get("expires_at",0) or 0)
        if not deadline or now<deadline: continue
        sub["enabled"]=False
        for user in after.get("users",[]):
            if user.get("subscription_id")==sub.get("id") and user.get("enabled",True):
                user["enabled"]=False
                user["disabled_reason"]="expired"
                exceeded.append(user.get("id"))
    expired_subscriptions = [
        x for x in after.get("subscriptions",[])
        if x.get("enabled",True)==False and int(x.get("expires_at",0) or 0) and now>=int(x["expires_at"])
    ]
"""
    src = swap(src, MANAGER, new, "enforce subscription expiry")
    src = swap(src, "    if not exceeded:\n        return []",
               "    if not exceeded and after==before:\n        return []",
               "commit expired subscription state")
    return src


def apply(app, manager, helper):
    targets={
        app/"wpp_ui.py":patch_ui,
        app/"panel.py":patch_panel,
        app/"wpp_subscriptions.py":patch_subscriptions,
        manager:patch_manager,
    }
    contents={}
    for path, updater in targets.items():
        old=path.read_text(encoding="utf-8")
        new=updater(old)
        if new != old:
            ast.parse(new,filename=str(path))
        contents[path]=(old,new)
    module=app/"wpo_user_v28.py"
    if not helper.is_file():
        raise RuntimeError("Missing WPO v28 user form")
    ast.parse(helper.read_text(encoding="utf-8"), filename=str(helper))
    backups=[]
    try:
        if not module.exists() or module.read_bytes()!=helper.read_bytes():
            if module.exists():
                saved=module.with_suffix(".v28-prev")
                shutil.copy2(module,saved)
                backups.append((module,saved))
            else:
                backups.append((module,None))
            shutil.copy2(helper,module)
            module.chmod(0o644)
        for path,(old,new) in contents.items():
            if old==new: continue
            saved=path.with_suffix(path.suffix+".v28-prev")
            shutil.copy2(path,saved)
            backups.append((path,saved))
            tmp=path.with_suffix(path.suffix+".v28-tmp")
            tmp.write_text(new,encoding="utf-8")
            tmp.chmod(path.stat().st_mode & 0o777)
            tmp.replace(path)
    except Exception:
        for path,saved in reversed(backups):
            if saved is None:
                path.unlink(missing_ok=True)
            else:
                shutil.copy2(saved,path)
        raise
    return [str(path) for path,(old,new) in contents.items() if old!=new]


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--app",type=Path,default=Path("/opt/tproxy-panel"))
    parser.add_argument("--manager",type=Path,default=Path("/usr/local/sbin/web-proxy-panelctl"))
    parser.add_argument("--helper",type=Path,default=Path(__file__).with_name("wpo_user_v28.py"))
    args=parser.parse_args()
    print("Updated:", ", ".join(apply(args.app,args.manager,args.helper)) or "already current")
