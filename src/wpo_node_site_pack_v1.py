"""Self-contained original node landing pages for WPO.

All assets are inline HTML/CSS. No external fonts, trackers, scripts, remote
images, fake business addresses, dependencies, or Github downloads at install
time. Templates are safe to publish over the existing site-template API.
"""
from __future__ import annotations
from html import escape

_DEFINITIONS = (
    {
      "id":"wpo-studio",
      "name":"Дизайн-студия",
      "description":"Светлая типографическая страница дизайн-студии.",
      "brand":"FORMA / STUDIO","eyebrow":"Дизайн и стратегия",
      "headline":"Хорошие идеи заслуживают<br><em>точной формы.</em>",
      "lead":"Цифровые продукты, айдентика и визуальные системы — с вниманием к деталям и удобству людей.",
      "cta":"Наш подход","section":"Что мы делаем",
      "services":(("01","Брендинг","Характер бренда в каждом элементе."),
                  ("02","Цифровой дизайн","Чистые интерфейсы и понятный опыт."),
                  ("03","Арт-дирекшн","Последовательность от идеи до запуска.")),
      "accent":"#7759c8","bg":"#f6f3ed","surface":"#ffffff",
      "text":"#1b1a21","muted":"#6a6975","dark":False,
    },
    {
      "id":"wpo-logistics",
      "name":"Логистическая компания",
      "description":"Тёмно-синий корпоративный сайт логистики.",
      "brand":"NORTH ROUTE","eyebrow":"Транспорт и логистика",
      "headline":"Когда важен<br><em>каждый маршрут.</em>",
      "lead":"Планирование перевозок, складские решения и прозрачные процессы для команд, которые ценят своё время.",
      "cta":"Направления","section":"Наши направления",
      "services":(("01","Перевозки","Организованный путь от точки отправки до назначения."),
                  ("02","Складская логистика","Учёт, планирование и надёжная обработка."),
                  ("03","Сервис для бизнеса","Операции с ясной структурой и понятными этапами.")),
      "accent":"#f4ba45","bg":"#101c2d","surface":"#17283d",
      "text":"#f8f9fb","muted":"#adbacb","dark":True,
    },
    {
      "id":"wpo-coworking",
      "name":"Коворкинг",
      "description":"Тёплая минималистичная страница пространства для работы.",
      "brand":"SLOW WORK / SPACE","eyebrow":"Пространство для идей",
      "headline":"Место для работы.<br><em>Время для главного.</em>",
      "lead":"Спокойное рабочее пространство, переговорные и комфортные общие зоны — для новых проектов и повседневных задач.",
      "cta":"Пространство","section":"В пространстве",
      "services":(("01","Рабочие места","Внимание к свету, тишине и эргономике."),
                  ("02","Переговорные","Комфортное пространство для совместных идей."),
                  ("03","Общие зоны","Место для общения и короткой паузы.")),
      "accent":"#356b54","bg":"#eaf0e8","surface":"#fffefa",
      "text":"#20352c","muted":"#62796d","dark":False,
    },
    {
      "id":"wpo-digital-lab",
      "name":"IT-лаборатория",
      "description":"Современная технологическая страница с карточками услуг.",
      "brand":"FREQUENCY / LAB","eyebrow":"Digital solutions",
      "headline":"Идеи переходят<br><em>в работающие решения.</em>",
      "lead":"Разрабатываем цифровые сервисы, автоматизируем процессы и строим продукты, с которыми удобно работать каждый день.",
      "cta":"Компетенции","section":"Направления работы",
      "services":(("01","Разработка","От прототипа до надёжного продукта."),
                  ("02","Автоматизация","Меньше рутины — больше времени на задачи."),
                  ("03","Инфраструктура","Чистая архитектура и системный подход.")),
      "accent":"#6ce0bd","bg":"#101416","surface":"#1a2426",
      "text":"#f0f9f6","muted":"#a8beb8","dark":True,
    },
)


