"""Conservative in-place REALITY modal patch for existing WPO UI variants.

Does not replace whole wpo_reality_ui.py. Rejects incomplete/unknown source,
preserving prior localization, CSS changes and unrelated working UI.
"""
from __future__ import annotations
import ast

MARK="# WPO_REALITY_DOMAIN_MODAL_V1"

DEFAULT_HELP="Шаблон сайта на вашем домене настраивается отдельно. "
PRESENT=r"""const defaultHelp=f.querySelector('[data-reality-help]').textContent;
function presentMode(p){
 const direct=managedNodeReadonly;
 f.dataset.realityMode=direct?'direct443':'legacy';
 f.querySelector('[data-reality-legacy-target]').hidden=direct;
 f.querySelector('[data-reality-sni-label]').firstChild.nodeValue=direct?'Домен ноды · SNI':'SNI';
 f.querySelector('[data-reality-help]').textContent=direct
  ?'REALITY: Xray напрямую на TCP 443. SNI совпадает с доменом ноды и управляется автоматически. Шаблон сайта настраивается отдельно в карточке ноды.'
  :defaultHelp;
 f.elements.fingerprint.disabled=direct;
 f.elements.sni.readOnly=direct||f.elements.preset.value!=='custom';
 if(direct)f.elements.sni.value=p.sni||'';
}
"""
CSS=r"""
#wpoRealityDialog [data-reality-legacy-target][hidden]{display:none!important}
#wpoRealityDialog [data-reality-mode="direct443"] [data-reality-sni-label] input{
 cursor:default;background:var(--raised,var(--input));color:var(--muted)
}
"""


def patch(source):
    if MARK in source or "function presentMode(" in source:
        raise ValueError("The node-domain REALITY modal is already patched")
    replacements=[
        ('<label>Сайт для REALITY<div class="wpo-reality-picker">',
         '<label data-reality-legacy-target>Сайт для REALITY<div class="wpo-reality-picker">'),
        ('<label>SNI<input name="sni" value="',
         '<label data-reality-sni-label>SNI<input name="sni" value="'),
        ('<small>'+DEFAULT_HELP,
         '<small data-reality-help>'+DEFAULT_HELP),
        ("f.elements.fingerprint.readOnly=false;",
         "f.elements.fingerprint.disabled=false;"),
        ("  displayPreset();if(f.elements.preset.value==='custom')f.elements.sni.value=p.sni;",
         "  displayPreset();if(f.elements.preset.value==='custom')f.elements.sni.value=p.sni;\n  presentMode(p);"),
        ("f.elements.fingerprint.readOnly=true;",
         "f.elements.fingerprint.disabled=true;"),
        (" }catch(err){if(!cancelRequested)out.textContent=err.message}",
         " }catch(err){if(!cancelRequested){managedNodeReadonly=true;f.querySelector('[data-reality-legacy-target]').hidden=true;out.textContent='Не удалось определить режим ноды: '+err.message+'. Изменения REALITY заблокированы.'}}"),
    ]
    for old,new in replacements:
        if source.count(old)!=1:
            raise ValueError("Неподдерживаемая версия REALITY UI; отсутствует уникальный фрагмент: "+old[:56])
        source=source.replace(old,new,1)

    import re
    display_pattern=r"(?m)^(function displayPreset\(\)\{.*\})$"
    displays=re.findall(display_pattern,source)
    if len(displays)!=1:
        raise ValueError("Unexpected REALITY preset display implementation")
    source=source.replace(displays[0],displays[0]+"\n"+PRESENT,1)

    # Disable the drop-down also while loading and in managed mode.
    old=" f.querySelector('[data-reality-toggle]').disabled=value||managedNodeReadonly;"
    if source.count(old)!=1:
        raise ValueError("REALITY picker state differs; stopping")
    # Keep existing row's lock behavior, only hide it for direct 443.

    # Existing managed readonly body may use a slight text translation
    # variation. Replace the complete block only if verified anchors agree.
    block_head="  if(managedNodeReadonly){"
    block_start=source.find(block_head)
    if block_start<0 or source.count(block_head)!=1:
        raise ValueError("Managed readonly branch missing")
    next_end=source.find("\n  }\n }catch(err)",block_start)
    if next_end<0:
        raise ValueError("Managed readonly branch unexpected")
    current_block=source[block_start:next_end+4]
    if ("f.elements.sni.readOnly=true;" not in current_block or
        "out.textContent=" not in current_block):
        raise ValueError("Managed mode branch not compatible")
    replacement=(
        "  if(managedNodeReadonly){\n"
        "    out.textContent='Прямой REALITY 443 активен. Настройки SNI защищены; клиенты и подписки управляются через WPO.';\n"
        "  }"
    )
    source=source.replace(current_block,replacement,1)

    # Add CSS to the existing style block; no layout or dimensions changed.
    old='#wpoRealityDialog .connection-pane>small{font-size:11px;line-height:1.6;color:var(--muted)}'
    if source.count(old)!=1:
        raise ValueError("REALITY modal style section changed; stopping")
    source=source.replace(old,old+"\n"+CSS,1)
    if ("managedNodeReadonly" not in source or
        "const actions=Array.from(f.querySelectorAll('.actions button'))" not in source or
        "if(running||(typeof managedNodeReadonly!=='undefined'&&managedNodeReadonly))return;" not in source):
        raise ValueError("Установленный REALITY UI не поддерживает защищённый режим; ничего не меняю")
    source=source.rstrip()+"\n"+MARK+"\n"
    ast.parse(source)
    return source
