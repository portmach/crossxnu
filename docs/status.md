# Статус сборки

> Обновлено: 2026-10-30. Всё, что здесь написано, проверялось на
> Arch Linux x86_64 в WSL2, clang 23.1.4, XNU `xnu-12377.121.6`.

## 1. Матрица

| Хост | Target | Конфигурация | Статус |
|:-----|:-------|:-------------|:-------|
| Arch Linux (WSL2), x86_64 | `x86_64-apple-macos26.5` | `RELEASE` | recovery-userland работает: `bash`, `uname`, `sw_vers`, `ls`, `ps`, `mount`, `sysctl` на HFS+ root; свежий HFS+ том на `/dev/md1` монтируется и пишется; launchd пока SIGILL; обычный root требует cryptex |
| Arch Linux, x86_64 | `x86_64-apple-macos26.5` | `DEVELOPMENT` | не проверялось |
| Arch Linux, x86_64 | arm64 | — | не поддерживается (нужен KDK/Tightbeam/SPTM) |
| macOS | любой | — | вне scope |

## 1.1. Security status

**Phase 1 — permissive.** TrustCache и CodeSignature не обеспечивают
security-модель macOS: подпись/доверие/entitlements не enforced. Это
осознанное решение, а не «пока не заметили». См. [`../SECURITY.md`](../SECURITY.md)
и [`security-policy.md`](security-policy.md).

Ядро уже линкуется и грузится, и выводит
`crossxnu: permissive code-signing profile enabled`. Runtime-проверка
enforcement (TrustCache, подпись, entitlements) ещё впереди: пока это
заявленный профиль, а не проверенная security-модель.

Патч `0007-security-permissive-profile.patch` уже добавляет
compile-time профиль `CROSSXNU_SECURITY_PERMISSIVE=1`:
`--security permissive` в `scripts/build.sh`. Он не проверен в загрузке,
но фиксирует политику в коде. Справочник флагов — [`security-flags.md`](security-flags.md).

## 2. Что уже проверено

### 2.1. Host-инструменты

- [x] `SETUP/config` (bison/flex, Linux ELF).
- [x] `SETUP/installfile`, `replacecontents`, `decomment`, `setsegname`.
- [x] `SETUP/kextsymboltool` (линкуется с `libhostcompat`).
- [x] `unifdef`/`decomment`/`install` шимы.
- [x] Apple MIG `migcom` + драйвер `mig` на Linux.
- [x] `availability.pl` из `AvailabilityVersions`.

### 2.2. MIG

Проверено на `osfmk/mach/mach_host.defs`:

```bash
build/mig/mig -cc toolchain/bin/clang \
    -DKERNEL_SERVER=1 -mach_msg2 -novouchers \
    -header mach_host.h -server mach_hostServer.c -user mach_hostUser.c \
    -I upstream/xnu/osfmk -I upstream/xnu/bsd \
    upstream/xnu/osfmk/mach/mach_host.defs
```

Генерируются `mach_host.h`, `mach_hostServer.c`, `mach_hostUser.c`
корректной структуры (с `MIG_STRNCPY_ZEROFILL`, `mach_msg2`).

### 2.3. Заголовки

- [x] `make exporthdrs` завершается.
- [x] `syscalls.master` → `sysproto.h` генерируется.
- [x] `sys/_symbol_aliasing.h` генерируется из `availability.pl`.
- [x] `libkern/version.h` генерируется.

### 2.4. Компиляция ядра

- [x] Компилируются `osfmk`, `bsd`, `iokit`, `libkern`, `pexpert`,
      `libsa`, `security`, включая сгенерированный DriverKit.
- [x] `RELEASE`/`x86_64` флаги совпадают с Apple-схемой (`-O2`, `-mkernel`,
      `-fapple-kext`, `-fno-rtti`, `-fno-exceptions`).
- [x] cctools-port `ld64` линкует `kernel`:
      `MH_EXECUTE`, `NOUNDEFS PIE`, `__TEXT=0xffffff8000200000`.
- [x] `kalloc`, kext scan, PRNG и `vm_map_store` проходят; полный лог —
      [`boot.md`](boot.md).
