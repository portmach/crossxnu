# System root из `payloadv2`

Как собрать обычный (не recovery) корневой том macOS из установочного asset'а,
и что при этом выяснилось.

## Где лежат данные

`InstallAssistant.pkg` → `SharedSupport.dmg` → `Shared Support/`:

| Путь | Размер | Что это |
|:-----|-------:|:--------|
| `com_apple_MobileAsset_MacSoftwareUpdate/3c3d…b4.zip` | 18.4 GB | сам asset: `AssetData/` |
| `com_apple_MobileAsset_MobileSoftwareUpdate_MacUpdateBrain/*.zip` | 4.4 MB | update brain, к root'у не относится |

Внутри asset'а (16.2 GB на `payloadv2`):

| Путь | Что это |
|:-----|:--------|
| `payloadv2/payload.000 … payload.052` | 53 сегмента системы, каждый — свой Apple Archive |
| `payloadv2/payload.NNN.ecc` | Reed–Solomon ECC, для распаковки не нужен |
| `payloadv2/fixup.manifest` | pbzx + Apple Archive: firmlinks, корневые symlink'и, режимы |
| `payloadv2/links.txt` | 50 180 строк `=`/`+` — список link-путей |
| `payloadv2/payloadv2.bom` | BOM нового тома |
| `payloadv2/payload_chunks.txt` | размеры чанков (не совпадают с фактическим выходом pbzx — использовать только как справку) |
| `payloadv2/basesystem_patches/x86_64BaseSystem.dmg` | `BXDIFF50`, 892 MB — **дифф** к BaseSystem |
| `payloadv2/image_patches/cryptex-system-x86_64` | `RIDIFF10`, 1.6 GB — **дифф** к системному cryptex |
| `payloadv2/image_patches/cryptex-app` | `RIDIFF10`, 31 MB — дифф к app cryptex |

## Контейнеры

### pbzx

```text
"pbzx"                  4 байта
u64be blockSize         номинальный размер блока (обычно 8 MiB, у fixup — 1 MiB)
повтор:
    u64be uncompressedSize
    u64be compressedSize
    <compressedSize>    xz-контейнер (начинается с FD 37 7A 58 5A)
```

Каждый чанк распаковывается независимо, `uncompressedSize` — его точный размер.
Никакой склейки между чанками нет: это один непрерывный поток.

### Apple Archive (YAA1)

```text
"YAA1" (или "AA01")     4 байта
u16le headerSize
<headerSize-6>          поля
[DAT: dataSize байт]    только у файлов
[XAT: xatSize байт]     расширенные атрибуты
```

Поле: `u32be` = key (24 бита) + subtype (8 бит), затем значение:

| subtype | значение |
|:--------|:---------|
| `*` | флаг, данных нет |
| `1` `2` `4` `8` | беззнаковое целое 1/2/4/8 байт (little-endian) |
| `A` `B` `C` | blob 2/4/8 байт |
| `F` `G` `H` `I` `J` | hash 4/20/32/48/64 байт |
| `S` `T` | timespec 8/12 байт |
| `P` | строка: u16le длина + байты |

Ключи, которые нужны для распаковки: `PAT` (путь), `TYP` (`D` каталог, `F` файл,
`L` symlink), `DAT` (размер данных), `LNK` (цель symlink), `XAT` (размер xattr),
`MOD` (режим). Архив — плоская последовательность записей; **родительские
каталоги в нём не обязательны**.

## Что было не так раньше

В `docs/hfs.md` было записано, что крупные файлы «размазаны по нескольким
payload-сегментам». Это неверно. Настоящая причина — усечённая распаковка:

```text
AA overflow: path=System/Library/Frameworks/QuartzCore.framework/…/default.metallib
             dataSize=160153248 endOfFile=8388442
```

`endOfFile = 8388442` — это ровно 8 MiB минус заголовки, то есть распаковщик
останавливался на лимите в 8 MiB (позже — 200 MiB), а не архив кончался.
Кроме того `neoaa` не создаёт родительские каталоги, поэтому падал ещё и на
`fopen` для первого же файла.

Проверка после исправления: `payload.010` — 43 чанка, 358 727 489 байт
распакованного Apple Archive, извлекается целиком (5 файлов, 343 MB).

## Инструменты

Оба скрипта — чистый Python 3, без macOS-тулинга и без внешних библиотек.

```bash
# один payload: распаковать pbzx и извлечь
python3 scripts/aa.py unpbxz payload.010 payload.010.aar
python3 scripts/aa.py list payload.010.aar
python3 scripts/aa.py extract payload.010.aar root/

# весь root: параллельно, с metadata и fixup.manifest
python3 scripts/extract-payloadv2.py \
    --asset "…/3c3d…b4.zip" \
    --root ~/root \
    --jobs 6 --metadata --fixup
```

`scripts/extract-payloadv2.py` читает zip потоком (payload'ы в нём хранятся без
сжатия), распаковывает pbzx во временный `.aar`, извлекает и удаляет его.
Пиковый объём — `jobs × ~350 MB`.

Извлечение идемпотентно: повторный запуск перезаписывает файлы, поэтому
прерванный прогон можно продолжить тем же `--payloads`.

### Место на диске

- дерево: ~20 GB;
- asset zip: 18.4 GB;
- временные `.aar`: `jobs × 350 MB`.

