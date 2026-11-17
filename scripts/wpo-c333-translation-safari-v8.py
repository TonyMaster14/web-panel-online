#!/usr/bin/env python3
"""WPO c333e00: restore complete dynamic RU/EN on the existing safe UI.

Edits only /opt/tproxy-panel/wpp_ui.py; backs up and rolls back on failure.
No changes to routes, node/protocol IDs, backend data or form field names.
"""
import ast
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import urlopen

APP=Path('/opt/tproxy-panel')
TARGET=APP/'wpp_ui.py'
SERVICE='tproxy-panel.service'
NEW_MARK='# WPO_C333_I18N_V8_PRELOAD'
OLD_MARK='# WPO_C333_LANGUAGE_THEME_V1'

PRELOAD_HELPER = "\n# WPO_C333_V8_PRE_RENDER_TRANSLATE_NO\ndef _wpo_c333_v8_safari_preflight(markup):\n    \"\"\"Markup-only browser hint: it runs before Safari decides to offer native translation.\"\"\"\n    if '<html lang=\"ru\">' not in markup:\n        return markup\n    preload = (\n        '<meta name=\"google\" content=\"notranslate\">'\n        '<style>html.wpo-en-prepaint body{visibility:hidden!important}</style>'\n        '<script>(function(){try{if(localStorage.getItem(\"wpo-language\")===\"en\"){'\n        'document.documentElement.classList.add(\"wpo-en-prepaint\");'\n        'setTimeout(function(){document.documentElement.classList.remove(\"wpo-en-prepaint\")},1400)'\n        '}}catch(e){}})();</script>'\n    )\n    return (markup.replace('<html lang=\"ru\">','<html lang=\"ru\" translate=\"no\">',1)\n                  .replace('<head>','<head>'+preload,1))\n\n_WPO_C333_V8_PREVIOUS_LOGIN = login_ui\ndef login_ui(path):\n    return _wpo_c333_v8_safari_preflight(_WPO_C333_V8_PREVIOUS_LOGIN(path))\n\n_WPO_C333_V8_PREVIOUS_PAGE = page_layout\ndef page_layout(*args, **kwargs):\n    return _wpo_c333_v8_safari_preflight(_WPO_C333_V8_PREVIOUS_PAGE(*args, **kwargs))\n"