- [x] `kc-builder` всегда генерирует `__PRELINK_INFO`, даже для KC без
      kext'ов (патч `patches/kc-tools/`).
- [x] Встроенный platform-expert stub (0017), `pthread` KEC (0018) и
      `ml_wait_max_cpus` (0019) обойдены; ядро доходит до BSD init.
- [x] Guard для commpage-update (0020) и AES без corecrypto (0021):
      ядро печатает BSD banner, поднимает `lo0`/`gif0`/`stf0` и ждёт root device.
- [ ] Следующий блокер — root device: нужны storage/APFS kext'ы, см. §3.
- [ ] LTO выключен (`BUILD_LTO=0`); включить после проверки cctools LTO.

## 3. Блокеры линковки (по состоянию на 2026-10-29)

| # | Блокер | Что нужно | Риск для ABI |
|:--|:-------|:----------|:-------------|
| 1 | ~~`Still waiting for root device`~~ | закрыт: встроенный HFS+ + `memdev` дают root с ramdisk | — |
| 2 | launchd падает SIGILL | разобрать, какая инструкция/проверка; см. [`userland.md`](userland.md) | **высокий**: userland-граница |
| 3 | root смонтирован read-only | rw-mount HFS+ (md0 в RAM) + `/tmp`, `/private/var` | средний |
| 4 | System cryptex отсутствует | `libSystem`/shared cache лежат в cryptex; в asset'е только RIDIFF/BXDIFF-диффы к нему | **высокий**: без него обычный `launchd` не стартует |
| 4 | DriverKit ABI | `iig-port` генерирует; сравнить vtable/символы с Apple 26.5 | средний: DriverKit ABI |
| 5 | `libcc_kext` — shim, не реальный C++ runtime | собрать/подключить Apple-совместимый `libcc_kext` | средний |
| 6 | `__builtin_xnu_type_*` | fallback-патчи 0004/0005 | средний (hardening) |
| 7 | `libTightbeam` | только для arm64/новых платформ | нет для x86_64 |
## 4. Как воспроизвести текущее состояние

```bash
git clone --recurse-submodules https://github.com/portmach/crossxnu.git
cd crossxnu
./scripts/bootstrap.sh
./scripts/build.sh --arch x86_64 --config RELEASE --jobs "$(nproc)"
```

Ожидаемый результат на текущем этапе: DriverKit генерируется через
`iig-port`, все объекты компилируются, `libfirehose_kernel` и
`libcc_kext`-shim подставляются, cctools-port `ld64` линкует **корректный
Mach-O kernel**: `MH_EXECUTE`, `NOUNDEFS PIE`, `__TEXT` по адресу
`0xffffff8000200000`. Это ещё **не** успех phase 1: ядро не загружено,
symbol table/vtable не сверены с Apple. Критерий — загрузка и совпадающая
таблица символов.

## 5. Ближайшие шаги

1. Запустить recovery-`launchd` как pid 1 с записываемым `/private/var`
   (`md1` уже работает): `mkdir -p /private/var`, `mount -t hfs /dev/md1
   /private/var`, затем `exec /sbin/launchd`. Для этого `userland/init.c`
   должен готовить `/private/var` до `execve()`.
2. Разобрать SIGILL в recovery-`launchd` (userland уже выполняется, см.
   [`userland.md`](userland.md)).
3. Вынести правки ядра (pthread/AMFI guards, serial-шим, md1, дисковые ioctl,
   `__nochk_bcopy` в HFS+) в `patches/`.
4. Разобрать `RIDIFF10`/`BXDIFF50` — можно ли восстановить базу system cryptex
   из asset'а; без неё обычный userland не запустится.
5. Сравнить symbol table и DriverKit vtable с Apple-сборкой `xnu-12377.121.6`.
6. Собрать полноценный `libcc_kext` вместо shim; вернуть LTO.
7. Повторить для `DEVELOPMENT`, затем для `arm64`.

## 6. Журнал

