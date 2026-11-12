#!/usr/bin/env bash
# Minimal WPO v3 standalone VLESS Happ title UI repair. Does not modify Xray, clients or firewall.
set -Eeuo pipefail
[[ "$EUID" -eq 0 ]] || { echo 'Запустите с sudo.' >&2; exit 1; }
UI=/opt/tproxy-panel/wpp_ui.py
[[ -s "$UI" ]] || { echo "Нет файла $UI" >&2; exit 1; }
if grep -Fq '# wpo-happ-vless-title-v1' "$UI"; then
  echo 'Исправление заголовка Happ уже установлено.'
  exit 0
fi
BACKUP="/var/lib/tproxy-panel/happ-title-ui-backup-$(date -u +%Y%m%dT%H%M%SZ).py"
cp -a "$UI" "$BACKUP"
TOUCHED=0
finish() {
  rc=$?
  trap - EXIT
  if (( rc != 0 && TOUCHED == 1 )); then
    cp -a "$BACKUP" "$UI"
    systemctl reset-failed tproxy-panel.service 2>/dev/null || true
    systemctl restart tproxy-panel.service || true
    echo "Ошибка патча, интерфейс восстановлен из $BACKUP" >&2
  fi
  exit "$rc"
}
trap finish EXIT
python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import os
import sys
p=Path(sys.argv[1])
src=p.read_text(encoding='utf-8')
changes = [["            link=happ_import_link(routing_url)\n        records.append(dict(id=u['id'],name=u['name'],kind='direct',protocols=[proto],","            link=happ_import_link(routing_url)\n        # wpo-happ-vless-title-v1: Standalone VLESS uses Happ profile URL even without routing.\n        happ_url=routing_url\n        if proto=='vless' and not happ_url and callable(direct_profile_url):\n            happ_url=direct_profile_url(u,u.get('secret',''))\n            link=happ_import_link(happ_url)\n        records.append(dict(id=u['id'],name=u['name'],kind='direct',protocols=[proto],"],["link=link,raw_link=raw_link,routing_url=routing_url,source=u,devices=len(mt_devices),limit=len(mt_devices)))","link=link,raw_link=raw_link,routing_url=routing_url,happ_url=happ_url,source=u,devices=len(mt_devices),limit=len(mt_devices)))"],["            qr=(path+'/__qr?'+urlencode({'id':r['id']}) if proto in ('awg20','awg31') else","            qr=(path+'/direct-profile-qr?'+urlencode({'id':r['id'],'secret':source.get('secret',''),'import':'happ'}) if r.get('happ_url') else\n                path+'/__qr?'+urlencode({'id':r['id']}) if proto in ('awg20','awg31') else"],["            qr_kind='direct'\n            user_port=port","            qr_kind='routing' if r.get('routing_url') else 'happ' if r.get('happ_url') else 'direct'\n            user_port=port"],["        routed=bool(r.get('routing_url'))\n        qr=(path+'/subscription-qr?'","        routed=bool(r.get('routing_url'))\n        happ=bool(r.get('happ_url'))\n        qr=(path+'/subscription-qr?'"],["            path+'/direct-profile-qr?'+urlencode({'id':uid,'secret':r['source']['secret'],'import':'happ'}) if routed else","            path+'/direct-profile-qr?'+urlencode({'id':uid,'secret':r['source']['secret'],'import':'happ'}) if happ else"],["        copy_title='Копировать для Happ · JSON с маршрутизацией' if routed else 'Копировать'\n        qr_kind='routing' if routed else kind","        copy_title='Копировать для Happ · JSON с маршрутизацией' if routed else 'Копировать для Happ' if happ else 'Копировать'\n        qr_kind='routing' if routed else 'happ' if happ else kind"]]

for idx,(before,after) in enumerate(changes,1):
    count=src.count(before)
    if count!=1:
        raise SystemExit(f"Отмена без изменений: шаблон {idx}, совпадений {count}.")
    src=src.replace(before,after,1)
compile(src,str(p),"exec")
tmp=p.with_suffix(".happ-new")
tmp.write_text(src,encoding="utf-8")
tmp.chmod(p.stat().st_mode & 0o777)
os.replace(tmp,p)
PY_PATCH
TOUCHED=1
python3 -m py_compile "$UI"
systemctl reset-failed tproxy-panel.service 2>/dev/null || true
systemctl restart tproxy-panel.service
systemctl is-active --quiet tproxy-panel.service
echo 'Готово: VLESS QR/копирование использует Happ-профиль с заголовком клиента.'
echo "Резервная копия UI: $BACKUP"
echo 'Xray, Caddy, пользователи и VPN-ключи не изменены.'