LANGUAGE_JS = r'''<script>
(()=>{
'use strict';
const dictionary=__DICTIONARY__;
const extraPairs=[["ID","ID"],["ENABLED","ВКЛЮЧЕНО"],["CONNECTION","ПОДКЛЮЧЕНИЕ"],["ROUTE","МАРШРУТ"],["PORT","ПОРТ"],["PROTOCOL","ПРОТОКОЛ"],["CLIENTS","КЛИЕНТЫ"],["Enabled","Включено"],["Disabled","Отключено"],["Direct","Напрямую"],["Main panel domain","Основной домен панели"],["Main connection","Основное подключение"],["Main node","Основная нода"],["Online","В сети"],["Installing","Установка"],["Registration","Регистрация"],["Offline","Не в сети"],["Error","Ошибка"],["Add node","Добавить ноду"],["Template","Шаблон"],["Node management","Управление нодами"],["Server resources","Ресурсы сервера"],["Cumulative traffic","Суммарный трафик"],["Total traffic","Всего трафика"],["Proxy traffic","Трафик прокси"],["CPU","Процессор"],["Memory","Память"],["Swap","Подкачка"],["Disk","Диск"],["Clients","Клиенты"],["Subscriptions","Подписки"],["Subscription","Подписка"],["Traffic","Трафик"],["Total","Всего"],["Transferring traffic","Передают трафик"],["Online now","Сейчас в сети"],["Services and version","Службы и версия"],["Running","Работает"],["Stopped","Остановлено"],["Server status","Состояние сервера"],["Upload","Отправка"],["Download","Получение"],["Sent","Отправлено"],["Received","Получено"],["Last measurement","Последний замер"],["Users and subscriptions","Пользователи и подписки"],["Management","Управление"],["Access / QR","Доступ / QR"],["Separate link","Отдельная ссылка"],["Search by client name","Поиск по имени клиента"],["All clients","Все клиенты"],["All protocols","Все протоколы"],["Default order","Обычный порядок"],["Access","Доступ"],["Protocols","Протоколы"],["Users","Пользователи"],["User","Пользователь"],["No traffic","Нет трафика"],["Subscriptions and individual client connections","Подписки и отдельные подключения клиентов"],["VPS uptime","Время работы VPS"],["Xray uptime","Время работы Xray"],["Xray memory","Память Xray"],["Xray tasks","Задачи Xray"],["Proxy traffic only. Activity means traffic in the last 90 seconds, not the number of connected devices.","Только трафик прокси. Активность означает передачу данных за последние 90 секунд, а не число подключённых устройств."],["Update center","Центр обновлений"],["Update management","Управление обновлениями"],["Refresh lists","Обновить списки"],["Stable · automatic","Стабильная · автоматически"],["Automatically install new versions","Автоматически устанавливать новые версии"],["Automatically update Xray and OpenFlux","Автоматически обновлять Xray и OpenFlux"],["Every 6 hours WPP checks GitHub and installs only a new stable release.","Раз в 6 часов WPO проверяет GitHub и устанавливает только новую стабильную версию."],["You can install a new version or return to the previous one. The rollback copy is kept only during installation.","Можно установить новую версию или вернуться к предыдущей. Копия для отката хранится только во время установки."],["WEB PANEL ONLINE","WEB PANEL ONLINE"],["Interface, connection manager, and service modules","Интерфейс, управление подключениями и служебные модули"],["Components","Компоненты"],["Core","Основное"],["Installed version","Установленная версия"],["Available version","Доступная версия"],["Version","Версия"],["Install","Установить"],["Load version list","Загрузить список версий"],["Versions loaded.","Версии загружены."],["Xray and OpenFlux update independently of the panel","Xray и OpenFlux обновляются независимо от панели"],["Diagnostics and recovery","Диагностика и восстановление"],["Diagnostics","Диагностика"],["Recovery","Восстановление"],["Public CDN","Публичный CDN"],["WPP origin","Исходный сервер WPO"],["DNS, TLS, edge responses and caching","DNS, TLS, ответы CDN и кэширование"],["HTTPS, Host and Caddy test route","HTTPS, Host и проверочный маршрут Caddy"],["Provider method, path and local inbound","Метод провайдера, путь и локальный входящий порт"],["The check finds issues, and recovery safely rebuilds only local WPP components.","Проверка выявляет проблемы, а восстановление безопасно пересоздаёт только локальные компоненты WPO."],["No VLESS CDN connections created","Подключения VLESS CDN ещё не созданы"],["Check","Проверить"],["No check has been run yet","Проверка ещё не запускалась"],["Results and recommendations will appear here.","Здесь появятся результаты и рекомендации."],["Site templates","Шаблоны сайтов"],["Create a custom placeholder","Создать свой шаблон"],["Create","Создать"],["Preview","Предпросмотр"],["Apply","Применить"],["Click Preview to see the site. Apply publishes it to the domain immediately.","Нажмите «Предпросмотр», чтобы увидеть сайт. «Применить» сразу опубликует его на домене."],["Name, description, and custom HTML. The template will appear in this collection.","Название, описание и свой HTML. Шаблон появится в этой коллекции."],["Beauty salon","Салон красоты"],["Car showroom","Автосалон"],["Car service","Автосервис"],["Open coffee shop","Открытие кофейни"],["Medical clinic","Медицинская клиника"],["Smartphone repair","Ремонт смартфонов"],["Diagnostic center","Центр диагностики"],["Settings backup","Резервная копия настроек"],["Stored on your computer","Хранится на вашем компьютере"],["Download backup","Скачать резервную копию"],["Select archive","Выбрать архив"],["Install backup","Установить копию"],["Administrator password","Пароль администратора"],["New password","Новый пароль"],["Save password","Сохранить пароль"],["Settings","Настройки"],["Dashboard","Главная"],["Updates","Обновления"],["Connection manager","Управление подключениями"],["Connection","Подключение"],["Connections","Подключения"],["Nodes","Ноды"],["Node","Нода"],["Select connection","Выберите подключение"],["Select protocol","Выберите протокол"],["Select node","Выберите ноду"],["Select template","Выберите шаблон"],["New user","Новый пользователь"],["Add user","Добавить пользователя"],["Create client","Создать клиента"],["Save","Сохранить"],["Cancel","Отмена"],["Delete","Удалить"],["Edit","Изменить"],["Copy","Копировать"],["Copied","Скопировано"],["Open","Открыть"],["Close","Закрыть"],["Back","Назад"],["Next","Далее"],["Update","Обновить"],["Status","Статус"],["Services","Службы"],["Name","Название"],["Date","Дата"],["Time","Время"],["Domain","Домен"],["Port","Порт"],["Protocol","Протокол"],["No clients","Нет клиентов"],["No nodes","Нет нод"],["Loading","Загрузка"],["Loading…","Загрузка…"],["Waiting","Ожидание"],["Unknown","Неизвестно"],["Available","Доступно"],["Active","Активно"],["Inactive","Неактивно"],["Automatic","Автоматически"],["Manual","Вручную"],["On","Вкл."],["Off","Выкл."],["Traffic statistics","Статистика трафика"],["Sent traffic","Отправленный трафик"],["Received traffic","Полученный трафик"],["Copy link","Скопировать ссылку"],["Copy config","Скопировать конфигурацию"],["QR code","QR-код"],["Client status","Статус клиента"],["No updates available","Нет доступных обновлений"],["All services running","Все службы работают"],["Not used","Не используется"],["Not configured","Не настроено"],["Not assigned","Не назначено"],["Will be assigned when a client is created","Будет назначен при создании клиента"],["Security","Безопасность"],["Country","Страна"],["View","Просмотр"],["Main panel","Основная панель"],["Main domain","Основной домен"],["1 h","1 ч"],["6 h","6 ч"],["24 h","24 ч"],["24 hours","24 часа"],["Last 24 hours","Последние 24 часа"],["Last 1 hour","Последний час"],["Last 6 hours","Последние 6 часов"],["Separate connection","Отдельное подключение"],["Search","Поиск"],["Client","Клиент"],["Client access","Доступ клиента"],["Client connections","Подключения клиента"],["Summary","Сводка"],["None","Нет"],["Default","По умолчанию"],["active traffic first","сначала передающие данные"],["Automatic updates are enabled. Stable releases are checked every 6 hours.","Автообновление включено. Проверка стабильных релизов выполняется каждые 6 часов."],["At least 3 characters · changing the password will end all panel sessions","Минимум 3 символа · смена пароля завершит все сессии панели"],["Every 6 hours","Раз в 6 часов"],["One hour","1 час"],["Panel management","Панель управления"],["No additional nodes","Дополнительных нод нет"],["No connection yet","Нет подключений"],["Selected protocol","Выбранный протокол"],["Connection status","Статус подключения"],["Connection type","Тип подключения"],["Checking…","Проверяем…"],["Ready","Готово"],["Showing","Показано"],["Not available","Недоступно"],["direct","напрямую"],["main","основной"],["separate profile","отдельный профиль"],["separate port","отдельный порт"],["separate TLS port","отдельный TLS-порт"],["A modern dark service page with progress, steps, and system status indicators.","Современная тёмная страница обслуживания с прогрессом, этапами и статусами системы."],["A new coffee shop-inspired variation: a dark palette, expressive typography, and a booking section.","Новый вариант в стилистике кофейни: тёмная палитра, выразительная типографика и блок записи."],["A stylish service center template with a technical look: dark background, feature cards, and clear service descriptions.","Стильный шаблон сервисного центра в стилистике технической страницы: тёмный фон, карточки с блоками и понятные услуги."],["Every 6 hours, the latest numbered version is installed. Test builds are available for manual selection only. Before replacement a temporary backup is created, and a broken version is rolled back.","Раз в 6 часов устанавливается самая новая номерная версия. Тестовые сборки доступны только для ручного выбора. Перед заменой создаётся временная копия, а неисправная версия откатывается."],["Clients, subscriptions, keys, connections, nodes, OpenFlux, site, and panel account","Клиенты, подписки, ключи, подключения, ноды, OpenFlux, сайт и учётная запись панели"],["The panel will prepare a temporary rollback before installation and remove it after verification. Connections may be briefly interrupted.","Перед установкой панель подготовит временный откат и удалит его после проверки. Подключения могут кратковременно прерваться."],["Opening hours","График работы"],["Contact details","Контакты"],["Selected connection","Выбранное подключение"],["Main","Основной"],["Netherlands","Нидерланды"],["Sweden","Швеция"],["Poland","Польша"],["Separate profile","Отдельный профиль"],["No routes have been configured","Правила маршрутизации не настроены"],["Save changes","Сохранить изменения"],["Change password","Сменить пароль"],["Transfer","Передача"],["Shown 2 of 2 · active traffic first","Показано 2 из 2 · сначала передающие данные"],["A live opening page with address, opening hours, phone number and countdown timer.","Живая страница открытия с адресом, графиком, телефоном и таймером."],["A realistic car showcase with photos, prices and contact information.","Реалистичная витрина автомобилей с фотографией, ценами и контактами."],["A ready-to-use order-tracking page with route, order number and support.","Готовая страница отслеживания с маршрутом, номером заказа и поддержкой."],["A premium car service website in the same dark style, with services, prices, benefits and booking.","Премиальный сайт автоцентра в той же тёмной стилистике: услуги, цены, преимущества и запись."],["An additional medical template in a light turquoise clinic style, with examinations, departments and appointments.","Дополнительный медицинский шаблон в светлой бирюзовой стилистике клиники: обследования, направления и запись."],["A modern clinic page with services, prices, contact details and appointment booking.","Современная страница клиники с услугами, ценами, контактами и записью на приём."],["The archive contains passwords and secret keys. Keep it in a safe place. After restoration, the username and password in the archive are used. No permanent backup copies are created on the VPS.","Архив содержит пароли и секретные ключи. Храните его в безопасном месте. После восстановления действуют логин и пароль из архива. На VPS постоянные копии не создаются."],["The archive contains passwords and secret keys.","Архив содержит пароли и секретные ключи."],["Keep it in a safe place.","Храните его в безопасном месте."],["Technical maintenance","Технические работы"],["A new service center template with a technical look: dark background, status blocks and clear services.","Новый шаблон сервисного центра в стилистике технической страницы: тёмный фон, статусные блоки и понятные услуги."],["A new variation in coffee shop style: warm palette, expressive typography and a booking section.","Новый вариант в стилистике кофейни: тёплая палитра, выразительная типографика и блок записи."],["Modern dark maintenance page with progress, stages and system status indicators.","Современная тёмная страница обслуживания с прогрессом, этапами и статусами систем."],["The archive contains a password and secret keys. Keep it in a safe place. After restoring, the username and password from the archive will apply. No permanent copies are created on the VPS.","Архив содержит пароль и секретные ключи. Храните его в безопасном месте. После восстановления действуют логин и пароль из архива. На VPS постоянные копии не создаются."],["For up to 24 hours · approximately 1-minute sampling · UTC","До 24 часов · замер ~1 мин · UTC"],["Update the connection after changing routing","Обновите подключение после изменения маршрутизации"],["Update the subscription in your VPN app.","Обновите подписку в VPN-приложении."],["After restoring, the username and password from the archive will apply.","После восстановления действуют логин и пароль из архива."],["No permanent copies are created on the VPS.","На VPS постоянные копии не создаются."],["The archive contains a password and secret keys.","Архив содержит пароль и секретные ключи."],["Disabled","Отключена"],["Disabled","Отключен"],["No data transmission","Нет передачи данных"],["Data transfer","Передача данных"],["Select an account","Выберите аккаунт"],["What do access, activity and HWID mean?","Что означают доступ, активность и HWID?"],["All accounts","Все аккаунты"],["New connection","Новое подключение"],["Transfer active","Передача активна"],["Choose a connection to configure rules","Выберите подключение для настройки правил"],["A new version is installed","Установлена новая версия"],["Days","Дни"],["Hour","Час"],["Hours","Часы"],["Minutes","Минуты"],["seconds ago","секунд назад"],["minutes ago","минут назад"],["No traffic for the last 90 seconds","Нет трафика за последние 90 секунд"],["No data","Нет данных"],["A system check has not yet been run.","Проверка системы ещё не выполнялась."],["Clear","Очистить"],["Open settings","Открыть настройки"],["Saved","Сохранено"],["Saving","Сохранение"],["The current connection","Текущее подключение"],["No updates found","Обновлений не найдено"],["Subscriptions","Подписок"],["Will be assigned","Будет назначен"],["when a client is created","при создании клиента"],["Main WEB Proxy","Основной WEB Proxy"],["Load · 1 / 5 / 15 min.","Нагрузка · 1 / 5 / 15 мин."],["Check","Проверка"],["Total traffic","Всёго трафика"],["Status","Состояние"],["Cores","Ядер"],["hypervisor","гипервизор"],["No connection","Нет подключения"],["Select only the rules you want to add or remove.","Отметьте только те правила, которые нужно добавить или убрать."],["Disabled","Отключён"],["Routing","Маршрутизация"],["Dashboard","Дашборд"],["Show","Показать"],["Hide","Скрыть"],["Not connected","Не подключён"],["Password","Пароль"],["min ago","мин. назад"],["s ago","с назад"],["client","клиента"],["Unified subscription link","Единая ссылка подписки"],["Subscription QR code","QR подписки"],["Maximum devices (HWID), 0 = unlimited","Максимум устройств (HWID), 0 — без привязки"],["Switching between zero and a HWID limit revokes old keys. A subscription update does not mean the device is currently online.","При переходе между 0 и HWID-лимитом старые ключи отзываются. «Обновление подписки» не означает, что устройство сейчас онлайн."],["Devices will appear after importing the subscription in the client.","Устройства появятся после импорта подписки в клиент."],["Change link and reset devices","Сменить ссылку и сбросить устройства"],["One link: VLESS XHTTP + Hysteria2","Одна ссылка: VLESS XHTTP + Hysteria2"],["The limit counts the HWID sent by the client, such as Happ, rather than IP addresses or connection count. Clients without a HWID will not receive a configuration while the limit is enabled. Separate keys are created for each device.","Лимит учитывает HWID, переданный клиентом (например, Happ), а не IP и не число соединений. Клиенты без HWID при включённом лимите не получат конфигурацию. Для каждого устройства создаются отдельные ключи."],["HWID can be spoofed and the issued key can be copied. This controls registration and revocation, not guaranteed hardware binding. WEB Proxy remains a separate Telegram link. Initial registration and revocation briefly restart Xray.","HWID можно подделать, а полученный ключ — скопировать. Это контроль регистрации и отзыва, не гарантированная аппаратная привязка. WEB Proxy остаётся отдельной Telegram-ссылкой. Первая регистрация и отзыв устройства кратковременно перезапускают Xray."],["New subscription","Новая подписка"],["Create subscription","Создать подписку"],["There are no subscriptions yet. Older individual connections remain under Users.","Подписок пока нет. Старые отдельные подключения сохранены во вкладке «Пользователи»."],["Open in draft","Открыть в черновике"],["The preset opens in a draft. The live website changes only after publication. The current draft will be replaced.","Пресет открывается в черновике. Рабочий сайт изменится только после публикации. Текущий черновик будет заменён."],["Preview is isolated from the panel. External resources, forms and network requests are blocked; styles and scripts must be inside the HTML. Restrictions on the live site may differ, so verify the page after publishing.","Предпросмотр изолирован от панели. Внешние ресурсы, формы и сетевые запросы заблокированы; стили и скрипты должны быть внутри HTML. В живом сайте ограничения могут отличаться — после публикации проверьте страницу."],["Save draft","Сохранить черновик"],["Publish to site","Опубликовать на сайте"],["Delete draft","Удалить черновик"],["Click Preview to view the current code without publishing.","Нажмите «Предпросмотр», чтобы увидеть текущий код без публикации."],["The toggle controls access permission; activity means data was transmitted in the last 90 seconds, not that a device is precisely online. OpenFlux shows the state of its separate profile service.","Переключатель управляет разрешением доступа, а активность означает передачу данных за последние 90 секунд — не точное присутствие онлайн. Для OpenFlux отображается состояние отдельной службы профиля."],["The HWID limit restricts registration of client identifiers. HWID and keys can be copied; this is not hardware security. GB quotas and expiry are not configured here. The main connection is protected against accidental disabling and can only be deleted separately with confirmation.","Лимит HWID ограничивает регистрацию идентификаторов клиента. HWID и ключ можно скопировать: это не аппаратная защита. Квоты гигабайтов и срок действия здесь не настроены. Основное подключение защищено от случайного отключения; удалить его можно только отдельной корзиной с подтверждением."],["Changing access can briefly restart services. When performing bulk actions, clients are processed sequentially; OpenFlux has its own toggle in this table.","Изменение доступа может кратковременно перезапустить службы. При массовом действии клиенты обрабатываются последовательно; OpenFlux управляется своим переключателем в этой таблице."],["Every AWG client receives unique keys, a port, subnet and obfuscation parameters. If your VPS provider has a cloud firewall, allow the shown UDP port.","Каждый AWG-клиент получает собственные ключи, порт, подсеть и параметры маскировки. Если у провайдера VPS есть облачный firewall, разрешите показанный UDP-порт."],["DNS, the certificate and the rules in the CDN control panel do not change automatically; the doctor provides exact recommendations.","DNS, сертификат и правила в кабинете CDN не меняются автоматически — для них доктор покажет точную рекомендацию."],["Beget: compatible GET packet upload, larger upload blocks, Session ID in the query and xMux. Disable caching and ignoring query parameters.","Beget: совместимый GET packet-up, увеличенные блоки upload, Session ID в query и xMux. Отключите кэширование и игнорирование параметров запроса."],["Site design, backup and panel access","Оформление сайта, резервная копия и доступ к панели"],["Try signing in again.","Попробуйте войти ещё раз."],["Go back","Вернуться"],["Connection system","Система подключения"],["The secure connection is active.","Безопасное соединение активно."],["Server","Сервер"],["Number of subscriptions","Количество подписок"],["Backups","Резервные копии"],["HWID and the key can be copied","HWID и ключ можно скопировать"]];
// Exact original label is retained separately from its optional English translation.
const ruToEn=Object.assign(Object.create(null),dictionary);
for(const [en,ru] of extraPairs){
 if(/[А-ЯЁа-яё]/u.test(ru)&&en!==ru)ruToEn[ru]=en;
}
const textStates=new WeakMap(),attrStates=new WeakMap();
const skip='script,style,noscript,textarea,code,pre,svg,[contenteditable],[data-wpo-no-translate],.wpo-utility-switches';
const attrNames=['title','placeholder','aria-label','alt'];
const observeOptions={subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:attrNames};
let language='ru';
try{language=localStorage.getItem('wpo-language')==='en'?'en':'ru'}catch(_){}
const pageTitle=document.title;
const queuedRoots=new Set();
let scheduled=false,observer=null;
const has=(key)=>Object.prototype.hasOwnProperty.call(ruToEn,key);
function translateOriginal(original){
 if(!/[А-ЯЁа-яё]/u.test(original))return original;
 const m=original.match(/^(\s*)([\s\S]*?)(\s*)$/);
 if(!m)return original;
 const key=m[2].replace(/\s+/g,' ').trim();
 // Prefer a complete known phrase before applying partial numeric/unit rules.
 if(has(key))return m[1]+ruToEn[key]+m[3];
 // Existing Latin protocol names, arrows, symbols and emojis are never translated.
 // Translate the Russian UI label after the non-Cyrillic prefix only.
 const prefixed=key.match(/^([^А-ЯЁа-яё]*)([А-ЯЁа-яё][\s\S]*)$/u);
 if(prefixed&&prefixed[1]&&has(prefixed[2]))
   return m[1]+prefixed[1]+ruToEn[prefixed[2]]+m[3];
 // Dynamic CPU and uptime values preserve their numbers.
 const cpu=key.match(/^Ядер:\s*(.+?)\s*·\s*гипервизор:\s*(.+)$/u);
 if(cpu)return m[1]+'Cores: '+cpu[1]+' · hypervisor: '+cpu[2]+m[3];
 const elapsed=key.replace(/(\d+)\s*д\./gu,'$1 d.').replace(/(\d+)\s*ч\./gu,'$1 h.').replace(/(\d+)\s*мин\./gu,'$1 min.').replace(/(\d+)\s*с\s+назад/gu,'$1 s ago').replace(/(\d+)\s*мин\s+назад/gu,'$1 min ago');
 if(elapsed!==key)return m[1]+elapsed+m[3];
 if(has(key))return m[1]+ruToEn[key]+m[3];
 const arrow=key.match(/^([↑↓])\s*(.+)$/);
 if(arrow&&has(arrow[2]))return m[1]+arrow[1]+' '+ruToEn[arrow[2]]+m[3];
 const shown=key.match(/^Показано\s+(\d+)\s+из\s+(\d+)(\s*·\s*(.+))?$/);
 if(shown){
   const extra=shown[4]?(has(shown[4])?' · '+ruToEn[shown[4]]:' · '+shown[4]):'';
   return m[1]+'Showing '+shown[1]+' of '+shown[2]+extra+m[3];
 }
 // Icons and plus signs belong to button labels but are not translatable words.
 const decorated=key.match(/^([+＋✓✔⚠!•●]\s*)(.+)$/);
 if(decorated&&has(decorated[2]))
   return m[1]+decorated[1]+ruToEn[decorated[2]]+m[3];

 // Numerical byte units are interface labels, not user data or protocol IDs.
 const units={'Б':'B','КБ':'KB','МБ':'MB','ГБ':'GB','ТБ':'TB'};
 if(/(^|[\s↑↓·|:])\d+(?:[,.]\d+)?\s*(?:ТБ|ГБ|МБ|КБ|Б)(?:\/с)?(?=$|[\s↑↓·|:])/u.test(key)){
   const replaced=key.replace(/(^|[\s↑↓·|:])(\d+(?:[,.]\d+)?\s*)(ТБ|ГБ|МБ|КБ|Б)(\/с)?(?=$|[\s↑↓·|:])/gu,
     (full,lead,num,unit,perSec)=>lead+num+units[unit]+(perSec?'/s':''));
   if(replaced!==key)return m[1]+replaced+m[3];
 }
 const numbered=key.match(/^(\d+)\s*[·.]\s*(.+)$/);
 if(numbered&&has(numbered[2]))return m[1]+numbered[1]+' · '+ruToEn[numbered[2]]+m[3];
 const suffix=key.match(/^(.+?)\s*(\(\d+\)|\d+)$/);
 if(suffix&&has(suffix[1]))return m[1]+ruToEn[suffix[1]]+' '+suffix[2]+m[3];

 // Long notices may arrive as a single text node containing several sentences.
 // Translate only individually known Russian sentences; preserve all other content verbatim.
 const sentences=key.match(/[^.!?]+[.!?]?(?:\s+|$)/gu);
 if(sentences&&sentences.length>1){
   let matched=false;
   const mapped=sentences.map(part=>{
     const m=part.match(/^(\s*)([\s\S]*?)(\s*)$/);
     if(!m)return part;
     if(has(m[2])){matched=true;return m[1]+ruToEn[m[2]]+m[3]}
     return part;
   });
   if(matched)return m[1]+mapped.join('')+m[3];
 }
 const parts=key.split(/(\s*[·•|:]\s*)/);
 if(parts.length>1){
  let changed=false;
  for(let i=0;i<parts.length;i+=2){
    const segment=parts[i].trim();
    if(has(segment)){parts[i]=parts[i].replace(segment,ruToEn[segment]);changed=true}
  }
  if(changed)return m[1]+parts.join('')+m[3];
 }
 return original;
}
function restoreOrTranslate(current,state){
 if(!state||current!==state.original&&current!==state.en)
   state={original:current,en:translateOriginal(current)};
 return {state,desired:language==='en'?state.en:state.original};
}
function validElement(el){
  return el&&el.nodeType===1&&!(el.matches(skip)||el.closest(skip));
}
function translateText(node){
  const parent=node.parentElement;
  if(!validElement(parent))return;
  // An <option> without a value attribute submits its text as its value.
  // Preserve these options so language never changes connection/protocol IDs.
  if(parent.tagName==='OPTION'&&!parent.hasAttribute('value'))return;
  const current=node.nodeValue;
  if(!current||!current.trim())return;
  const info=restoreOrTranslate(current,textStates.get(node));
  textStates.set(node,info.state);
  if(current!==info.desired)node.nodeValue=info.desired;
}
function translateAttributes(el){
  if(!validElement(el))return;
  let attrs=attrStates.get(el);
  if(!attrs){attrs=new Map();attrStates.set(el,attrs)}
  for(const name of attrNames){
    if(!el.hasAttribute(name))continue;
    const current=el.getAttribute(name);
    const info=restoreOrTranslate(current,attrs.get(name));
    attrs.set(name,info.state);
    if(current!==info.desired)el.setAttribute(name,info.desired);
  }
  if(el.tagName==='INPUT'&&!el.name&&['submit','button','reset'].includes(el.type)){
    const current=el.value;
    const info=restoreOrTranslate(current,attrs.get('input-label'));
    attrs.set('input-label',info.state);
    if(current!==info.desired)el.value=info.desired;
  }
}
function scan(root){
  if(!root)return;
  if(root.nodeType===3){translateText(root);return}
  if(root.nodeType!==1||!validElement(root))return;
  translateAttributes(root);
  const walker=document.createTreeWalker(root,NodeFilter.SHOW_ELEMENT|NodeFilter.SHOW_TEXT);
  let node;
  while((node=walker.nextNode())){
    if(node.nodeType===3){translateText(node);continue}
    if(validElement(node))translateAttributes(node);
  }
}
function updateControls(){
  // Safari page language is intentionally constant; only WPO UI text changes.
  document.querySelectorAll('button[data-wpo-lang]').forEach(button=>{
    button.setAttribute('aria-pressed',String(button.dataset.wpoLang===language));
  });
  const switchGroup=document.querySelector('.wpo-utility-switches');
  if(switchGroup)switchGroup.setAttribute('aria-label',language==='en'?'Language and theme':'Язык и тема');
  // Keep the browser tab title unchanged to avoid reclassification in Safari.
}
function observe(){
  if(observer&&document.body)observer.observe(document.body,observeOptions);
}
function fullApply(){
  if(observer)observer.disconnect();
  queuedRoots.clear();
  scheduled=false;
  scan(document.body);
  updateControls();
  document.documentElement.classList.remove('wpo-en-prepaint');
  observe();
}
function flush(){
  scheduled=false;
  if(!document.body)return;
  if(observer)observer.disconnect();
  let roots=[...queuedRoots];queuedRoots.clear();
  if(roots.length>80)roots=[document.body];
  for(const root of roots){
    if(root.isConnected)scan(root);
  }
  observe();
}
function enqueue(root){
  if(!root)return;
  if(root.nodeType===3)root=root.parentElement;
  if(!root||!root.isConnected)return;
  queuedRoots.add(root);
  if(queuedRoots.size>80){queuedRoots.clear();queuedRoots.add(document.body)}
  if(!scheduled){scheduled=true;requestAnimationFrame(flush)}
}
function start(){
  if(!document.body)return;
  // Ask browser translators to leave this already-localized application alone.
  // Safari itself may still show its own translation/Reader UI.
  // translate=no is already present in the first HTML response, before Safari parses the page.
  if(document.head&&!document.head.querySelector('meta[name="google"][content="notranslate"]')){
    const meta=document.createElement('meta');
    meta.setAttribute('name','google');
    meta.setAttribute('content','notranslate');
    document.head.appendChild(meta);
  }
  fullApply();
  observer=new MutationObserver(records=>{
    for(const record of records){
      if(record.type==='childList'){
        for(const node of record.addedNodes)enqueue(node);
      }else if(record.type==='characterData'){
        enqueue(record.target);
      }else if(record.type==='attributes'){
        enqueue(record.target);
      }
    }
  });
  observe();
}
document.addEventListener('click',event=>{
  const target=event.target;
  const button=target&&typeof target.closest==='function'?target.closest('button[data-wpo-lang]'):null;
  if(!button)return;
  const next=button.dataset.wpoLang;
  if(next!=='en'&&next!=='ru')return;
  language=next;
  try{localStorage.setItem('wpo-language',language)}catch(_){}
  fullApply();
});
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});
else start();
})();
</script>'''