| Дата | Событие |
|:-----|:--------|
| 2026-10-29 | Зафиксирован `xnu-12377.121.6`; собран MIG; `make exporthdrs` проходит; начата компиляция объектов |
| 2026-10-29 | Добавлены fallback'и для Apple builtins; исключён DriverKit; собираются `osfmk`/`bsd`/`iokit` объекты |
| 2026-10-29 | Открыты блокеры: `libfirehose_kernel`, `libcc_kext`, `ld64.lld -static` |
| 2026-10-29 | DriverKit сгенерирован `iig-port`; aliases/`libcc_kext` закрыты; `ld64.lld` дал `DYLDLINK`/нулевой base |
| 2026-10-29 | cctools-port `ld64` 956.6: `kernel` — `MH_EXECUTE NOUNDEFS PIE`, `__TEXT=0xffffff8000200000`; LTO пока off |
| 2026-10-29 | UEFI xnu-loader: kernel стартует в QEMU (Skylake-Client); исправлены TSC/SSE/bare-KC; дальше divide в `kalloc_type_distribute_budget` |
| 2026-10-30 | kalloc проходит; `__PRELINK_INFO` генерируется всегда; `read_random` и `vm_map_store` получили fallback без corecrypto KEC |
| 2026-10-30 | Ядро доходит до `IOPlatformExpert`; panic: `Unable to find driver for this platform: "ACPI"` — нужен platform expert kext |
| 2026-10-30 | Встроенный platform-expert stub: IOKit стартует; дальше `pthread` KEC и `ml_wait_max_cpus`; ядро доходит до BSD init |
| 2026-10-30 | Новый блокер: `commpage_update_mach_approximate_time` пишет по невалидному commpage до `commpage_init` |
| 2026-10-30 | commpage и AES обойдены; ядро дошло до BSD init, подняло сеть и ждёт root device |
| 2026-10-30 | HFS+ в ядре; recovery-root монтируется, `launchd` печатает Darwin Ignition Sequence и упирается в `ignition blob not available` |
| 2026-10-30 | `payloadv2` разобран: pbzx вырезал поток на 8 МиБ, а не «multi-segment»; полная распаковка даёт 53 независимых Apple Archive |
| 2026-10-30 | Обычный system root собран (19 GB, 179 712 файлов) без macOS-тулинга: `scripts/aa.py` + `scripts/extract-payloadv2.py` |
| 2026-10-30 | Найден блокер обычного userland: `/usr/lib/libSystem.B.dylib` и dyld shared cache живут в системном cryptex, а в asset'е только RIDIFF/BXDIFF-диффы |
| 2026-10-30 | Ignition обойдён патчем recovery-dyld (`_ignite` → `ret 0`); dyld грузит launchd и ~50 образов |
| 2026-10-30 | Закрыты два NULL-разыменования ядра: `pthread_functions` в 16 shim'ах и `amfi` в entitlement-функциях |
| 2026-10-30 | **Userland выполняется**: `cat`/`sh`/скрипт запускаются и завершаются с кодом; launchd падает в SIGILL. Блокер — `/dev/console` (km-драйвер) |
| 2026-10-30 | Консоль починена (serial-шим в `cons.c`); статический init (`userland/init.c`) поднимает `bash` |
| 2026-10-30 | **Работает macOS userland**: `uname`, `sw_vers` (26.7.2/25G332), `ls`, `ps`, `mount`, `sysctl`, `cat` на HFS+ root; корень пока read-only |
| 2026-10-30 | Корень монтируется rw, но том заполнен на 100% (`freeBlocks = 0`) → `ENOSPC`; добавлен scratch-том `md1` (256 MB) |
| 2026-10-30 | `newfs_hfs` на `md1` работает после дисковых ioctl в `memdev`; монтирование свежего тома падает в `cat_create` |
| 2026-10-30 | Причина трапа при mount свежего тома: `_FORTIFY_SOURCE_STRICT` проверяет `bcopy()` по размеру поля (`userInfo` = 16), clang сворачивал её в `ud2`; 4 копии Finder Info переведены на `__nochk_bcopy()` |
| 2026-10-30 | **HFS+ пишется**: свежий том монтируется, `mkdir -p`, запись/чтение файла и `df` работают (`/dev/md1 on /private/var (hfs, local)`) || 2026-10-30 | `launchd` с записываемым `/var`: убраны `security-critical blob` и `Text page corruption` (permissive: не enforced launch constraints и cdhash текстовых страниц), SIGILL остался настоящим `#UD` || 2026-10-30 | SIGILL в `launchd` опознан: `__pthread_workqueue_supported` в libsystem_pthread делает `trap` со строкой `BUG IN LIBPTHREAD: libpthread has not been initialized` — не хватает `com.apple.kec.pthread` || 2026-10-30 | Встроенная таблица `pthread_functions` вместо kext'а: `launchd` прошёл trap «libpthread has not been initialized» (маска возможностей в `bsdthread_register`), упёрся в libdispatch (`Unable to limit cooperative pool size`) || 2026-10-30 | libdispatch прошёл `wq_limit_cooperative_threads` (permissive: запрос игнорируется без workqueue) и упёрся в `Root queue initialization failed` — нужны настоящие workqueue-потоки || 2026-10-30 | Первый заход на `bsdthread_create` (`thread_create_immovable` + `thread_set_wq_state64` + порт) ломал `load_init_program` — откатан до `ENOTSUP`; нужен поэтапный разбор || 2026-10-30 | `bsdthread_create` проверен по шагам: поток создаётся, состояние (`rip/rsp/rdi/rsi/rdx`) читается обратно, порт отдаётся; новый поток сразу ловит trap в libpthread, из-за чего pid 1 умирает || 2026-10-30 | `bsdthread_create` разобран по трапам libpthread: нужен `rdi = pthread_t`, `r9 = 0x10000000`, `thread_set_tsd_base`; дальше упор в поле порта `pthread+0xf8` || 2026-10-30 | `bsdthread_create` заработал (поток создаётся приостановленным, порт отдаётся через retval) — pid 1 переживает создание потоков || 2026-10-30 | Сняты атрибуты `bsdthread_create`: `flags=0x90008ff`, `wqthread = threadstart-0x14`; для workqueue-потоков нужна отдельная точка входа || 2026-10-30 | `workq_create_threadstack` выделяет настоящий стек через `vm_allocate`; libdispatch падает раньше, чем этот путь вызывается || 2026-10-30 | `P_LREGISTER` включает `workq_open`; root queues libdispatch инициализируются, `workq_create_threadstack` вызывается; дальше ядро падает в `__builtin_unreachable()` после `workq_setup_thread` || 2026-10-30 | `workq_setup_thread` реализован (`thread_exception_return`); workqueue-поток доходит до userland, ядро не падает, launchd упирается только в «не pid 1» || 2026-10-30 | `rc.launchd` + init: launchd запускается как pid 1, но сам печатает «cannot be run directly» и выходит — нужен признак «запущен ядром как init» |
| 2026-10-30 | Причина «cannot be run directly» найдена в бинаре: первая инструкция main() (LC_MAIN entryoff 0x16598) — это if (isatty(STDOUT_FILENO)) → отказ, затем if (getpid() != 1). Ядро подаёт pid 1 без файловых дескрипторов, поэтому isatty(1) даёт EBADF; наш init отдавал /dev/console. |
| 2026-10-30 | 
c.launchd запускает launchd с </dev/null >/dev/null (stderr остаётся на консоли): **launchd стартует как pid 1**, регистрирует pthread-ABI, создаёт поток и workqueue-поток. |
| 2026-10-30 | Разобран ABI workqueue-потока по исходникам libpthread (_pthread_wqthread(self, kport, stacklowaddr, keventlist, flags, nkevents)): 
di=self, 
si=kport, 
dx=stacklowaddr, 
cx=eventlist, 
8=flags|WQ_FLAG_THREAD_TSD_BASE_SET, 
9=nkevents; 

