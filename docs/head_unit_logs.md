# Логи с ГУ Deepal S07 2026 — первая выгрузка

Дата выгрузки: 2026-11-26. Источник: штатная функция `日志管理` на ГУ,
флешка с пустой папкой `log.mega.co` в корне.

## Объём

| Параметр | Значение |
|---|---|
| Размер | ~1,2 ГБ |
| Файлов | 622 |
| Каталог | `log.mega.co/<VIN>_2026_11_26_<время>/` |

Имя каталога содержит VIN. При передаче наружу каталог переименовывается,
VIN в документах и отчётах не публикуется.

## Структура

| Каталог | Что внутри |
|---|---|
| `android/` | `logcat.log`, 100 архивов logcat, `PRODUCT_INFO.txt` |
| `qlog/dltlogs/` | `slog2_*.txt.bz2` — системный лог QNX/Android-слоя |
| `qlog/kernel/`, `qlog/coredump/` | ядро и падения |
| `qlog/tcpdump/` | сетевые дампы |
| `qlog/adp_8295/` | логи Qualcomm 8295 |
| `qlog/sjgd/` | консольные логи |
| `anr/`, `tombstones/` | зависания и падения приложений |
| `bluetooth/`, `btsnoop/`, `wlan_logs/` | Bluetooth и Wi-Fi |

## Подтверждено логами

| Параметр | Значение | Источник |
|---|---|---|
| Версия Android | **13** | `logcat.log` |
| `MemTotal` | 17 222 020 kB (≈16,4 ГБ) | `PRODUCT_INFO.txt` |
| Swap | 4 194 300 kB (4 ГБ) | `PRODUCT_INFO.txt` |
| Пакетов в логах | ~60 | `Start proc` в logcat |

Расхождение с экраном «24 ГБ ОЗУ» описано в [head_unit.md](head_unit.md).

## Пакеты

Системные и вендорские:

```
com.android.car, com.android.car.settings, com.android.launcher3,
com.android.systemui, com.android.settings, com.android.packageinstaller,
com.android.webview, com.android.bluetooth, com.android.phone,
com.android.providers.media.module, com.android.externalstorage,
com.android.permissioncontroller, com.android.keychain,
com.android.networkstack.process, com.android.dynsystem,
com.android.managedprovisioning, com.android.shell, com.android.traceur
```

Оболочка Changan/Deepal:

```
com.mega.car, com.mega.carsettings, com.mega.media, com.mega.btphone,
com.mega.petalmap,
com.mega.carplay, com.mega.carplayapp, com.mega.mobileconnect,
com.mega.linkmanager, com.mega.wired, com.mega.sceneblock,
com.mega.scenemode, com.mega.dvr, com.mega.satellite, com.mega.tbox,
com.mega.account.services, com.mega.assistant.service, com.mega.assist.vui,
com.mega.tts, com.mega.controller, com.mega.commonservice,
com.mega.datatrack, com.mega.user, com.mega.owl, com.mega.hive,
com.mega.nexus.server, com.mega.qnxaudiomanager, com.mega.documentsui,
com.mega.usbmountreceiver, com.mega.update, com.mega.tencentpush,
com.mega.dvtest, com.mega.carmodel, com.mega.app.engineeringmode,
com.deepal.ivi.hmi.showcarmode
```

Сторонние и партнёрские:

```
com.changan.appmarket, com.kugou.android.auto, com.bilibili.bilithings,
com.sogou.inputmethod.iot, com.loostone.tuning, com.abupdate.ota,
com.huawei.maps.car.app, com.huawei.hibaic.adshmiic,
com.huawei.hibaic.adsotad, com.huawei.hisight, com.huawei.nearby,
com.huawei.dmsdpdevice, com.phone.cast, com.android.bluetooth1,
android.ext.services, android.process.acore, android.process.media
```

## APK, найденные в логах

```
/system/priv-app/MegaAssistant/MegaAssistant.apk
/system/product/app/ShowCarMode/ShowCarMode.apk
/system/product/app/webview/webview.apk
/vendor/app/BigsurBilibili/BigsurBilibili.apk
/vendor/app/SogouInput/SogouInput.apk
```

Это не полный список: логи содержат только упоминания, а не инвентаризацию
`/system`. Полный список появится после чтения каталогов на самом ГУ.

## Чувствительные данные

`android/PRODUCT_INFO.txt` содержит:

- VIN и TUID;
- ICCID;
- сертификат и **приватный RSA-ключ**.

Файл нельзя публиковать, отправлять и коммитить. Каталог `dump/` в
`.gitignore`, но при копировании на другую машину это надо проверять руками.

## Чего в логах нет

- самих APK;
- листинга `/system/app` и `/system/priv-app`;
- ответа на вопрос, читается ли `/system` без root.

## Следующий шаг

Забрать 1–2 APK с ГУ. Варианты по порядку:

1. `USB模式切换` в инженерном меню — если даёт доступ к файлам с ПК.
2. Файловый менеджер на ГУ, если найдётся в `应用商城`.
3. ADB — только при наличии пароля отладки, без подбора.
