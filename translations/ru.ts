<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="ru_RU">
<context>
    <name>MainWindow</name>
    <message>
        <location filename="../ui.py" line="28"/>
        <source>EFD Unpacker</source>
        <translation>EFD Unpacker</translation>
    </message>
    <message>
        <location filename="../ui.py" line="53"/>
        <source>Unpack</source>
        <translation>Распаковать</translation>
    </message>
    <message>
        <location filename="../ui.py" line="83"/>
        <source>Open Folder</source>
        <translation>Открыть папку</translation>
    </message>
    <message>
        <location filename="../ui.py" line="238"/>
        <source>Unpacking in progress</source>
        <translation>Распаковка не завершена</translation>
    </message>
    <message>
        <location filename="../ui.py" line="0"/>
        <source>Unpacking is not finished. Stop it and close the window?</source>
        <translation>Распаковка ещё идёт. Остановить её и закрыть окно?</translation>
    </message>
    <message>
        <location filename="../ui.py" line="246"/>
        <location filename="../ui.py" line="250"/>
        <location filename="../ui.py" line="279"/>
        <location filename="../ui.py" line="286"/>
        <source>Error</source>
        <translation>Ошибка</translation>
    </message>
    <message>
        <source>Could not open the folder</source>
        <translation>Не удалось открыть папку</translation>
    </message>
    <message>
        <source>Drop files to inspect</source>
        <translation>Отпустите файлы для осмотра</translation>
    </message>
    <message>
        <source>Inspecting…</source>
        <translation>Осмотр…</translation>
    </message>
    <message>
        <source>Select files</source>
        <translation>Выбрать файлы</translation>
    </message>
    <message>
        <source>Supply and distribution files (*.efd *.zip *.rar *.dmg *.tar *.gz *.bz2 *.xz)</source>
        <translation>Поставки и дистрибутивы (*.efd *.zip *.rar *.dmg *.tar *.gz *.bz2 *.xz)</translation>
    </message>
    <message>
        <source>Without demo databases</source>
        <translation>Без демобаз</translation>
    </message>
    <message>
        <source>saves %s</source>
        <translation>на %s меньше</translation>
    </message>
    <message>
        <source>templates</source>
        <translation>шаблоны</translation>
    </message>
    <message>
        <source>distributions</source>
        <translation>дистрибутивы</translation>
    </message>
    <message>
        <source>Drag files here</source>
        <translation>Перетащите файлы сюда</translation>
    </message>
    <message>
        <source>1C folder</source>
        <translation>Каталог 1С</translation>
    </message>
    <message>
        <source>Change</source>
        <translation>Изменить</translation>
    </message>
    <message>
        <source>inside it</source>
        <translation>внутри него</translation>
    </message>
    <message>
        <source>for templates</source>
        <translation>для шаблонов</translation>
    </message>
    <message>
        <source>for distributions</source>
        <translation>для дистрибутивов</translation>
    </message>
    <message>
        <source>Clear all marks</source>
        <translation>Снять все</translation>
    </message>
    <message>
        <source>Clear list</source>
        <translation>Очистить список</translation>
    </message>
    <message>
        <source>Stop</source>
        <translation>Остановить</translation>
    </message>
    <message>
        <source>About</source>
        <translation>О программе</translation>
    </message>
    <message>
        <source>about</source>
        <translation>осталось ≈</translation>
    </message>
    <message>
        <source>in</source>
        <translation>за</translation>
    </message>
    <message>
        <source>sec</source>
        <translation>с</translation>
    </message>
    <message>
        <source>min</source>
        <translation>мин</translation>
    </message>
    <message>
        <source>stopped</source>
        <translation>остановлено</translation>
    </message>
    <message>
        <source>Settings</source>
        <translation>Настройки</translation>
    </message>
    <message>
        <source>Where to unpack…</source>
        <translation>Куда распаковывать…</translation>
    </message>
    <message>
        <source>Tools for .rar</source>
        <translation>Инструменты для .rar</translation>
    </message>
    <message>
        <source>Tools…</source>
        <translation>Инструменты…</translation>
    </message>
