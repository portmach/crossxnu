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

## Интерактивная консоль

`/dev/console` в гостя — это serial UART, поэтому интерактив зависит только от
того, как QEMU подключён к порту:

| `-serial` | что получается |
|:----------|:---------------|
| `file:build/serial.log` | односторонний лог, ввод недоступен |
| `stdio` | ваш терминал = консоль гостя, можно печатать команды |
| `tcp:127.0.0.1:4555,server=on,wait=off` | можно подключиться `nc`/скриптом |

Быстрый способ:

```powershell
pwsh -File scripts/run-console.ps1
```

Скрипт поднимает QEMU с `-serial stdio`; через ~50 секунд появляется
приглашение. `/etc/rc.local` в образе печатает короткий отчёт и делает
`exec /bin/sh -i`.

Проверенный сеанс:

```text
sh-3.2# echo INTERACTIVE-OK
INTERACTIVE-OK
sh-3.2# ls /
System  bin  dev  etc  mnt1  mnt2 … private  sbin  tmp  usr  var
sh-3.2# ps -A
  PID TTY           TIME CMD
    1 ??        20:07.29 /bin/sh -i
    7 ??         2:15.24 ps -A
sh-3.2# cat /System/Library/CoreServices/SystemVersion.plist
… <string>26.7.2</string> …
sh-3.2# echo typed-by-user
typed-by-user
```

Что попробовать:

```sh
uname -a
sw_vers
ls -l /
mount
ps -A
sysctl kern.ostype
cat /System/Library/CoreServices/SystemVersion.plist
echo hi > /tmp/x        # ENOSPC: том заполнен, см. ниже
exit                    # pid 1 выходит -> kernel panic "initproc exited"
```

Ограничения сеанса: нет управления размером терминала и ANSI-редактирования
(serial без tty), `exit` роняет ядро (потому что init — это и есть шелл),
корень доступен только на чтение (том заполнен), `uname` ругается на
отсутствующий `hw.machine`.

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

