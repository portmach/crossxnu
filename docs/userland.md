# Userland: ignition и первый запуск

Что происходит после монтирования recovery-root и как обойти ignition.

## Где сидит ignition

`libignition_core` **статически слинкован в dyld** (recovery `/usr/lib/dyld`,
1.1 MB). Симптом на нашем ядре:

```text
load_init_program: attempting to load /sbin/launchd
shared_region: [1(launchd)] check_np(...) vm_shared_region_start_address() returned 0x1
Darwin Ignition Sequence Version 1.0.0: … libignition_core/RELEASE_X86_64
libignition: 1:   ignition level    : 0x5
libignition: 1: ignition blob not available
```

`_ignite()` (`0x6b9e9` в recovery-dyld) вызывает `_configuration_init()`, а тот
читает через `sysctlbyname`:

| sysctl | назначение |
|:-------|:-----------|
| `security.mac.img4.ignition_blob` | IMG4-блоб; на реальной машине его кладёт iBoot |
| `security.mac.img4.ignition_failure_blob` | блоб для BRA при ошибке |
| `hw.osenvironment`, `kern.bootuuid`, `hw.targettype`, rootdev | окружение |

В нашем ядре этих sysctl'ов нет, `ignition_blob` возвращает `ENOENT`, и
последовательность обрывается.

## Обход

Два патча в recovery-dyld (образ пересобирается `scripts/hfs-image.py`):

1. `security.mac.img4.ignition_blob` ENOENT → принять как «блоб есть»
   (`0x6ca6a`: `83 f8 02 74 2c` → `31 c0 90 90 90`).
2. `_ignite()` → `xor eax, eax; ret` (`0x6b9e9`: `55 48 89 e5` → `31 c0 c3`),
   то есть ignition целиком пропускается.

После этого dyld идёт дальше и грузит `launchd` со всеми dylib'ами.

## Что выяснилось про ядро

Дальше вскрылись два NULL-разыменования в ядре, которых раньше не было видно:

| Паника | Причина | Правка |
|:-------|:--------|:-------|
| `Kernel trap … CR2=0` в `bsdthread_register` | `pthread_functions` NULL: `com.apple.kec.pthread` нет в синтетическом KC | `CROSSXNU_REQUIRE_PTHREAD_KEC()` во все 16 shim'ов → `ENOTSUP` |
| `CR2=0x1e0` в `IOTaskGetEntitlement` | `amfi == NULL` (AMFI KEC отсутствует) | `#ifdef CROSSXNU_SECURITY_PERMISSIVE if (!amfi) return NULL/false;` в трёх оставшихся entitlement-функциях |

Обе правки — в рабочих деревьях (`bsd/pthread/pthread_shims.c`,
`iokit/bsddev/IOKitBSDInit.cpp`), пока не вынесены в `patches/`.

## Результат: userland работает

Итоговый лог (`-v serial=1`, init — статический stub, который запускает
`/bin/sh /etc/rc.local`):

```text
=== crossxnu: macOS userland on a non-macOS kernel ===
Darwin  12377.121.6 Darwin Kernel Version 12377.121.6: … RELEASE_X86_64
ProductName:            macOS
ProductVersion:         26.7.2
BuildVersion:           25G332

--- root volume ---
drwxr-xr-x   4 1000 1000    136 Oct 22  2026 System
drwxr-xr-x  18 1000 1000    612 Oct 30  2026 bin
dr-xr-xr-x   3 root wheel  3781 Jan  1 00:03 dev
lrwxrwxrwx   1 1000 1000     11 Oct 22  2026 etc -> private/etc
drwxr-xr-x  10 1000 1000    340 Oct 22  2026 usr
lrwxrwxrwx   1 1000 1000     11 Oct 22  2026 var -> private/var

--- processes ---
  PID TTY           TIME CMD
    1 ??         6:04.68 /bin/sh /etc/rc.local
    6 ??         2:11.68 ps -A

--- mounts ---
root_device on / (hfs, local, read-only)
devfs on /dev (devfs, local, nobrowse)

--- sysctl ---
kern.ostype: Darwin
kern.version: Darwin Kernel Version 12377.121.6: …
```

То есть на нашем ядре работают: dyld, `bash`/`sh`, `uname`, `sw_vers`, `ls`,
`ps`, `mount`, `sysctl`, `cat` — настоящие бинарники macOS 26.7.2 (recovery
ramdisk сборки `25G332`), с HFS+ в качестве корня, devfs и таблицей процессов.

## Как это получилось

| Шаг | Файл |
|:----|:-----|
| обход ignition в dyld | `_ignite` → `xor eax,eax; ret`, `docs/userland.md` |
| `pthread_functions == NULL` | `bsd/pthread/pthread_shims.c` |
| `amfi == NULL` | `iokit/bsddev/IOKitBSDInit.cpp` |
| `/dev/console` → serial | `bsd/dev/i386/cons.c` |
| init без stdio | `userland/init.c` (статический Mach-O, `scripts/build-init.sh`) |

## Почему понадобился свой init

Ядро запускает `/sbin/launchd` как pid 1 **без fd 0/1/2**: `write(1, …)`
возвращает `EBADF`. Скрипт с `#!` или сам `/bin/sh` умирают молча, потому что
stderr тоже закрыт. Статический stub (`userland/init.c`, 8.6 KB, без dyld)
открывает `/dev/console`, делает `dup2` на 0/1/2 и делает
`execve("/bin/sh", {"/bin/sh", "/etc/rc.local"})`.

Ещё одна деталь: `/bin/sh` в macOS — это multi-call `bash`, который
перезапускает себя как `/bin/bash`. Без `/bin/bash` в root'е он печатает
`Failed to exec /bin/bash as variant for /bin/sh (2: No such file or directory)`
и выходит с кодом 1. Поэтому в образ нужно положить оба файла.

