#!/usr/bin/env python3
"""WPO V15: RU/EN labels without duplicate spans or layout changes."""
from pathlib import Path
import os,shutil,stat,subprocess,tempfile,time,sys
from datetime import datetime,timezone

p=Path('/opt/tproxy-panel/wpp_ui.py')
marker='# WPO_LANGUAGE_SAFE_V15'
old="el.querySelector('b').textContent=state[0]"
new="el.querySelector('b').textContent=document.documentElement.dataset.wpoLanguage==='en'?({online:'Online',installing:'Installing',registration:'Registration',offline:'Offline',error:'Error'}[state[1]]||'Offline'):state[0]"
addon=r'''
# WPO_LANGUAGE_SAFE_V15: original text nodes only; no new HTML/CSS.
_WPO_V15_MAP=r"""ruToEn['⚙️ Управление нодами']='⚙️ Node management';
ruToEn['Управление нодами']='Node management';
ruToEn['Будет назначен']='Will be assigned';
ruToEn['при создании клиента']='when a client is created';
"""
_WPO_V15_TEMPLATE=r""" const nodeTemplate=key.match(/^Шаблон:\s*(.+)$/u);
 if(nodeTemplate){
  const builtIn={'Салон красоты':'Beauty salon','Автосалон':'Car dealership',
   'Открытие кофейни':'Coffee shop opening','Стандартная страница ноды':'Standard node page'};
  return left+'Template: '+(builtIn[nodeTemplate[1]]||nodeTemplate[1])+right;
 }
"""
_WPO_V15_PORT=r"""function wpoV15PortText(){
 document.querySelectorAll('.connection-port-empty').forEach(el=>{
  for(const n of el.childNodes)if(n.nodeType===3)translateText(n);
  const small=el.querySelector('small');
  if(small)for(const n of small.childNodes)if(n.nodeType===3)translateText(n);
 });
}
"""
for before,after in (
 ('const originalText=new WeakMap()',_WPO_V15_MAP+'const originalText=new WeakMap()'),
 (' const fleet=key.match(',_WPO_V15_TEMPLATE+' const fleet=key.match('),
 ('function controls(){',_WPO_V15_PORT+'function controls(){'),
 (' scan(document.body);\n controls();',' scan(document.body);\n wpoV15PortText();\n controls();'),
):
 if WPO_C333_I18N_JS.count(before)!=1:
  raise RuntimeError('WPO i18n changed; V15 refused to start')
 WPO_C333_I18N_JS=WPO_C333_I18N_JS.replace(before,after,1)
'''

def change(src):
 if marker in src:
  print('✓ V15 уже установлен');return src,False
 for m in ('# WPO_C333_STABLE_DYNAMIC_I18N_V11','# WPO_NODES_EN_QUIET_V13','setInterval(refresh,1000)'):
  if m not in src:raise RuntimeError('Неизвестная версия WPO: '+m)
 if '# WPO_NODES_STABLE_EN_V14' in src:raise RuntimeError('Сначала откати V14')
 if 'querySelector("[data-node-edit]")?.dataset.nodeName' not in src or 'querySelector(".wpo-node-label h3")?.textContent.trim()' in src:
  raise RuntimeError('Рабочее исправление перезагрузки Нод не найдено; ничего не меняем')
 if src.count(old)!=1:raise RuntimeError('Статусы нод изменились; ничего не меняем')
 dst=src.replace(old,new,1)+'\n'+addon
 compile(dst,str(p),'exec')
 print('✓ Статусы нод EN/RU без остановки обновления')
 print('✓ Заголовок «Node management» без второго текста')
 print('✓ Шаблоны: перевод подписи и встроенных названий')
 print('✓ PORT: «Will be assigned when a client is created»')
 print('✓ Размеры блоков, HTML, данные нод и клиентов не изменены')
 return dst,True

def running():return subprocess.run(['systemctl','is-active','--quiet','tproxy-panel.service']).returncode==0

def main():
 if os.geteuid()!=0:raise RuntimeError('Нужен sudo')
 if len(sys.argv)!=2 or sys.argv[1] not in ('--check','--apply'):raise RuntimeError('Укажи --check или --apply')
 if not p.is_file() or p.is_symlink():raise RuntimeError('Не найден файл панели')
 dst,changed=change(p.read_text(encoding='utf-8'))
 if sys.argv[1]=='--check':print('✓ Проверка успешна, ничего не изменено');return
 if not changed:return
 if not running():raise RuntimeError('WPO не работала до исправления')
 bdir=Path('/var/backups/web-panel-online');bdir.mkdir(parents=True,exist_ok=True)
 backup=bdir/('wpp_ui-before-v15-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.py')
 if backup.exists():raise RuntimeError('Резервная копия уже существует')
 shutil.copy2(p,backup);os.chmod(backup,0o600);print('✓ Резервная копия:',backup)
 tmp=None;modified=False
 try:
  with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=p.parent,prefix='.wpo-v15-',suffix='.py',delete=False) as f:
   f.write(dst);tmp=Path(f.name)
  st=p.stat();os.chmod(tmp,stat.S_IMODE(st.st_mode));os.chown(tmp,st.st_uid,st.st_gid)
  os.replace(tmp,p);modified=True
  subprocess.run(['systemctl','restart','tproxy-panel.service'],check=True,timeout=45)
  for _ in range(12):
   if running():print('✓ WPO работает. V15 установлен');return
   time.sleep(1)
  raise RuntimeError('WPO не запустилась')
 except Exception:
  if modified:
   shutil.copy2(backup,p)
   subprocess.run(['systemctl','restart','tproxy-panel.service'],check=False)
   print('! Прежняя версия восстановлена')
  raise
 finally:
  if tmp:tmp.unlink(missing_ok=True)

if __name__=='__main__':
 try:main()
 except Exception as e:print('ОШИБКА:',e,file=sys.stderr);sys.exit(1)
