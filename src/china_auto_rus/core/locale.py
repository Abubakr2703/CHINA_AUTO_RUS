"""Коды языков: нормализация и проверка известности.

Нужен общий модуль, потому что язык определяется в двух местах: по пути
файла ресурсов (``resources``) и по конфигурации внутри ``resources.arsc``.
"""

from __future__ import annotations

DEFAULT_LANGUAGE = "default"

# Устаревшие коды Android: in → id, iw → he, ji → yi.
LEGACY_LANGUAGE_CODES = {"in": "id", "iw": "he", "ji": "yi"}

# Без списка известных кодов любое короткое слово выглядело бы языком:
# ui.json → "ui", my_car.json → "car".
LANGUAGE_CODES = (
    "aa ab ae af ak am an ar as av ay az ba be bg bh bi bm bn bo br bs ca ce ch co "
    "cr cs cu cv cy da de dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga gd gl "
    "gn gu gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io is it iu ja jv ka kg "
    "ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk "
    "ml mn mr ms mt my na nb nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps "
    "pt qu rm rn ro ru rw sa sc sd se sg si sk sl sm sn so sq sr ss st su sv sw ta "
    "te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi vo wa wo xh yi yo za "
    "zh zu cmn yue zho fil"
)
KNOWN_LANGUAGES = frozenset(LANGUAGE_CODES.split())


def normalize_language(code: str) -> str:
    """Приводит устаревшие коды Android к современным."""
    if not code:
        return DEFAULT_LANGUAGE
    parts = code.split("-")
    head = LEGACY_LANGUAGE_CODES.get(parts[0].lower(), parts[0])
    return "-".join([head, *parts[1:]]) if len(parts) > 1 else head


def is_known_language(code: str) -> bool:
    """``in`` и ``iw`` — устаревшие, но всё равно известные коды."""
    return normalize_language(code).split("-")[0] in KNOWN_LANGUAGES