</context>
<context>
    <name>UnpackService</name>
    <message>
        <location filename="../unpack_service.py" line="12"/>
        <source>Unpacking completed successfully</source>
        <translation>Распаковка завершена успешно</translation>
    </message>
    <message>
        <location filename="../unpack_service.py" line="14"/>
        <source>File not found</source>
        <translation>Файл не найден</translation>
    </message>
    <message>
        <location filename="../unpack_service.py" line="16"/>
        <source>Permission error</source>
        <translation>Ошибка доступа к файлу</translation>
    </message>
    <message>
        <location filename="../unpack_service.py" line="18"/>
        <source>Archive rejected: it tries to write outside the output folder</source>
        <translation>Архив отклонён: он пытается записать файлы за пределы папки распаковки</translation>
    </message>
    <message>
        <location filename="../unpack_service.py" line="20"/>
        <source>Archive rejected: unpacked size exceeds the allowed limit</source>
        <translation>Архив отклонён: объём распакованных данных превышает допустимый предел</translation>
    </message>
    <message>
        <location filename="../unpack_service.py" line="22"/>
        <source>Archive is damaged or incomplete: %1</source>
        <translation>Архив повреждён или неполон: %1</translation>
    </message>
    <message>
        <source>This archive format is not supported: %1</source>
        <translation>Этот формат архива не поддерживается: %1</translation>
    </message>
    <message>
        <source>Archive rejected: too many nested archives</source>
        <translation>Архив отклонён: слишком много вложенных архивов</translation>
    </message>
    <message>
        <source>Archive rejected: too many files inside</source>
        <translation>Архив отклонён: слишком много файлов внутри</translation>
    </message>
    <message>
        <location filename="../unpack_service.py" line="24"/>
        <source>the file is incomplete, most likely the download was interrupted</source>
        <translation>файл неполный, скорее всего загрузка оборвалась</translation>
    </message>
    <message>
        <source>the file is not an EFD archive or its contents are damaged</source>
        <translation>файл не является архивом EFD или его содержимое повреждено</translation>
    </message>
    <message>
        <source>the archive could not be read, most likely the download was interrupted</source>
        <translation>архив не удалось прочитать, скорее всего загрузка оборвалась</translation>
    </message>
    <message>
        <location filename="../unpack_service.py" line="26"/>
        <source>the file is too short to be an EFD archive</source>
        <translation>файл слишком короткий для архива EFD</translation>
    </message>
    <message>
        <location filename="../unpack_service.py" line="28"/>
        <source>unsupported format version</source>
        <translation>неподдерживаемая версия формата</translation>
    </message>
    <message>
        <source>a file name inside the archive is unreadable</source>
        <translation>имя файла внутри архива не читается</translation>
    </message>
    <message>
        <location filename="../unpack_service.py" line="30"/>
        <source>a file inside the archive is shorter than declared</source>
        <translation>файл внутри архива короче заявленного размера</translation>
    </message>
    <message>
        <location filename="../unpack_service.py" line="32"/>
        <source>the archive contains two files with the same name</source>
        <translation>в архиве два файла с одинаковым именем</translation>
    </message>
    <message>
        <location filename="../unpack_service.py" line="34"/>
        <source>a file name in the archive conflicts with a folder name</source>
        <translation>имя файла в архиве конфликтует с именем папки</translation>
    </message>
    <message>
        <location filename="../unpack_service.py" line="36"/>
        <source>Unpacking was stopped, some files were not extracted</source>
        <translation>Распаковка остановлена, часть файлов не извлечена</translation>
    </message>
    <message>
        <location filename="../unpack_service.py" line="17"/>
        <source>Unexpected error: %1</source>
        <translation>Неожиданная ошибка: %1</translation>
    </message>
</context>
<context>
    <name>SettingsService</name>
    <message>
        <source>used last time</source>
        <translation>использовался прошлый раз</translation>
    </message>
    <message>
        <source>from 1cestart.cfg</source>
        <translation>из 1cestart.cfg</translation>
    </message>
    <message>
        <source>by default</source>
        <translation>по умолчанию</translation>
    </message>
</context>
<context>
    <name>FileValidator</name>
    <message>
        <source>File does not exist</source>
        <translation>Файл не существует</translation>
    </message>
    <message>
        <source>Path is not a file</source>
        <translation>Путь не является файлом</translation>
    </message>
    <message>
        <source>Invalid file format. Expected .efd file</source>
        <translation>Неверный формат файла. Ожидается файл .efd</translation>
    </message>
    <message>
        <source>No permission to read file</source>
        <translation>Нет прав на чтение файла</translation>
    </message>
    <message>
        <source>File is empty</source>
        <translation>Файл пустой</translation>
    </message>
    <message>
        <source>Cannot access file size</source>
        <translation>Не удается получить размер файла</translation>
    </message>
    <message>
        <source>Output directory path is empty</source>
        <translation>Путь к папке вывода пустой</translation>
    </message>
    <message>
        <source>Output path exists but is not a directory</source>
        <translation>Путь вывода существует, но не является папкой</translation>
    </message>
    <message>
        <source>No permission to write to output directory</source>
        <translation>Нет прав на запись в папку вывода</translation>
    </message>
    <message>
        <source>No permission to create output directory</source>
        <translation>Нет прав на создание папки вывода</translation>
    </message>
    <message>
        <source>Invalid output directory path</source>
        <translation>Неверный путь к папке вывода</translation>
    </message>
    <message>
        <source>Failed to create output directory: %1</source>
        <translation>Не удалось создать папку вывода: %1</translation>
    </message>
    <message>
        <source>Unexpected error: %1</source>
        <translation>Неожиданная ошибка: %1</translation>
    </message>
