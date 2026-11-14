# -*- coding: utf-8 -*-
"""
RotorWeb — traduction français → anglais.

Le texte de référence est en français. La table static/i18n-en.json est partagée
avec la page web (même algorithme en JavaScript) :
  - "exact"    : phrase française → phrase anglaise
  - "patterns" : [expression régulière, remplacement] ; les groupes $1, $2… sont
                 eux-mêmes traduits (ex. un nom de région dans une phrase).
"""
import json
import re
from pathlib import Path

_TABLE = None
_PATH = Path(__file__).resolve().parent / "static" / "i18n-en.json"


def _load():
    global _TABLE
    if _TABLE is None:
        try:
            d = json.loads(_PATH.read_text(encoding="utf-8"))
        except Exception:
            d = {}
        exact = d.get("exact") or {}
        pats = []
        for rx, rep in d.get("patterns") or []:
            try:
                pats.append((re.compile("^" + rx + "$", re.S), rep))
            except re.error:
                continue
        _TABLE = (exact, pats)
    return _TABLE


def tr(text, lang="fr", depth=0):
    if lang != "en" or not text or not isinstance(text, str):
        return text
    exact, pats = _load()
    s = text.strip()
    if not s:
        return text
    lead, trail = text[:len(text) - len(text.lstrip())], text[len(text.rstrip()):]
    if s in exact:
        return lead + exact[s] + trail
    if depth > 4:
        return text
    for rx, rep in pats:
        m = rx.match(s)
        if m:
            groups = [tr(g or "", lang, depth + 1) for g in m.groups()]
            out = re.sub(r"\$(\d)", lambda k: groups[int(k.group(1)) - 1] if int(k.group(1)) <= len(groups) else "", rep)
            return lead + out + trail
    return text