| 2026-10-30 | Причина «cannot be run directly» найдена в бинаре: первая инструкция `main()` (`LC_MAIN entryoff 0x16598`) — это `if (isatty(STDOUT_FILENO))` → отказ, затем `if (getpid() != 1)`. Ядро подаёт pid 1 без файловых дескрипторов, поэтому `isatty(1)` даёт `EBADF`; наш init отдавал `/dev/console`. |
| 2026-10-30 | `rc.launchd` запускает launchd с `</dev/null >/dev/null` (stderr остаётся на консоли): **launchd стартует как pid 1**, регистрирует pthread-ABI, создаёт поток и workqueue-поток. |
| 2026-10-30 | Разобран ABI workqueue-потока по исходникам libpthread (`_pthread_wqthread(self, kport, stacklowaddr, keventlist, flags, nkevents)`): `rdi=self`, `rsi=kport`, `rdx=stacklowaddr`, `rcx=eventlist`, `r8=flags|WQ_FLAG_THREAD_TSD_BASE_SET`, `r9=nkevents`; `rsp=self=stackaddr`; стек = `[guard page][stack][pthread-struct]`. Первая версия давала `rsp` = низ стека → SIGBUS на `_start_wqthread`. |
| 2026-10-30 | С правильным ABI workqueue-поток **выполняет userland** и возвращается в ядро через `__workq_kernreturn`; дальше упор в `workq_handle_stack_events`. Временная реализация (снять привязку к kqworkloop, `return 0`) убирает панику, но workloop крутится вхолостую: события не доставляются. |
| 2026-10-30 | Следующий шаг: протокол `kevent_workq_internal(KEVENT_FLAG_STACK_DATA|IMMEDIATE[|PARKING])` — kext кладёт на стек `[data buffer][data avail][nevents][pthread_self]` и kqid перед `eventlist`; см. комментарий в `bsd/kern/kern_event.c`. |
| 2026-10-30 | Реализован kevent-протокол workqueue: `kevent_workq_internal(STACK_DATA|IMMEDIATE[|PARKING])` в обе стороны, scratch-область на стеке (`[data 32K][kqid][events]`), `workq_handle_stack_events` паркует поток. Найдены и исправлены: `pthsize` (0x2000) приходит в поле `flags` вызова `bsdthread_register`, TSD-база = `pthread + 224` (`offsetof(struct pthread_s, tsd)`). |
| 2026-10-30 | **launchd работает как pid 1**: печатает `hello, launchd UUID: ...`, `Darwin Bootstrapper Version 7.0.0`, `System Integrity Protection is engaged`, входит в ondemand mode, создаёт system domain и запускает boot-задачи (`exclaves-boot`, `mount-phase-1`). |
| 2026-10-30 | Следующие блокеры: (1) `setiopolicy_np` не реализован → `assertion failed: launchd.real + 60817: 0xffffffffffffffff` в `update_thread`; (2) главный поток умирает в `__pthread_terminate` с намеренным `ud1` (`PTHREAD_INTERNAL_CRASH`) → `panic: initproc exited` (SIGILL). |
| 2026-10-30 | Причина падения pid 1 найдена по исходникам libpthread: `_pthread_terminate()` заканчивается `__bsdthread_terminate(...)`, а сразу за ним `PTHREAD_INTERNAL_CRASH(t, "thread didn't terminate")`. Наш шим `bsdthread_terminate` был пустышкой и возвращал 0. |
| 2026-10-30 | `bsdthread_terminate` реализован: освобождение пользовательского стека (`vm_deallocate`) + `thread_terminate_self()`. **launchd больше не падает**: проходит все boot-задачи (включая `mount-phase-1`/`mount-phase-2`), запускает `dirs_cleaner` и печатает `launchd logging initialized. name: com.apple.xpc.launchd pid: 1`. |
| 2026-10-30 | Обязательный boot-таск `dirs_cleaner` отсутствовал в ramdisk → launchd сам объявлял `Panicking in 3 seconds`. Скопирован `/usr/libexec/dirs_cleaner` из полного macOS-рута (`~/aa/root`); остальные отсутствующие boot-таски — optional. |
| 2026-10-30 | Созданы `/private/var/{log,db,run}/com.apple.xpc.launchd` и `/private/var/boot`; `launchd.log` — симлинк на `/dev/console`. Тестовый `com.crossxnu.hello` (RunAtLoad, вывод на консоль) пока не запускается. |
| 2026-10-30 | launchd стабилен (4 загрузки, паники нет), но после `launchd logging initialized` замолкает — похоже, блокируется. Главные подозреваемые: заглушки `psynch_*` (ENOTSUP) в мьютексах libpthread/libdispatch и незакрытый `setiopolicy_np`. |
