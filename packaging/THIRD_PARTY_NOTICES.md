# Сторонние компоненты и их лицензии

ЖелезоЧек использует следующие сторонние программы и библиотеки. Тексты лицензий
сторонних программ лежат рядом с ними в папке `vendor\`.

## Программы, которые запускаются как отдельные процессы

### memtest_vulkan — тест видеопамяти
- Источник: https://github.com/GpuZelenograd/memtest_vulkan (версия 0.5.0, официальный релиз)
- Лицензия: **zlib**. Текст: `vendor\memtest_vulkan\LICENSE.txt`.

### smartmontools (smartctl) — чтение S.M.A.R.T. накопителей
- Источник: https://www.smartmontools.org/ , https://github.com/smartmontools/smartmontools (версия 7.5)
- Лицензия: **GNU GPL v2.0**. Текст: `vendor\smartmontools\COPYING.txt`.
- smartctl.exe распространяется без изменений и запускается как **отдельная программа** (не
  встраивается в код ЖелезоЧек и не связывается с ним), поэтому условия GPL относятся только к нему.
  Исходный код этой версии: https://github.com/smartmontools/smartmontools/releases/tag/RELEASE_7_5
  (см. также `vendor\smartmontools\SOURCE.txt`).
- **Письменное предложение (GPL v2, раздел 3b).** В течение трёх лет с момента получения вами
  этой копии программы правообладатель ЖелезоЧек по запросу на bagroderose@gmail.com бесплатно
  (без учёта стоимости носителя и пересылки, если она понадобится) предоставит полный
  машиночитаемый исходный код smartmontools 7.5, соответствующий распространяемому smartctl.exe.

### nvidia-smi
- Входит в драйвер NVIDIA, с программой НЕ распространяется — используется, только если уже установлен.

## Данные

### PCI ID Repository (pci.ids)
- Источник: https://pci-ids.ucw.cz/
- Используется выборка (`hwcheck/data/pci_ids.txt`) для определения реального чипа видеокарты.
- Лицензия: на выбор GNU GPL v2.0+ или 3-clause BSD; программа использует файл на условиях **BSD-3-Clause**.

> Copyright (c) the PCI ID Repository contributors. Redistribution and use in source and binary
> forms, with or without modification, are permitted provided that the conditions of the
> 3-clause BSD license are met.

## Библиотеки Python, входящие в сборку

Python (среда выполнения) — PSF License, https://www.python.org/ .

Список ниже собирается **автоматически** из установленных пакетов (`scripts/third_party.py`,
SPEC 1.4, 30.3): зависимости программы из `pyproject.toml` и всё, что они тянут за собой.
Скрипт проверяет, что среди них нет библиотек под GPL/AGPL без исключения (они работают внутри
процесса программы) и с неизвестной лицензией.

<!-- python-packages:start -->
| Пакет | Версия | Лицензия | Источник |
|---|---|---|---|
| beautifulsoup4 | 4.15.0 | MIT License | https://www.crummy.com/software/BeautifulSoup/bs4/ |
| cffi | 2.1.1 | MIT-0 |  |
| Jinja2 | 3.1.6 | BSD License | https://github.com/pallets/jinja/ |
| MarkupSafe | 3.0.4 | BSD-3-Clause | https://github.com/pallets/markupsafe/ |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org |
| psutil | 7.2.2 | BSD-3-Clause | https://github.com/giampaolo/psutil |
| pycparser | 3.12 | BSD-3-Clause | https://github.com/eliben/pycparser |
| PySide6 | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| PySide6_Addons | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| PySide6_Essentials | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| PySide6_Pdf | 6.12.0.140 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| PySide6_WebEngine | 6.12.0.140 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| PyYAML | 6.0.3 | MIT | https://pyyaml.org/ |
| rendercanvas | 2.7.2 | BSD 2-Clause License | https://github.com/pygfx/rendercanvas |
| shiboken6 | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| soupsieve | 3.0.4 | MIT | https://github.com/facelessuser/soupsieve |
| typing_extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| wgpu | 0.32.0 | BSD 2-Clause License | https://github.com/pygfx/wgpu-py |
<!-- python-packages:end -->

### Пояснения к таблице (составлено вручную, раньше было в этом разделе)

| Компонент | Назначение | Лицензия | Источник |
|---|---|---|---|
| Python | Среда выполнения | PSF License | https://www.python.org/ |
| PySide6 / Qt 6 (QtCore, QtGui, QtWidgets, QtSvg) | Интерфейс, графики, PDF-отчёт | LGPL-3.0 | https://www.qt.io/ , https://code.qt.io/ |
| shiboken6 | Связка Python и Qt | LGPL-3.0 | https://www.qt.io/ |
| wgpu-py | Нагрузка видеокарты (WebGPU) | BSD-2-Clause | https://github.com/pygfx/wgpu-py |
| wgpu-native | Реализация WebGPU | MIT / Apache-2.0 | https://github.com/gfx-rs/wgpu-native |
| numpy | Вычисления для тестов CPU и ОЗУ | BSD-3-Clause | https://numpy.org/ |
| psutil | Сведения о процессоре, памяти, процессах | BSD-3-Clause | https://github.com/giampaolo/psutil |
| Jinja2, MarkupSafe | HTML-отчёт | BSD-3-Clause | https://palletsprojects.com/ |
| PyYAML | Чтение правил и справочников | MIT | https://pyyaml.org/ |
| beautifulsoup4, soupsieve | Разбор страниц объявлений | MIT | https://www.crummy.com/software/BeautifulSoup/ |
| cffi, pycparser | Зависимости wgpu | MIT, BSD-3-Clause | https://cffi.readthedocs.io/ |

### Об LGPL (Qt / PySide6)
Qt и PySide6 подключаются как отдельные динамические библиотеки (файлы `.dll` и `.pyd` в папке
`_internal\PySide6`, `shiboken6` — в `_internal\shiboken6`) и не изменялись. ЖелезоЧек использует
их на условиях **LGPL-3.0** (из вариантов LGPL-3.0 / GPL-2.0 / GPL-3.0):
- библиотеки не встроены в `ЖелезоЧек.exe` статически: это отдельные файлы, которые программа
  загружает при запуске;
- вы вправе **заменить** их совместимыми (той же версии Qt 6 и PySide6) собранными вами или
  полученными с qt.io / PyPI — положите свои файлы на место прежних в `_internal\PySide6`;
- лицензионное соглашение ЖелезоЧек не запрещает такую замену и отладку замены; запрет обратной
  разработки к библиотекам Qt/PySide6 не относится;
- тексты лицензий Qt лежат рядом с библиотеками в сборке (папка `_internal\PySide6`), полный текст
  LGPL-3.0 — по ссылке ниже.
Исходный код Qt: https://code.qt.io/ , PySide6: https://code.qt.io/cgit/pyside/pyside-setup.git/ .
Полный текст LGPL-3.0: https://www.gnu.org/licenses/lgpl-3.0.html .