## Записываемый root и scratch-том

Корень монтируется read-only жёстко: `vfs_rootmountalloc_internal()` ставит
`MNT_RDONLY | MNT_ROOTFS`, а на macOS его потом переводит в rw уже userland
(через HFS+ update-mount с `hfs_mount_args`). Под `CROSSXNU_SECURITY_PERMISSIVE`
флаг убран — корень монтируется как `(hfs, local)`, то есть rw.

Но запись всё равно падает с `ENOSPC`: `xorrisofs` пишет том ровно по объёму
данных, `freeBlocks = 0` (проверяется в volume header по смещению `0x34`).
Смонтировать полный том rw можно, писать в него нельзя.

Поэтому в ядре добавлен второй memory device: `setconf()` выделяет 256 MB
через `kmem_alloc(kernel_map, …)` и регистрирует их как `md1`
(`crossxnu: scratch device md1`). Дальше userland должен был отформатировать
его `newfs_hfs` и смонтировать в `/private/var`.

Что уже работает:

```text
brw-------  1 root  operator  0x1000001 Jan  1 00:03 /dev/md1
--- formatting md1 ---
Initialized /dev/rmd1 as a 256 MB case-insensitive HFS Plus volume
newfs ok
```

Для этого пришлось научить `memdev` отвечать на дисковые ioctl'ы, которые
`newfs_hfs`/`mount_hfs` спрашивают у устройства (`DKIOCGETMAXBYTECOUNTREAD/
WRITE`, `DKIOCGETTHROTTLEMASK`, `DKIOCGETPHYSICALBLOCKSIZE`, `DKIOCISVIRTUAL`,
`DKIOCGETFEATURES`, `DKIOCGETPROVISIONSTATUS`, `DKIOCCORESTORAGE`,
`DKIOCGETERRORDESCRIPTION`), и не менять сектор устройства по
`DKIOCSETBLOCKSIZE` с raw-char узла.

Осталось: **mount свежесозданного тома падает в ядре** — trap (invalid opcode,
`hfs_assert`) внутри `cat_create` при `hfs_mountfs`. Корневой том (собранный
`xorrisofs`) монтируется нормально, а пустой том от `newfs_hfs` — нет.
Похоже на ветку создания/чтения пустого catalog B-tree, которой в перенесённом
коде HFS+ не хватает; это следующий конкретный шаг.

## Ограничения, которые видны сразу

- корень смонтирован **read-only** (`mount` → `hfs, local, read-only`),
  поэтому `/tmp/crossxnu.txt` не создаётся; нужен rw-mount и `/tmp`;
- в recovery-root'е нет `/tmp` как symlink'а (есть только `etc`, `var`);
- `kern.osversion` пустой — ядро не заполняет его для нашего конфига;
- `uname` печатает `sysctl: Invalid argument` для одного поля (`hw.machine`).

## Консоль: почему её не было и как починили

`/dev/console` в x86-ветке XNU обслуживается драйвером `km`
(`bsd/dev/i386/km.c`): `kminit()` вызывается из `bsd_init()` **всегда**,
`km_tty[0]` существует, но за ним стоит VGA-фреймбуфер и PS/2-клавиатура.
При `-display none` запись уходит в эмулируемый VGA, а не в serial; ядро при
этом печатает в serial напрямую (`PE_kputc = pal_serial_putc`) — поэтому
казалось, что «консоль работает, а userland молчит».

Шим в `bsd/dev/i386/cons.c` (под `CROSSXNU_SECURITY_PERMISSIVE`) переводит
`cnopen`/`cnclose`/`cnread`/`cnwrite`/`cnioctl` на `serial_getc()`/`serial_putc()`
минуя km. Проверка статическим probe'ом:

```text
crossxnu: cnopen entry dev=0
crossxnu: cnopen(serial console)
PROBE: static userland on crossxnu
pid 1 exited -- no exit reason available -- (signal 0, exit 42)
```

`42` — код «write(1) успешно записал весь баннер»; до шима тот же probe
возвращал `9` (`EBADF`), потому что pid 1 не получает fd'ов от ядра.

## Что изменено в ядре

| Файл | Изменение |
|:-----|:----------|
| `bsd/pthread/pthread_shims.c` | `CROSSXNU_REQUIRE_PTHREAD_KEC()` в 16 syscall-шимах → `ENOTSUP` |
| `iokit/bsddev/IOKitBSDInit.cpp` | `amfi == NULL` guards в 3 оставшихся entitlement-функциях |
| `bsd/dev/i386/cons.c` | serial-бэкенд для `/dev/console` |

Все три — в рабочем дереве `upstream/xnu`; в `patches/` пока не вынесены
(как и HFS+-интеграция).

## Воспроизведение

```bash
# 1. init-заглушка (статический Mach-O) и rc.local
./scripts/build-init.sh build/init
cp build/init  ~/recovery/sbin/launchd          # ядро грузит именно этот путь
cp userland/rc.local ~/recovery/etc/rc.local

# 2. /bin/sh и /bin/bash из payload-root'а (bash перезапускает себя как /bin/bash)
cp ~/aa/root/bin/sh   ~/recovery/bin/sh
cp ~/aa/root/bin/bash ~/recovery/bin/bash

# 3. образ и ESP
python3 scripts/hfs-image.py ~/recovery ~/rec.hfs
mcopy -o -i build/esp32.img ~/rec.hfs ::/ramdisk.img
# boot-args на ESP: -v serial=1
```

Важно: dyld в образе — пропатченный (см. выше), иначе до userland дело не
дойдёт. Оригинальный `launchd` сохранён как `/sbin/launchd.real`.