</context>
<context>
    <name>CLIHelp</name>
    <message>
        <source>EFD Unpacker - cross-platform EFD file unpacker</source>
        <translation>EFD Unpacker - кроссплатформенный распаковщик файлов EFD</translation>
    </message>
    <message>
        <source>CLI modes:</source>
        <translation>Режимы CLI:</translation>
    </message>
    <message>
        <source>1. GUI mode: open the window and preselect the input file</source>
        <translation>1. Режим GUI: открыть окно и заранее выбрать входной файл</translation>
    </message>
    <message>
        <source>2. Headless mode: unpack directly in the console</source>
        <translation>2. Консольный режим: распаковать напрямую в консоли</translation>
    </message>
    <message>
        <source>3. Inspect mode: show what is inside without unpacking</source>
        <translation>3. Режим осмотра: показать состав, ничего не распаковывая</translation>
    </message>
    <message>
        <source>Usage:</source>
        <translation>Использование:</translation>
    </message>
</context>
<context>
    <name>Report</name>
    <message>
        <source>paths:</source>
        <translation>пути:</translation>
    </message>
    <message>
        <source>template</source>
        <translation>шаблон</translation>
    </message>
    <message>
        <source>distribution</source>
        <translation>дистрибутив</translation>
    </message>
    <message>
        <source>packages</source>
        <translation>пакеты</translation>
    </message>
    <message>
        <source>content</source>
        <translation>содержимое</translation>
    </message>
    <message>
        <source>other</source>
        <translation>прочее</translation>
    </message>
    <message>
        <source>skipped</source>
        <translation>пропуск</translation>
    </message>
    <message>
        <source>error</source>
        <translation>отказ</translation>
    </message>
    <message>
        <source>already installed</source>
        <translation>уже установлено</translation>
    </message>
    <message>
        <source>excluded by filter</source>
        <translation>отфильтровано</translation>
    </message>
    <message>
        <source>format is not supported</source>
        <translation>формат не поддержан</translation>
    </message>
    <message>
        <source>no program for .rar</source>
        <translation>нет программы для .rar</translation>
    </message>
    <message>
        <source>nothing found inside</source>
        <translation>внутри ничего не найдено</translation>
    </message>
    <message>
        <source>no templates inside</source>
        <translation>нет шаблонов внутри</translation>
    </message>
    <message>
        <source>files:</source>
        <translation>файлов:</translation>
    </message>
    <message>
        <source>templates:</source>
        <translation>шаблонов:</translation>
    </message>
    <message>
        <source>distributions:</source>
        <translation>дистрибутивов:</translation>
    </message>
    <message>
        <source>other:</source>
        <translation>прочего:</translation>
    </message>
    <message>
        <source>skipped:</source>
        <translation>пропущено:</translation>
    </message>
    <message>
        <source>errors:</source>
        <translation>отказов:</translation>
    </message>
    <message>
        <source>written</source>
        <translation>записано</translation>
    </message>
    <message>
        <source>written:</source>
        <translation>записано:</translation>
    </message>
    <message>
        <source>stopped</source>
        <translation>остановлено</translation>
    </message>
    <message>
        <source>to write:</source>
        <translation>к записи:</translation>
    </message>