def _render(data):
    def e(key):
        return escape(data[key],quote=True)
    cards = "".join(
      '<article class="service"><span>'+escape(number)+'</span><h3>'+
      escape(title)+'</h3><p>'+escape(description)+'</p></article>'
      for number,title,description in data["services"]
    )
    # Only <br> and <em> are intentional in curated headline source.
    header=data["headline"]
    return '''<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="'''+("dark" if data["dark"] else "light")+'''">
<title>'''+e("brand")+''' — официальный сайт</title>
<style>
:root{--bg:'''+e("bg")+''';--surface:'''+e("surface")+''';--ink:'''+e("text")+''';--muted:'''+e("muted")+''';--accent:'''+e("accent")+'''}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main,.nav,.footer{width:min(1100px,calc(100% - 42px));margin:auto}
.nav{display:flex;align-items:center;justify-content:space-between;padding:27px 0}
.logo{font-weight:850;letter-spacing:.13em;font-size:13px}.nav a{color:var(--ink);text-decoration:none;font-size:12px;opacity:.82}
.hero{position:relative;min-height:440px;display:grid;align-content:center;justify-items:start;padding:55px 0 72px;overflow:hidden}
.hero:before{content:"";position:absolute;width:230px;height:230px;right:2%;top:14%;border:1px solid var(--accent);border-radius:44px;transform:rotate(24deg);opacity:.35}
.hero:after{content:"";position:absolute;width:145px;height:145px;right:10%;top:32%;border:1px solid var(--accent);border-radius:50%;opacity:.24}
.eyebrow{color:var(--accent);font-size:11px;font-weight:750;letter-spacing:.17em;text-transform:uppercase}
h1{z-index:1;position:relative;max-width:860px;margin:17px 0 21px;font-weight:740;font-size:clamp(44px,7.5vw,79px);line-height:1.05;letter-spacing:-.055em}
h1 em{font-family:Georgia,serif;font-weight:400;color:var(--accent)}
.lead{max-width:605px;margin:0 0 30px;color:var(--muted);font-size:17px;line-height:1.75}
.cta{display:inline-block;background:var(--accent);color:var(--bg);padding:12px 19px;border-radius:9px;text-decoration:none;font-size:13px;font-weight:750}
.section{border-top:1px solid color-mix(in srgb,var(--muted) 22%,transparent);padding:44px 0 78px}
.section h2{font-size:28px;letter-spacing:-.035em;margin:0 0 24px}
.services{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.service{padding:23px 21px 26px;border:1px solid color-mix(in srgb,var(--muted) 22%,transparent);border-radius:16px;background:var(--surface)}
.service span{font:700 11px ui-monospace,monospace;color:var(--accent)}
.service h3{margin:37px 0 8px;font-size:19px;letter-spacing:-.03em}
.service p{margin:0;color:var(--muted);font-size:13px;line-height:1.65}
.footer{padding:22px 0 34px;border-top:1px solid color-mix(in srgb,var(--muted) 20%,transparent);font-size:11px;color:var(--muted)}
@media(max-width:700px){.hero{min-height:390px;padding:55px 0}.hero:before,.hero:after{opacity:.12}.lead{font-size:15px}.services{grid-template-columns:1fr}.service h3{margin-top:17px}.section{padding-bottom:45px}}
</style></head><body>
<nav class="nav"><span class="logo">'''+e("brand")+'''</span><a href="#services">Направления</a></nav>
<main><section class="hero"><span class="eyebrow">'''+e("eyebrow")+'''</span>
<h1>'''+header+'''</h1><p class="lead">'''+e("lead")+'''</p>
<a class="cta" href="#services">'''+e("cta")+'''</a></section>
<section class="section" id="services"><h2>'''+e("section")+'''</h2>
<div class="services">'''+cards+'''</div></section></main>
<footer class="footer">'''+e("brand")+''' · Информационная страница</footer>
</body></html>'''


def presets():
    return [{"id":d["id"],"name":d["name"],"description":d["description"],
             "html":_render(d)} for d in _DEFINITIONS]


def install(namespace):
    """Add original templates to the existing WPO library, once."""
    if namespace.get("_wpo_node_site_pack_v1_installed"):
        return
    original=namespace.get("presets")
    if not callable(original):
        raise RuntimeError("WPO preset library missing")
    namespace["_wpo_node_site_pack_v1_installed"]=True

    def all_presets():
        base=original()
        ids={p.get("id") for p in base if isinstance(p,dict)}
        return base+[p for p in presets() if p["id"] not in ids]

    namespace["presets"]=all_presets