Осталось: **mount свежесозданного тома падал в ядре** — trap (invalid opcode)
внутри `cat_create` при `hfs_mountfs`. Причина найдена и исправлена; разбор —
в [`hfs.md`](hfs.md#запись-на-свежий-том-fortify_source_strict-и-cat_create).
Коротко: `bcopy()` по 32 байта Finder Info попадал под
`_FORTIFY_SOURCE_STRICT`-проверку (16-байтовое поле `userInfo`), clang
сворачивал её в безусловный `ud2`. После перевода этих копий на
`__nochk_bcopy()` свежий том монтируется и пишется:

```text
sh-3.2# mount -t hfs /dev/md1 /private/var
hfs: mounted scratch on device md1
sh-3.2# mkdir -p /private/var/a/b/c
sh-3.2# echo hello-hfs > /private/var/hello
sh-3.2# cat /private/var/hello
hello-hfs
sh-3.2# df /private/var
/dev/md1       524288 12328    511960     3%       7 4294967272    0%   /private/var
```

Сборка с `-fno-strict-aliasing` (флаг остаётся в `scripts/build.sh`) trap не
убирала — это была тупиковая ветка диагностики, а не причина.


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


## launchd: code signing и SIGILL

Записываемый `/private/var` (см. [`hfs.md`](hfs.md)) — необходимое, но не
достаточное условие: `launchd` всё равно умирает с SIGILL. Первые сообщения
на этом пути были про code signing:

```text
sh-3.2# /sbin/launchd.real
unable to validate security-critical blob: 85 [9|4208886145]
check_signature[pid: 7]: error = 1
proc 7: load code signature error 4 for file "launchd.real"
Text page corruption detected for pid 7
Illegal instruction: 4
```

- `85` = `EBADEXEC`, `4208886145` = `0xfade8181` =
  `CSMAGIC_EMBEDDED_LAUNCH_CONSTRAINT`. `validate_auxiliary_signed_blobs()`
  в `bsd/kern/ubc_subr.c` требует слоты 8..11 (self/parent/responsible/library
  launch constraints). У recovery-`launchd` нет слота 9
  (`CSSLOT_LAUNCH_CONSTRAINT_PARENT`), поэтому подпись не загружалась вовсе
  (`load code signature error 4`), и процесс оставался без `cs_blob`.
- `Text page corruption detected` (`osfmk/vm/vm_fault.c`) — cdhash текстовой
  страницы не сходится. SHA-256 в ядре приходит из corecrypto KEC
  (`g_crypto_funcs`), а без него шимы в `libkern/crypto/corecrypto_sha2.c`
  возвращают нулевой дайджест: проверка не может пройти в принципе. Ядро
  выбрасывало годную страницу из объекта, после чего процесс мог выполнять
  уже освобождённую страницу.

Под permissive-профилем обе проверки больше не enforced:

| Файл | Что добавлено |
|:-----|:--------------|
| `bsd/kern/ubc_subr.c` | `crossxnu_enforce_aux_signed_blobs = false`; `cs_blob_init()` грузит подпись без launch constraints |
| `osfmk/vm/vm_fault.c` | `crossxnu_cs_enforce_text_pages = false`; `CROSSXNU_VMP_CS_TAINTED()` не помечает страницу и не выбрасывает её |

Оба переключателя — обычные глобалы (`bool`), а не `#if`, чтобы код остался
собранным и включался одной строкой, когда появится настоящий SHA-256.

После пересборки `security-critical blob` и `Text page corruption` исчезли,
подпись грузится. SIGILL остался и это **настоящая** недопустимая инструкция:
QEMU `-d int` показывает ровно один `v=06 e=0000 cpl=3` c
`IP=0x1088d704f`. Ни в `launchd.real`, ни в `dyld`, ни в библиотеках нет
`ud0/ud1/ud2` по этому смещению в странице (`0x4f`), так что это не
clang-заглушка `__builtin_trap`. Рабочие версии:

1. инструкция, которой нет в текущей конфигурации (например `xgetbv` без
   `CR4.OSXSAVE`, или AVX-код, выбранный по CPUID);
2. код, сгенерированный dyld во время выполнения (у нас нет shared cache;
   `vm_shared_region_start_address()` возвращает `0x1`);
3. страница, содержимое которой не совпадает с файлом.

Следующий шаг — печатать в ядре для user-mode `#UD` путь образа и 8 байт по
`RIP` (в `osfmk/i386/trap.c`), чтобы ответить на эти вопросы одним запуском.

### SIGILL в launchd: `BUG IN LIBPTHREAD`

Чтобы не гадать по голому `RIP`, в `osfmk/i386/trap.c` добавлен отчёт для
user-mode `#UD`: под `CROSSXNU_SECURITY_PERMISSIVE` `user_trap()` печатает
`RIP`, смещение в странице и 16 байт инструкции (через `copyin`):

```text
crossxnu: user #UD rip=0x1050d004f page_off=0x4f insn=67 0f b9 80 01 b0 ff ff 0f 0b 55 48 89 e5 48 8d
```

Байты — это `ud1` + `ud2` (clang-заглушка), а не «левая» инструкция. Поиск
этих байтов по дереву recovery-образа даёт единственное совпадение:

```text
offset=0x904f  page_off=0x4f  usr/lib/system/libsystem_pthread.dylib
```

Это `__pthread_workqueue_supported.cold.1` — холодный блок, который перед
ловушкой пишет строку в `__crashreporter_info__`:

```text
9037/904f: ud1l -0x4fff(%eax), %eax ; ud2
0x9b06:   "BUG IN LIBPTHREAD: libpthread has not been initialized"
```

То есть падение — не порча кода и не отсутствующая инструкция CPU, а
сознательный `trap` в libpthread: **`__pthread_init()` не вызывался**. Его
вызывает kext `com.apple.kec.pthread` через таблицу `pthread_functions`
(`bsd/sys/pthread_shims.h`): `pthread_init()` в
`bsd/pthread/pthread_shims.c` сейчас под permissive просто печатает
`pthread KEC not loaded; skipping pthread_init` и возвращается.

Что нужно, чтобы это закрыть: собрать таблицу `pthread_functions` внутри ядра
вместо kext'а. В таблице ~25 живых слотов (остальные — `__unused_was_*`):
`pthread_init`, `pth_proc_hashinit/delete`,
`bsdthread_create/register/register2/terminate`, `thread_selfid`,
11 `psynch_*`, `pthread_find_owner`, `pthread_get_thread_kwq` и 5 `workq_*`.
Часть инфраструктуры уже есть в `pthread_shims.c` (аксессоры
`proc_get_threadstart`, `pthread_callbacks`, waitq/turnstile-код), но
`bsdthread_create` и `psynch_*` — это и есть тело закрытого kext'а, поэтому
это отдельная задача, а не односимвольная правка.

### Встроенная таблица `pthread_functions`

`com.apple.kec.pthread` в синтетическом kernel collection отсутствует, но
половина интерфейса уже есть в `bsd/pthread/pthread_shims.c` (шим'ы системных
вызовов и таблица `pthread_callbacks`). Поэтому таблицу `pthread_functions`
теперь собирает само ядро — `crossxnu_pthread_functions` в
`pthread_shims.c`; она ставится статически:

```c
SECURITY_READ_ONLY_LATE(pthread_functions_t) pthread_functions =
	&crossxnu_pthread_functions;      /* было NULL */
```

Важно: присваивать её в рантайме нельзя — `SECURITY_READ_ONLY_LATE` уже
защищён к моменту `pthread_init()`, и запись даёт page fault в
`_pthread_init+0xb`.

Что реализовано по-настоящему:

- `bsdthread_register` / `bsdthread_register2` — сохраняют `threadstart`,
  `wqthread`, `pthsize`, `stack_addr_hint`, TSD-смещения и
  `dispatchqueue_offset` в `proc`;
- `thread_selfid` — `thread_tid(current_thread())`;
- `pth_proc_hashinit/hashdelete`, `bsdthread_terminate`,
  `pthread_find_owner`, `pthread_get_thread_kwq`, `workq_setup_thread`,
  `workq_markfree_threadstack` — пустые заглушки.

Заглушки с сообщением (пока не реализованы): `bsdthread_create`, 11
`psynch_*`, `workq_handle_stack_events`, `workq_create_threadstack`,
`workq_destroy_threadstack`.

Отдельное открытие: **возвращаемое значение `bsdthread_register[_2]` — не код
ошибки, а битовая маска возможностей.** Если вернуть 0, libpthread считает
себя неинициализированным, и первый же `__pthread_workqueue_supported()`
делает `trap` со строкой `BUG IN LIBPTHREAD: libpthread has not been
initialized`. libpthread требует как минимум `0x4000001e`, а libdispatch —
ещё и бит поддержки kevent-workqueue (`Missing Kevent WORKQ support`), поэтому
сейчас маска — `0x7fffffff`; разбирать её по битам предстоит по мере того, как
станут известны определения `PTHREAD_FEATURE_*`.

После этого `launchd` ушёл дальше: trap в libpthread исчез, и следующая
остановка — уже в libdispatch:

```text
crossxnu: bsdthread_register2 pid 9 threadstart 0x10ddb1820 ...
crossxnu: user #UD rip=0x10b884d74 page_off=0xd74 insn=0f 0b 65 48 8b 04 25 ...
```

Это `__dispatch_root_queues_init_once.cold.3` в `libdispatch.dylib`
(смещение `0x32d74`) со строкой
`BUG IN LIBDISPATCH: Unable to limit cooperative pool size` — то есть
следующий шаг упирается в настройку cooperative pool, а значит в `workq_*`.

#### libdispatch: лимит cooperative pool и root queues

Следующая остановка была в libdispatch, и она оказалась дешёвой:
`__dispatch_root_queues_init_once` пишет в sysctl
`kern.wq_limit_cooperative_threads` значение `-1`. Обработчик в
`bsd/pthread/pthread_workqueue.c` возвращал `ENOTSUP`, если у процесса ещё нет
workqueue (`p->p_wqptr == NULL`, а его ставит только `workq_open`), и
libdispatch из-за этого делал `trap` со строкой
`BUG IN LIBDISPATCH: Unable to limit cooperative pool size`.

Под permissive обработчик теперь принимает `-1`/`0` и игнорирует запрос, если
workqueue нет (с записью в лог). После этого libdispatch пошёл дальше и упал на
следующей проверке:

```text
crossxnu: user #UD rip=0x101704d74 page_off=0xd74 insn=0f 0b 65 48 8b 04 25 ...
```

Это `__dispatch_root_queues_init_once.cold.2` (`libdispatch.dylib+0x32d57`),
строка `BUG IN LIBDISPATCH: Root queue initialization failed` — то есть
создание root queue'ов требует уже настоящих workqueue-потоков
(`bsdthread_create` + `workq_*`), а не заглушек.

#### Первый заход на `bsdthread_create` (откатан)

Механизм был собран из внутриядерных примитивов:

- `thread_create_immovable(current_task(), &th)` — поток и его `uthread`;
- `thread_set_wq_state64(th, &state)` — пользовательские `rip`/`rsp`/`rdi`/`rsi`/`rdx`
  (`_thread_start` в libsystem_pthread — обычная функция, аргументы приходят в
  регистрах: `rdi=func`, `rsi=funcarg`, `rdx=pthread`);
- `convert_thread_to_port_immovable()` + `ipc_port_copyout_send_pinned()` —
  порт, который libpthread получает как результат syscall'а, затем
  `thread_resume()`.

Но загрузка с этой версией упала **до** любого вызова из userland:

```text
panic(cpu 0 caller 0xffffff80007c9d2e):  initproc failed to start --
    exit reason namespace 2 subcode 0x4
```

То есть ломается `load_init_program()`, а не наш код, — значит в реализации
неверна одна из предпосылок (шаблон `thread_ro`, порядок «порт → resume»,
либо адрес `retval`: в таблице он `user_addr_t *`, хотя порт — 32-битный
`mach_port_name_t`). Правка откатана до честного `ENOTSUP` (код первой версии
остался в истории git), ядро снова грузится, `launchd` упирается в ту же
строку `Root queue initialization failed`.

Следующая попытка должна делаться по шагам, с проверкой после каждого:
сначала создать поток и **не** резюмировать его (посмотреть, что он появился в
`ps -M`), потом выставить состояние и проверить `thread_getstatus`, и только
потом отдавать порт и резюмировать.

#### `bsdthread_create`: что уже выяснено (проверено в QEMU)

Разбор шёл по трапам, которые libpthread делает в новом потоке. Каждый
следующий вызов убивал pid 1 (он создаёт потоки при старте), поэтому ядро
паниковало с `initproc failed to start` — это не поломка `load_init_program`,
а смерть pid 1.

Порядок открытий:

1. `BUG IN LIBPTHREAD: thread_set_tsd_base() wasn't called by the kernel` —
   ядро обязано вызвать `thread_set_tsd_base(th, pthread_t)`. Мало того,
   libpthread проверяет **флаг в `%r9`**: бит 28 (`0x10000000`) означает
   «ядро вызвало thread_set_tsd_base()». Бит 29
   (`PTHREAD_START_SUSPENDED`) должен остаться нулевым: с ним libpthread
   уходит в другую заглушку.
2. `BUG IN LIBPTHREAD: pthread_t was corrupted` — потому что в `%rdi`
   передавался `func`. `__pthread_start` — это `void __pthread_start(pthread_t)`,
   то есть **`rdi = pthread_t`**, а точку входа и аргумент libpthread берёт из
   самой структуры `_pthread` (`+0x90` — функция, `+0x98` — аргумент),
   и проверяет `self == *(uint64_t *)self ^ __pthread_ptr_munge_token`.
3. `BUG IN CLIENT OF LIBPTHREAD: Unable to allocate thread port, possible port
   leak` — следующая остановка: проверка `leal 0x1(%rax); cmpl $1; jbe` над
   полем `pthread+0xf8`, то есть там должен лежать валидный порт потока
   (не 0 и не -1). Мы отдаём порт через `*retval`; дальше нужно понять, кто и
   когда пишет его в `+0xf8` — сам kext или userland.

Итоговая рабочая последовательность (она и оставлена в коде как комментарий,
резюмируя):

```c
thread_create_immovable(current_task(), &th);
state.rip = proc_get_threadstart(p);
state.rsp = user_stack;
state.rdi = user_pthread;        /* pthread_t! */
state.r9  = 0x10000000;          /* «tsd base уже выставлен», без бита 29 */
thread_set_wq_state64(th, &state);
thread_set_tsd_base(th, user_pthread);
sright = convert_thread_to_port_immovable(th);
name = ipc_port_copyout_send_pinned(sright, get_task_ipcspace(current_task()));
thread_resume(th);
```

С этой последовательностью поток реально стартует и проходит три проверки
libpthread; упирается в четвёртую (порт в `pthread+0xf8`). Пока она не
разобрана, функция возвращает `ENOTSUP`, чтобы ядро грузилось, — иначе pid 1
умирает и система паникует.

#### `bsdthread_create` работает: создавать поток нужно приостановленным

Последняя проверка libpthread (`Unable to allocate thread port, possible port
leak` на поле `pthread+0xf8`) оказалась **гонкой**, а не отсутствующим
значением: `__pthread_start()` читает порт из структуры `_pthread` сразу после
`thread_selfid()`, а ядро резюмировало поток прямо в `bsdthread_create()` —
то есть до того, как `pthread_create()` в родителе успевал записать туда
отданный порт.

Теперь ядро собирает поток целиком (состояние с `rdi = pthread_t`,
`r9 = 0x10000000`, `thread_set_tsd_base`, порт через `*retval`), но оставляет
его **приостановленным** — запускает userland. После этого pid 1 выживает:

```text
crossxnu: bsdthread_create: suspended port=7939 threadstart=0x10a9ff820 stack=0x11d427000
crossxnu: bsdthread_create: suspended port=2563 ...
crossxnu: bsdthread_create: suspended port=2819 ...
crossxnu: bsdthread_create: suspended port=7427 ...
sh-3.2# /sbin/launchd.real; echo rc=$?
```

`launchd` по-прежнему упирается в `Root queue initialization failed`
(libdispatch), но обычный `pthread_create()` теперь работает.
#### Атрибуты `bsdthread_create` (что передаёт libpthread)

Все вызовы приходят с `flags = 0x90008ff`, `threadstart = _thread_start`,
`wqthread = _start_wqthread` (`threadstart - 0x14`):

```text
crossxnu: bsdthread_create: suspended port=7939 flags=0x90008ff
    threadstart=0x1074cc820 wqthread=0x1074cc80c stack=0x117c4a000
```

То есть «это workqueue-поток» кодируется не отдельным битом в `flags` —
решение о точке входа (`p_threadstart` против `p_wqthread`) нужно принимать по
битам workqueue-атрибутов внутри `flags` либо по `uthread->uu_workq_flags`.
Пара `threadstart`/`wqthread` теперь видна в логе на каждом создании потока,
что и нужно для следующего шага — запускать workqueue-потоки с `p_wqthread`.