"""Panel-only HTML helpers. No public subscription request may render admin data."""
import base64
import functools
import html
import os
import re
import time
from urllib.parse import quote as url_quote


def esc(value):
    return html.escape(str(value), quote=True)


def stamp(value):
    return time.strftime('%d.%m.%Y %H:%M UTC', time.gmtime(value)) if value else '—'


def subscription_ui(subs, path, domain, csrf, traffic, human_bytes):
    path, token = esc(path), esc(csrf)

    def hidden(sub, op):
        return (f'<input type="hidden" name="csrf" value="{token}">'
                f'<input type="hidden" name="id" value="{esc(sub.get("id", ""))}">'
                f'<input type="hidden" name="operation" value="{op}">')

    def checks(sub):
        return ''.join(f'<label class="check"><input type="checkbox" name="{p}" value="1" '
                       f'{"checked" if p in sub.get("protocols", ["vless", "hysteria"]) else ""}> {title}</label>'
                       for p, title in [('vless', 'VLESS XHTTP'), ('hysteria', 'Hysteria2')])

    cards = []
    for sub in subs:
        sid = esc(sub['id'])
        url = 'https://' + domain + '/wpp-sub/' + sub['token']
        active = sum(not d.get('revoked') for d in sub['devices'])
        limit = sub['max_devices']
        total = sum(int(traffic.get(uid, {}).get('up', 0)) + int(traffic.get(uid, {}).get('down', 0))
                    for uid in sub.get('profile_ids', []))
        devices = []
        for d in sub['devices']:
            revoked = d.get('revoked', False)
            devices.append(f'''<div class="device"><div><b>{esc(d['name'])}</b>
<small>{'Отозвано' if revoked else 'Разрешено'} · ID {esc(d['id'])}<br>Обновление подписки: {stamp(d.get('last_seen'))}</small></div>
<form method="post" action="{path}/subscription-action">{hidden(sub, 'allow' if revoked else 'revoke')}
<input type="hidden" name="device_id" value="{esc(d['id'])}"><button class="btn {'danger' if not revoked else ''}">{'Разрешить регистрацию' if revoked else 'Отозвать устройство'}</button></form></div>''')
        cards.append(f'''<article class="card subscription-card"><div class="sub-title"><h3>{esc(sub['name'])}</h3><span class="status {'on' if sub['enabled'] else 'off'}">{'Включена' if sub['enabled'] else 'Отключена'}</span></div>
<p class="muted">{'HWID: '+str(active)+' / '+str(limit) if limit else 'Без лимита HWID · общий ключ'} · Трафик: {human_bytes(total)}</p>
<label>Единая ссылка подписки</label><input class="sub-url" value="{esc(url)}" readonly aria-label="Ссылка подписки {esc(sub['name'])}">
<div class="actions"><button type="button" class="btn primary copy-sub" data-link="{esc(url)}">Скопировать</button><button type="button" class="btn show-sub-qr" data-src="{path}/subscription-qr?id={sid}">QR подписки</button></div>
<details><summary>Настройки и устройства</summary><form method="post" action="{path}/subscription-action">{hidden(sub,'update')}
<label>Имя</label><input name="name" value="{esc(sub['name'])}" maxlength="80" required>
<label>Максимум устройств (HWID), 0 — без привязки</label><input type="number" name="max_devices" min="0" max="20" value="{limit}" required>
<div class="checks">{checks(sub)}</div><button class="btn primary">Сохранить настройки</button></form>
<p class="muted">При переходе между 0 и HWID-лимитом старые ключи отзываются. «Обновление подписки» не означает, что устройство сейчас онлайн.</p>
<div class="devices">{''.join(devices) or '<p class="muted">Устройства появятся после импорта подписки в клиент.</p>'}</div>
<div class="actions"><form method="post" action="{path}/subscription-action">{hidden(sub,'toggle')}<button class="btn">{'Отключить подписку' if sub['enabled'] else 'Включить подписку'}</button></form>
<form method="post" action="{path}/subscription-action" data-confirm="Сменить ссылку и отозвать ключи всех устройств?">{hidden(sub,'rotate')}<button class="btn danger">Сменить ссылку и сбросить устройства</button></form>
<form method="post" action="{path}/subscription-action" data-confirm="Удалить подписку и отозвать все её ключи?">{hidden(sub,'delete')}<button class="btn danger">Удалить</button></form></div></details></article>''')
    return f'''<style>
.sub-title,.device{{display:flex;align-items:center;justify-content:space-between;gap:16px}}.sub-title h3{{margin:0}}.actions,.checks{{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0}}.check{{display:flex;gap:8px;align-items:center}}.check input{{width:auto;margin:0}}.device{{padding:14px 0;border-top:1px solid #ffffff12}}.device small{{display:block;color:#aab4c9;line-height:1.6}}.device form{{flex-shrink:0}}summary{{cursor:pointer;padding:16px 0;color:#c5baff}}.subscription-card{{margin-bottom:16px}}.sub-url{{font-size:12px;min-width:0}}.sub-qr{{max-width:260px;width:100%;background:#fff;padding:12px;border-radius:12px}}@media(max-width:600px){{.device{{align-items:flex-start;flex-direction:column}}}}
</style><div class="topbar"><div><h1>Подписки</h1><p>Одна ссылка: VLESS XHTTP + Hysteria2</p></div></div>
<div class="card"><p>Лимит учитывает HWID, переданный клиентом (например, Happ), а не IP и не число соединений. Клиенты без HWID при включённом лимите не получат конфигурацию. Для каждого устройства создаются отдельные ключи.</p>
<p class="muted">HWID можно подделать, а полученный ключ — скопировать. Это контроль регистрации и отзыва, не гарантированная аппаратная привязка. WEB Proxy остаётся отдельной Telegram-ссылкой. Первая регистрация и отзыв устройства кратковременно перезапускают Xray.</p></div>
<div class="card"><h3>Новая подписка</h3><form method="post" action="{path}/subscription-action">{hidden({},'create')}
<label>Имя пользователя</label><input name="name" maxlength="80" placeholder="Например, Александр" required>
<label>Максимум устройств (HWID), 0 — без привязки</label><input type="number" name="max_devices" value="2" min="0" max="20" required>
<div class="checks">{checks({})}</div><button class="btn primary">Создать подписку</button></form></div>
{''.join(cards) or '<div class="card muted">Подписок пока нет. Старые отдельные подключения сохранены во вкладке «Пользователи».</div>'}
<dialog id="subQrDialog" style="border:0;border-radius:20px;padding:24px"><img id="subQrImg" class="sub-qr" alt="QR подписки"><p><button class="btn" id="closeSubQr">Закрыть</button></p></dialog>
<script>
document.querySelectorAll('.copy-sub').forEach(b=>b.addEventListener('click',async()=>{{try{{await navigator.clipboard.writeText(b.dataset.link);b.textContent='Скопировано ✓'}}catch(e){{b.closest('article').querySelector('.sub-url').select();document.execCommand('copy');b.textContent='Скопировано ✓'}}}}));
document.querySelectorAll('.show-sub-qr').forEach(b=>b.addEventListener('click',()=>{{document.getElementById('subQrImg').src=b.dataset.src;document.getElementById('subQrDialog').showModal()}}));
document.getElementById('closeSubQr').addEventListener('click',()=>document.getElementById('subQrDialog').close());
document.querySelectorAll('form[data-confirm]').forEach(f=>f.addEventListener('submit',e=>{{if(!confirm(f.dataset.confirm))e.preventDefault()}}));
</script>'''