</context>
<context>
    <name>Screens</name>
    <message>
        <source>Back</source>
        <translation>Назад</translation>
    </message>
    <message>
        <source>Error</source>
        <translation>Ошибка</translation>
    </message>
    <message>
        <source>Could not open the link</source>
        <translation>Не удалось открыть ссылку</translation>
    </message>
    <message>
        <source>Where to unpack</source>
        <translation>Куда распаковывать</translation>
    </message>
    <message>
        <source>Configuration templates</source>
        <translation>Шаблоны конфигураций</translation>
    </message>
    <message>
        <source>The folder is dictated by 1C. Inside it the application creates 1c/&lt;product&gt;/&lt;version&gt; — that is what the supply standard requires.</source>
        <translation>Каталог задаёт 1С. Внутри приложение создаёт 1c/&lt;продукт&gt;/&lt;версия&gt; — так требует стандарт поставки.</translation>
    </message>
    <message>
        <source>Platform and DBMS distributions</source>
        <translation>Дистрибутивы платформы и СУБД</translation>
    </message>
    <message>
        <source>Here 1C dictates nothing. By default it sits next to the templates, in a neighbouring folder: change the templates folder and this one follows.</source>
        <translation>Тут 1С ничего не диктует. По умолчанию — рядом с шаблонами, в соседней папке: сменится каталог шаблонов, сменится и этот.</translation>
    </message>
    <message>
        <source>next to the templates</source>
        <translation>рядом с шаблонами</translation>
    </message>
    <message>
        <source>chosen manually</source>
        <translation>выбран вручную</translation>
    </message>
    <message>
        <source>Choose another folder…</source>
        <translation>Выбрать другую папку…</translation>
    </message>
    <message>
        <source>Select the templates folder</source>
        <translation>Выберите каталог шаблонов</translation>
    </message>
    <message>
        <source>Select the distributions folder</source>
        <translation>Выберите каталог дистрибутивов</translation>
    </message>
    <message>
        <source>free</source>
        <translation>свободно</translation>
    </message>
    <message>
        <source>needed</source>
        <translation>нужно</translation>
    </message>
    <message>
        <source>Done</source>
        <translation>Готово</translation>
    </message>
    <message>
        <source>Unpacking tools</source>
        <translation>Инструменты распаковки</translation>
    </message>
    <message>
        <source>Archives in .rar are unpacked by an external program. The application neither installs it nor ships it — it only finds it and calls it.</source>
        <translation>Архивы .rar распаковываются внешней программой. Приложение её не устанавливает и не включает в свою поставку — только находит и вызывает.</translation>
    </message>
    <message>
        <source>Searching…</source>
        <translation>Ищем…</translation>
    </message>
    <message>
        <source>IN USE</source>
        <translation>ИСПОЛЬЗУЕТСЯ</translation>
    </message>
    <message>
        <source>spare</source>
        <translation>про запас</translation>
    </message>
    <message>
        <source>not found</source>
        <translation>не найден</translation>
    </message>
    <message>
        <source>searched as %s</source>
        <translation>ищется как %s</translation>
    </message>
    <message>
        <source>checked on %s: %d entries</source>
        <translation>проверена на %s: записей — %d</translation>
    </message>
    <message>
        <source>Copy</source>
        <translation>Копировать</translation>
    </message>
    <message>
        <source>Copied</source>
        <translation>Скопировано</translation>
    </message>
    <message>
        <source>Fitness is checked on the archive itself, not by version number: libarchive builds ship with different format sets, and the list of supported ones can lie.</source>
        <translation>Годность проверяется на самом архиве, а не по номеру версии: сборки libarchive собирают с разным набором форматов, и список поддержки может врать.</translation>
    </message>
    <message>
        <source>Without such a program .rar files are simply skipped</source>
        <translation>Без такой программы файлы .rar просто пропускаются</translation>
    </message>
    <message>
        <source>Search again</source>
        <translation>Искать заново</translation>
    </message>
    <message>
        <source>About</source>
        <translation>О программе</translation>
    </message>
    <message>
        <source>Unpacking of 1C:Enterprise supply files and laying out platform distributions into folders.</source>
        <translation>Распаковка поставок 1С:Предприятия и раскладка дистрибутивов платформы по каталогам.</translation>
    </message>
    <message>
        <source>Source code on GitHub</source>
        <translation>Исходный код на GitHub</translation>
    </message>
    <message>
        <source>Report a problem</source>
        <translation>Сообщить о проблеме</translation>
    </message>
    <message>
        <source>Check for updates</source>
        <translation>Проверить обновление</translation>
    </message>
    <message>
        <source>Licenses</source>
        <translation>Лицензии</translation>
    </message>
    <message>
        <source>Full texts</source>
        <translation>Полные тексты</translation>
    </message>
    <message>
        <source>Programs for .rar are not part of the package — the application calls the ones installed in the system.</source>
        <translation>Программы для .rar в поставку не входят — приложение вызывает установленные в системе.</translation>
    </message>
    <message>
        <source>Ingvar Consulting helps 1C teams sort out development processes: planning, releases, reviews, onboarding, and makes the team more manageable.</source>
        <translation>Ingvar Consulting помогает 1С-командам разбирать процессы разработки: планирование, релизы, ревью, онбординг и повышает управляемость команды.</translation>
    </message>
    <message>
        <source>first in line</source>
        <translation>будет первой</translation>
    </message>
</context>
</TS>