def rewrite(source):
    if '# WPO_C333_MANUAL_LOGIN_V1' not in source or OLD_MARK not in source:
        raise RuntimeError('Нужны рабочая WPO c333e00 и предыдущие патчи языка/входа. Ничего не изменено.')
    if NEW_MARK in source:
        return source, 0
    if 'WPO_NAV_NATIVE_RECOVERY_V2_BEGIN' in source:
        raise RuntimeError('Обнаружена несовместимая версия WPO. Ничего не изменено.')
    lines=source.splitlines(keepends=True)
    candidates=[i for i,line in enumerate(lines) if line.startswith('WPO_C333_I18N_JS = ')]
    if len(candidates)!=1:
        raise RuntimeError('Не найдена единственная переменная перевода WPO; остановка.')
    index=candidates[0]
    old_js=ast.literal_eval(lines[index].split(' = ',1)[1].strip())
    if not isinstance(old_js,str) or 'const dictionary=' not in old_js or 'data-wpo-lang' not in old_js:
        raise RuntimeError('Не удалось проверить прежний переводчик WPO.')
    start=old_js.index('const dictionary=')+len('const dictionary=')
    dictionary,_=json.JSONDecoder().raw_decode(old_js[start:])
    if not isinstance(dictionary,dict) or len(dictionary)<600:
        raise RuntimeError('Словарь перевода неполный. Остановка.')
    replacement=LANGUAGE_JS.replace('__DICTIONARY__',json.dumps(dictionary,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c'))
    if '__DICTIONARY__' in replacement or 'new MutationObserver(' not in replacement:
        raise RuntimeError('Сборка переводчика не прошла проверку.')
    lines[index]='WPO_C333_I18N_JS = '+repr(replacement)+'\n'
    updated=''.join(lines)+'\n'+NEW_MARK+'\n'+PRELOAD_HELPER
    ast.parse(updated,filename=str(TARGET))
    compile(updated,str(TARGET),'exec')
    for critical in ('# WPO_SELECT_POPOVER_V2_BEGIN','def routing_ui(','def theme_button():'):
        if source.count(critical)!=updated.count(critical):
            raise RuntimeError('Обнаружено изменение рабочего кода WPO: '+critical)
    if source.count('wppNavigationTimer')!=updated.count('wppNavigationTimer'):
        raise RuntimeError('Проверка навигации не пройдена.')
    return updated,len(dictionary)


def healthy():
    if subprocess.run(['systemctl','is-active','--quiet',SERVICE]).returncode!=0:
        return False
    try:
        try:
            response=urlopen('http://127.0.0.1:8090/',timeout=2)
            code=response.status
            response.close()
        except HTTPError as e:
            code=e.code
        return 200 <= code < 500
    except Exception:
        return False


def main():
    mode=sys.argv[1] if len(sys.argv)==2 else ''
    if mode not in ('--check','--apply'):
        raise SystemExit('Использование: --check | --apply')
    if mode=='--apply' and os.geteuid()!=0:
        raise SystemExit('Для установки требуется sudo.')
    if not TARGET.is_file() or TARGET.is_symlink() or not (APP/'panel.py').is_file():
        raise SystemExit('Установленная панель WPO не найдена. Ничего не изменено.')
    source=TARGET.read_text(encoding='utf-8')
    updated,count=rewrite(source)
    if updated==source:
        print('✓ Переводчик v8 уже установлен; изменений нет.')
        return
    print('✓ Проверка исходника пройдена. Словарь:',count,'переводов.')
    if mode=='--check':
        print('✓ Режим проверки: сервер и файлы не изменены.')
        return
    if not healthy():
        raise SystemExit('WPO не отвечает до обновления. Ничего не изменено.')
    timestamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup_dir=Path('/var/backups/web-panel-online')/('i18n-v8-'+timestamp+'-'+str(os.getpid()))
    backup_dir.mkdir(parents=True,mode=0o700,exist_ok=False)
    shutil.copy2(TARGET,backup_dir/'wpp_ui.py')
    descriptor,tmp=tempfile.mkstemp(prefix='.wpo-i18n-v8-',suffix='.py',dir=APP)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8') as file:
            file.write(updated)
        attrs=TARGET.stat()
        os.chmod(tmp,stat.S_IMODE(attrs.st_mode))
        os.chown(tmp,attrs.st_uid,attrs.st_gid)
        os.replace(tmp,TARGET)
        subprocess.run(['systemctl','restart',SERVICE],check=True)
        for _ in range(20):
            if healthy():
                print('✓ RU восстанавливает исходный текст; EN переводит русские подписи. Safari-язык и заголовок страницы не изменяются.')
                print('✓ Проверен ответ WPO. Резервная копия:',backup_dir/'wpp_ui.py')
                return
            time.sleep(1)
        raise RuntimeError('WPO не ответила после установки.')
    except Exception:
        shutil.copy2(backup_dir/'wpp_ui.py',TARGET)
        subprocess.run(['systemctl','restart',SERVICE],check=False)
        print('✖ Ошибка, возвращена резервная копия:',backup_dir/'wpp_ui.py',file=sys.stderr)
        raise
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


if __name__=='__main__':
    main()