def editor_ui(source, path, csrf, presets, has_draft):
    buttons = ''.join(f'<form method="post" action="{esc(path)}/draft-preset" class="preset-card">'
                      f'<input type="hidden" name="csrf" value="{esc(csrf)}">'
                      f'<input type="hidden" name="preset" value="{esc(p["id"])}">'
                      f'<b>{esc(p["name"])}</b><p class="muted">{esc(p["description"])}</p>'
                      '<button class="btn">Открыть в черновике</button></form>' for p in presets)
    return f'''<style>.editor-actions{{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}}.preview-wrap{{overflow:auto;padding:12px;background:#090d18;border-radius:16px}}#landingPreview{{display:block;width:100%;height:660px;max-width:100%;border:0;margin:0 auto;background:white}}#landingPreview.phone{{width:390px;height:720px}}#htmlSource{{width:100%;font:12px/1.6 ui-monospace,monospace}}#previewStatus{{min-height:24px;color:#bdcce9}}</style>
<div class="card"><h3>Пресеты заглушек</h3><p class="muted">Пресет открывается в черновике. Рабочий сайт изменится только после публикации. Текущий черновик будет заменён.</p><div class="preset-grid">{buttons}</div></div>
<div class="card"><h3>HTML главной страницы · {'черновик' if has_draft else 'опубликованный исходник'}</h3>
<p class="muted">Предпросмотр изолирован от панели. Внешние ресурсы, формы и сетевые запросы заблокированы; стили и скрипты должны быть внутри HTML. В живом сайте ограничения могут отличаться — после публикации проверьте страницу.</p>
<form id="editorForm" method="post" action="{esc(path)}/site-html"><input type="hidden" name="csrf" value="{esc(csrf)}">
<textarea id="htmlSource" name="html" rows="20" spellcheck="false" required>{esc(source)}</textarea>
<div class="editor-actions"><button class="btn" formaction="{esc(path)}/save-draft">Сохранить черновик</button><button class="btn" type="button" id="previewHtml">Предпросмотр</button><button class="btn primary" id="publishHtml">Опубликовать на сайте</button></div></form>
<form method="post" action="{esc(path)}/discard-draft"><input type="hidden" name="csrf" value="{esc(csrf)}"><button class="btn" onclick="return confirm('Удалить черновик и вернуться к опубликованному исходнику?')">Удалить черновик</button></form>
<div class="editor-actions"><button type="button" class="btn" id="previewDesktop">Компьютер</button><button type="button" class="btn" id="previewPhone">Телефон</button></div>
<p id="previewStatus">Нажмите «Предпросмотр», чтобы увидеть текущий код без публикации.</p><div class="preview-wrap"><iframe id="landingPreview" title="Изолированный предпросмотр заглушки" sandbox="allow-scripts" referrerpolicy="no-referrer"></iframe></div></div>
<script>
const ef=document.getElementById('editorForm'),pf=document.getElementById('landingPreview'),ps=document.getElementById('previewStatus');
document.getElementById('previewHtml').addEventListener('click',async()=>{{ps.textContent='Подготовка…';try{{const body=new URLSearchParams(new FormData(ef));const r=await fetch('{esc(path)}/preview-html',{{method:'POST',body}});const d=await r.json();if(!r.ok)throw new Error(d.message||'Ошибка предпросмотра');pf.srcdoc=d.document;ps.textContent='Предпросмотр обновлён. Рабочий сайт не изменён.'}}catch(e){{ps.textContent=e.message}}}});
document.getElementById('previewPhone').addEventListener('click',()=>pf.classList.add('phone'));
document.getElementById('previewDesktop').addEventListener('click',()=>pf.classList.remove('phone'));
ef.addEventListener('submit',e=>{{if(e.submitter&&e.submitter.id==='publishHtml'&&!confirm('Опубликовать текущий HTML на основном сайте?'))e.preventDefault()}});
</script>'''