В WSL это всё лежит внутри `ext4.vhdx`, который растёт, но **не сжимается сам**:
если хост-диск кончится, WSL начнёт отдавать `EIO`. После чистки внутри WSL
место на хосте возвращается только `diskpart → compact vdisk` (нужен админ)
или `wsl --manage <distro> --set-sparse true` (на VHD2 не поддерживается).

## Результат

```text
extracted 53/53 payloads: archive=19354280697 files=… dirs=… links=…
```

- 19 GB, 179 712 файлов;
- `/sbin/launchd` (1.2 MB), `/usr/lib/dyld` (2.5 MB),
  `/System/Library/CoreServices/SystemVersion.plist`;
- 418 `LaunchDaemons`, 754 kext'а в `/System/Library/Extensions`;
- `/System/Cryptexes/{OS,App,ExclaveOS}` — пустые точки графта.

### fixup.manifest

Это манифест всего тома: 299 962 записи `F` с **пустым** `DAT`, 170 576
каталогов и 16 065 symlink'ов. Поэтому его нельзя распаковывать как обычный
архив — файловые записи обнулят дерево. `aa.extract(..., write_files=False)`
применяет только структуру и режимы:

```text
fixup.manifest: 82348727 bytes -> files=299962 dirs=170576 links=16065 bytes=0
```

После него в корне появляются `/var → private/var`, `/tmp`, `/Users`, `/cores`,
`/dev`, `.VolumeIcon.icns → System/Volumes/Data/.VolumeIcon.icns` и остальные
стандартные точки.

### links.txt

50 180 строк с префиксами `=` (22 309) и `+` (27 871). В самих payload'ах
symlink'ов нет (`links=0`), поэтому это список hardlink-групп тома; для
загрузки не критичен, но пригодится, чтобы не раздувать образ копиями
одинаковых файлов.

## Чего в root'е нет: cryptex

Это главный вывод. Корневой том macOS 11+ **не самодостаточен**:

```text
$ ls root/usr/lib
dsc_extractor.bundle  dtrace  dyld  ignition  libRPAC.dylib  libgmalloc.dylib
libobjc-trampolines.dylib  pam  rpcsvc  sasl2  ssh-keychain.dylib  swift …
$ strings root/bin/sh | grep libSystem
/usr/lib/libSystem.B.dylib        # файла в root'е нет
```

`/usr/lib/libSystem.B.dylib`, `libsystem_*.dylib`, `libobjc.A.dylib` и общий
dyld shared cache живут в **системном cryptex** (`/System/Cryptexes/OS`).
В asset'е для них есть только диффы:

- `basesystem_patches/x86_64BaseSystem.dmg` — `BXDIFF50` (нужен базовый образ);
- `image_patches/cryptex-system-x86_64` — `RIDIFF10` (внутри — pbzx-потоки,
  в первых 40 MB нет ни строк путей, ни признаков полного образа).

То есть `payloadv2` — это **дельта** к уже установленной системе. Собрать из
неё работающий обычный userland нельзя, пока нет базы (полный установщик,
`OS.dmg` или IPSW для нужной сборки).

Для сравнения: recovery-ramdisk (`x86_64SURamDisk.dmg`) **самодостаточен** —
в нём настоящие `libSystem.B.dylib` (45 KB), `libobjc.A.dylib` (441 KB) и 78 MB
`/usr/lib`, без shared cache. Именно поэтому recovery-`launchd` и запускается
нашим ядром.

## Что это значит для проекта

1. Корневой том можно собрать и смонтировать — это уже проверено на recovery.
2. Обычный `launchd` из `payloadv2` не запустится без cryptex: dyld не найдёт
   `libSystem.B.dylib`.
3. Дальше нужно либо достать базовый cryptex (полный образ системы), либо
   строить userland из открытых исходников (PureDarwin-подход), либо
   использовать recovery-userland как единственную доступную среду.

## Ignition: что именно нужно

Recovery-`launchd` доходит до ignition и останавливается:

```text
load_init_program: attempting to load /sbin/launchd
shared_region: [1(launchd)] check_np(...) vm_shared_region_start_address() returned 0x1
Darwin Ignition Sequence Version 1.0.0: … libignition_core/RELEASE_X86_64
libignition: 1:   ignition level    : 0x5
libignition: 1:   force dylib root  : 0x0
libignition: 1:   halt after stage  : n/a
libignition: 1: ignition blob not available
```

Ignition живёт **внутри dyld** (`libignition_core` слинкован туда), уровень уже
максимальный (5), не хватает только blob'а из IMG4-манифеста:

- `security.mac.img4.ignition_blob` / `security.mac.img4.ignition_failure_blob`
  — sysctl, который на реальной машине заполняет iBoot/boot.efi;
- boot-args: `ignition_level`, `ignition_halt_after`, `ignition_force_dylib_root`,
  `ignition_prereboot_graft`, `ignition_live_app_graft`;
- `usr/lib/ignition` в payload-root — отдельный 252 KB бинарь той же сборки.

Дальше — либо подсунуть blob (реализовать sysctl в нашем ядре / прокинуть через
devicetree), либо патчить проверку в dyld.

## Следующие шаги

- Разобрать `RIDIFF10`/`BXDIFF50`: понять, есть ли в них полные данные
  (тогда базу cryptex можно восстановить из asset'а).
- Ignition: проверить boot-args и, если их не хватает, патчить dyld
  (recovery-userland — единственная среда, которая запускается без cryptex).
- Применить `links.txt` как hardlink-группы, чтобы уменьшить образ.

