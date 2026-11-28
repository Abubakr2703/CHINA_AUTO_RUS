# CHINA AUTO RUS

Windows-инструмент для исследования и русификации мультимедиа китайских автомобилей.
Первый профиль — Changan Deepal S07 2026 (CN). Версия и статус — в `README.md`.

Пользователь — Junior Backend Python Developer. Общайся по-русски, технически,
объясняй архитектурные решения. UI, сообщения и документация — на русском.

## Команды

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"

.venv\Scripts\python.exe -m china_auto_rus          :: GUI
run.bat                                             :: то же через venv
.venv\Scripts\python.exe -m china_auto_rus --check   :: окружение и APK-инструменты

.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pytest tests/test_rro.py -q
.venv\Scripts\python.exe -m pytest tests/test_rro.py::test_name -q
.venv\Scripts\python.exe -m ruff check src tests tools
.venv\Scripts\python.exe -m mypy
```

Перед коммитом: `pytest` → `ruff` → `mypy`, все три зелёные. `mypy` строгий
(`disallow_untyped_defs`), аннотации обязательны.

## Структура и границы

- `src/china_auto_rus/core/` — бизнес-логика. **Без импортов PySide6.** Всё, что
  можно протестировать без Qt, живёт здесь.
- `src/china_auto_rus/ui/` — только Qt: окно, модели, вкладки, `QThread`-воркеры.
  Долгие операции — через `ui/workers.py::FunctionWorker`, не в GUI-потоке.
- `src/china_auto_rus/profiles/` — данные автомобилей: один модуль на модель плюс
  пользовательские JSON в `%LOCALAPPDATA%\CHINA_AUTO_RUS\profiles\`. Не хардкодить
  модель в `core/` или `ui/`.
- `src/china_auto_rus/__main__.py` — единственный CLI-вход (флаги `--analyze`,
  `--resources`, `--build-apk`, `--rro`, `--check` и т.д.). `app.py` — запуск GUI.
- `tools/` — автономные скрипты (`check_arsc.py`, `prepare_experiment.py`), не часть пакета.
- `docs/` — `head_unit*.md` (факты об устройстве), `russification.md` (пути, подпись, откат).

Версия проекта — только в `src/china_auto_rus/__init__.py` (`pyproject.toml` читает её динамически).

## Конвенции

- Зависимости: рантайм — только PySide6. Новые библиотеки не добавлять без явного согласия.
  Никаких FastAPI, PostgreSQL, Docker, микросервисов, платных API и AI-моделей.
- Пользовательские данные (отчёты, логи, профили) — только в
  `%LOCALAPPDATA%\CHINA_AUTO_RUS`, никогда в каталог репозитория.
- Консоль Windows по умолчанию cp1251. В CLI это решает `_configure_console()`;
  в отдельных скриптах — `sys.stdout.reconfigure(encoding="utf-8")`. CSV-шаблоны
  перевода — `utf-8-sig` (Excel).
- Тесты UI работают на `QT_QPA_PLATFORM=offscreen` (см. `tests/conftest.py`),
  фикстура `qapp` — session-scope. Окно в тестах не открывать.
- Не делать фиктивных кнопок: элемент интерфейса либо работает, либо его нет.
- Изменения — небольшими шагами, каждое с тестом. Существующие тесты не удалять
  и не ослаблять.

## Хрупкие места

- **`resources.arsc`**: writer меняет только глобальный пул строк и индексы значений;
  чанки пакета должны остаться байт-в-байт. Критерий приёмки — round-trip
  **байт-в-байт**. Проверка на реальном APK: `tools/check_arsc.py <apk>`.
  Если «РАСХОДИТСЯ» — этот APK не собирать, сначала разобраться.
- **RRO**: строки писать в `res/values/strings.xml`, не в `values-ru`. `aapt2`
  выбрасывает строки локали без default-значения. Генератор — `core/rro.py`.
- **Пересборка APK** ломает вендорскую подпись — это ожидаемо, не «баг».
  `core/apk_write.py` копирует все записи кроме `resources.arsc` без изменений;
  порядок, сжатие и комментарий архива сохраняются.
- **Android-инструменты**: `C:\Android` (JDK 17, build-tools 34.0.0, platform-tools).
  `apksigner`, `zipalign`, `aapt2`, `adb` — в пользовательском `PATH`; в текущей
  сессии могут не подхватиться, тогда полный путь или новый терминал.
  Тестовый ключ `C:\Android\keys\test.jks` (alias `test`) — только для опытов.

## Безопасность

- Только чтение и анализ файлов. Не подключаться к электронным блокам автомобиля,
  не писать прошивки, не выполнять неизвестные команды установки, не обходить
  защиту производителя. Оригиналы остаются неизменными.
- Не выдумывать характеристики ГУ и не считать прошивки других поколений совместимыми.
- В логах ГУ есть VIN, TUID, ICCID, сертификат и приватный ключ: не публиковать,
  не коммитить, не вставлять в ответы. APK и бинарные образы — в `.gitignore`.