# Preview iframes deliberately have opaque origins (no allow-same-origin).
# Browsers can block images fetched from the public hostname inside this
# sandbox when the public server sends cross-origin resource policies.
# Use only our already-installed, locally verified WebP photos as data: URLs.
# This also works in the public CSS; original author HTML is never rewritten.
_PRESET_PREVIEW_PHOTOS = frozenset({
    "preset-coffee.webp", "preset-cars.webp",
    "preset-car-graphite.webp", "preset-car-silver.webp",
    "preset-car-white.webp", "preset-car-blue.webp",
    "preset-car-red.webp", "preset-car-black.webp",
})


@functools.lru_cache(maxsize=24)
def _preset_photo_data(filename, mtime_ns, size):
    path = os.path.join("/srv/tproxy-site", filename)
    with open(path, "rb") as stream:
        raw = stream.read(4 * 1024 * 1024 + 1)
    if len(raw) != size or not 12 <= size <= 4 * 1024 * 1024:
        raise ValueError("Фотография пресета слишком большая или повреждена: " + filename)
    if raw[:4] != b"RIFF" or raw[8:12] != b"WEBP":
        raise ValueError("Неверный формат фотографии пресета: " + filename)
    return "data:image/webp;base64," + base64.b64encode(raw).decode("ascii")


def inline_bundled_preset_photos(source):
    # Match only exact packaged filenames, never arbitrary local paths.
    pattern = r"""(?P<quote>["'])(?P<url>/preset-[a-z0-9-]+\.webp)(?P=quote)"""
    def inline(match):
        url = match.group("url")
        filename = url[1:]
        if filename not in _PRESET_PREVIEW_PHOTOS:
            return match.group(0)
        path = os.path.join("/srv/tproxy-site", filename)
        try:
            stat = os.stat(path)
            data_url = _preset_photo_data(filename, stat.st_mtime_ns, stat.st_size)
        except OSError as exc:
            raise ValueError("Не найдена фотография " + filename + ". Проверьте установку assets пресетов.") from exc
        return match.group("quote") + data_url + match.group("quote")
    return re.sub(pattern, inline, source, flags=re.I)


