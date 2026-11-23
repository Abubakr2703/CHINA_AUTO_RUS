"""Changan Deepal S07 2026, китайская версия, рестайлинг.

Первый профиль проекта. Характеристики мультимедиа и аппаратной платформы
здесь намеренно не заполнены: подтверждённые данные лежат в
``docs/head_unit.md``, а профиль не должен угадывать.
"""

from china_auto_rus.profiles.car import CarProfile

PROFILE = CarProfile(
    id="deepal-s07-2026-cn-restyling",
    brand="Changan",
    model="Deepal S07",
    year=2026,
    market="CN",
    trim="рестайлинг",
    notes="Версия мультимедиа и аппаратная платформа не подтверждены.",
)
