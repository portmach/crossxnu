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

После этих правок ядро больше не падает и честно показывает, что процесс
пользователя выполнился:

```text
pid 1 exited -- no exit reason available -- (signal 0, exit 1)
panic: initproc failed to start … (exit status 1)
Thread 0 crashed
RIP: 0x1047368de   RAX: 0x2000001     # 0x2000001 = exit(1)
```

Проверка подменой init'а (ядро грузит ровно `/sbin/launchd`, поэтому образ
собирается с другим файлом на этом месте):

| init | результат |
|:-----|:----------|
| recovery `/bin/cat` | загрузился, dyld поднял ~30 образов, вышел с кодом 1 (нет stdin) |
| payload `/bin/sh` | загрузился, вышел с кодом 1 |
| `#!/bin/sh` + скрипт | интерпретатор запустился (`shared_region: [1(sh)]`), вышел с кодом 1 |
| recovery `/sbin/launchd` | SIGILL — падает уже сам launchd, не dyld |

То есть dyld, libSystem, libobjc и десятки dylib'ов **работают на нашем ядре**;
проблема конкретно в launchd.

## Следующий блокер: консоль

Вывод userland'а не доходит до serial. Причина — `/dev/console` в x86-ветке
XNU обслуживается драйвером `km` (`bsd/dev/i386/km.c`): `kminit()` вызывается
из `bsd_init()` **всегда**, `km_tty[0]` существует, но за ним стоит
VGA-фреймбуфер и PS/2-клавиатура. При `-display none` запись уходит в
эмулируемый VGA, а не в serial; ядро при этом пишет в serial напрямую
(`PE_kputc = pal_serial_putc`).

Добавлен шим в `bsd/dev/i386/cons.c` (под `CROSSXNU_SECURITY_PERMISSIVE`):
`cnopen`/`cnclose`/`cnread`/`cnwrite`/`cnioctl` при `crossxnu_serial_console()`
работают напрямую с `serial_getc()`/`serial_putc()`, минуя km. Ядро с ним
собирается, но вывод userland'а в serial пока не появился: `sh` завершается
с кодом 1, не успев ничего напечатать. Дальше — проверить, доходит ли
`cnwrite` вообще (fd 1/2 у pid 1 открывает сам ядро в `load_init_program`)
и нет ли ошибки на `open("/dev/console")`.

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
# recovery-root + патченный dyld
python3 scripts/hfs-image.py ~/recovery ~/rec.hfs
mcopy -o -i build/esp32.img ~/rec.hfs ::/ramdisk.img
# boot-args на ESP: -v serial=1
```