# Preview works for EVERY present and future HTML preset, not a fixed list
# of images. Only existing public-site image/font assets get rewritten to an
# independent, cacheable stream. Never embed huge WebP base64 in the HTML.
_PREVIEW_EXTENSIONS = r"(?:webp|png|jpe?g|gif|avif|svg|woff2?|ttf|otf)"
_PREVIEW_QUOTED_ASSET = re.compile(
    r"""(?P<quote>["'])(?P<path>/?(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+\."""
    + _PREVIEW_EXTENSIONS + r""")(?P<tail>\?[^"']*)?(?P=quote)""", re.I
)
_PREVIEW_UNQUOTED_URL = re.compile(
    r"url\(\s*(?P<path>/?(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+\."
    + _PREVIEW_EXTENSIONS + r")\s*\)", re.I
)


def _preview_local_asset_url(path, domain, panel_path):
    filename=path.lstrip("/")
    parts=filename.split("/")
    if (not filename or len(filename)>200
        or any(not segment or segment in (".","..") or segment.startswith(".")
               for segment in parts)):
        return None
    root=os.path.realpath("/srv/tproxy-site")
    candidate=os.path.realpath(os.path.join(root,filename))
    if not candidate.startswith(root+os.sep):
        return None
    try:
        stat=os.stat(candidate)
        if not os.path.isfile(candidate) or stat.st_size<1 or stat.st_size>8*1024*1024:
            return None
    except OSError:
        return None
    encoded="/".join(url_quote(part,safe="") for part in parts)
    stamp=f"{stat.st_mtime_ns:x}-{stat.st_size:x}"
    return "https://"+domain+panel_path+"/__preview_asset/"+encoded+"?v="+stamp


def _preview_streamed_assets(source, domain, panel_path):
    # Quotes cover HTML src/srcset, CSS url('...'), and images created by JS.
    # Unquoted CSS url(...) is also supported. External HTTPS images stay as
    # authored. No predetermined preset IDs or filenames are required.
    def replace_quoted(match):
        replacement=_preview_local_asset_url(match.group("path"),domain,panel_path)
        if not replacement:
            return match.group(0)
        quote=match.group("quote")
        return quote+replacement+quote

    source=_PREVIEW_QUOTED_ASSET.sub(replace_quoted,source)

    def replace_css_url(match):
        replacement=_preview_local_asset_url(match.group("path"),domain,panel_path)
        return 'url("'+replacement+'")' if replacement else match.group(0)

    return _PREVIEW_UNQUOTED_URL.sub(replace_css_url,source)


def preview_document(source, externalize, public_domain="", panel_path=""):
    # Render immediately; image/font requests load concurrently over HTTP,
    # cached by file version. The isolated iframe never gets admin origin,
    # cookies, forms, frames or unrestricted JavaScript network access.
    host=str(public_domain or "").strip().lower()
    valid_host=(len(host.split("."))>=2 and all(
        part and len(part)<=63
        and all(ch.isascii() and (ch.isalnum() or ch=="-") for ch in part)
        and part[0]!="-" and part[-1]!="-"
        for part in host.split(".")
    ))
    valid_path=bool(re.fullmatch(r"/panel-[a-z0-9-]{3,64}",str(panel_path or "")))
    if valid_host and valid_path:
        document=_preview_streamed_assets(source,host,panel_path)
    else:
        document=source

    # Arbitrary newly created presets may use different remote photo hosts.
    # Only image and font downloads can use HTTPS; forms, fetch/connect,
    # external scripts, frames and navigation remain restricted by CSP/sandbox.
    image_sources="'self' data: blob: https:"
    font_sources="data: https:"
    csp=(
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        +"img-src "+image_sources+"; font-src "+font_sources+"; "
        +"connect-src 'none'; frame-src 'none'; "
        +"base-uri 'none'; form-action 'none'"
    )
    policy='<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="'+csp+'">'
    head=re.search(r'<head\b[^>]*>',document,flags=re.I)
    if head:
        return document[:head.end()]+policy+document[head.end():]
    doctype=re.match(r'\s*<!doctype\b[^>]*>',document,flags=re.I)
    if doctype:
        return document[:doctype.end()]+'<head>'+policy+'</head>'+document[doctype.end():]
    return policy+document
