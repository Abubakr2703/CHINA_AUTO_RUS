# Инструменты сбора данных с ГУ

## prepare_experiment.py

Готовит APK для опыта с подписью: снимает старую подпись v1, выравнивает
`zipalign`, подписывает `apksigner` и проверяет сертификат. Нужны
build-tools в `PATH` (см. `docs/russification.md`).

```bat
.venv\Scripts\python.exe tools\prepare_experiment.py FDroid.apk ^
  --keystore C:\Android\keys\test.jks --alias test ^
  --storepass testpass --out FDroid-otherkey.apk
```

Ключ создаётся один раз:

```bat
keytool -genkeypair -v -keystore C:\Android\keys\test.jks -alias test ^
  -keyalg RSA -keysize 2048 -validity 10000 ^
  -storepass testpass -keypass testpass -dname "CN=Test"
```

Скрипт ничего не перезаписывает без `--force`.

## check_arsc.py

Проверяет запись `resources.arsc` на реальном APK: разбирает таблицу,
пересобирает её из строк и сравнивает результат. Ничего не сохраняет.

```bat
.venv\Scripts\python.exe tools\check_arsc.py "C:\dump\app.apk"
```

Ожидаемый вывод: `пересборка: байт-в-байт`, `повторный разбор: совпадает`,
`тестовая замена: 3 из 3`. Любое расхождение — сигнал не собирать APK.

## collect_adb.bat

Снимает **только чтение**: список устройств, свойства системы, список пакетов
и листинги каталогов. Ничего не устанавливает, не меняет и не удаляет.

### Что нужно

1. Android platform-tools (adb) — отдельная утилита, не зависимость проекта:
   https://developer.android.com/tools/releases/platform-tools
2. Распаковать архив и добавить его папку в `PATH`.
3. Проверить: `adb version`.

### Как запускать

```bat
tools\collect_adb.bat
```

Результат: `dump\<дата-время>\`

| Файл | Что внутри |
|---|---|
| `devices.txt` | список подключённых устройств |
| `getprop.txt` | модель, версия Android, сборка, производитель |
| `packages.txt` | установленные пакеты (имена APK) |
| `listing_root.txt` | корень файловой системы |
| `listing_system.txt` | `/system` |
| `listing_system_app.txt` | `/system/app` — системные приложения |
| `listing_system_etc.txt` | `/system/etc` — конфиги |
| `listing_vendor.txt` | `/vendor` — драйверы и вендорские файлы |
| `listing_data_app.txt` | `/data/app` — пользовательские приложения |

Каталог `dump/` в `.gitignore`: образы и дампы не попадают в репозиторий.

### Если устройство не найдено

- Проверить кабель: нужен **data**-кабель, не «только зарядка».
- Проверить, что в ГУ включена отладка по USB.
- На экране ГУ должно появиться подтверждение «Разрешить отладку?» — нажать «Разрешить».
- `adb devices` должен показать серийный номер и слово `device`, а не `unauthorized`.

### Что отправить в проект

`getprop.txt`, `packages.txt` и все `listing_*.txt`. Этого достаточно, чтобы
понять платформу и структуру, не вытягивая гигабайты.
