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

1. **[сделано]** Запустить `launchd` как pid 1 с записываемым `/private/var`:
   `userland/rc.launchd` готовит каталоги и `exec`-ит `/sbin/launchd.real`.
   `launchd` проходит все boot tasks (mount-phase-1/2, data-protection,
   keystore-init, fips, dirs_cleaner, …) и печатает
   `launchd logging initialized. name: com.apple.xpc.launchd pid: 1`.
2. **[сделано]** SIGILL в `launchd` разобран — это были два бага нашего
   pthread-kext-замещения, а не `launchd` (см. §7).
3. **[сделано]** Правки ядра вынесены в `patches/` (серия 0001–0028).
4. **[следующее]** Понять, почему после `logging initialized` процесс стоит на
   трёх потоках без работы (см. §7): подозреваются работа kevent/workloop и
   слишком быстрые таймеры (гостевые часы идут кратно быстрее реального
   времени, а workqueue убивает «простаивающие» потоки по таймеру).
5. Разобрать `RIDIFF10`/`BXDIFF50` — можно ли восстановить базу system cryptex
   из asset'а; без неё обычный userland не запустится.
6. Сравнить symbol table и DriverKit vtable с Apple-сборкой `xnu-12377.121.6`.
7. Собрать полноценный `libcc_kext` вместо shim; вернуть LTO.
8. Повторить для `DEVELOPMENT`, затем для `arm64`.

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

## 7. Зависание после `launchd logging initialized` (2026-10-30)

Расследование шло с временной диагностикой из `0028-bringup-tracing.patch`:
трассировка каждого syscall/mach-trap pid 1 с tid и user-RIP, трассировка
открываемых путей, а также сторожевой `thread_call`, который через 15 с после
каждого завершения потока печатает состояние планировщика всех потоков pid 1
(`cont=` — ядровая continuation, `ev=` — wait event, `sys=/` — счётчики
syscall/mach-trap, `cs=` — переключения контекста) и состояние workqueue
(`nthreads`, `idle`, `req`, `dying`, `creator`, пустоту трёх списков).

### Что было сломано и исправлено

1. **Двойной `workq_thread_terminate()`.** `bsdthread_terminate()` в
   `pthread_shims.c` сам вызывает `workq_thread_terminate()` для
   `THREAD_TAG_WORKQUEUE` **до** того, как передать управление таблице
   `pthread_functions`. Наш шим вызывал функцию ещё раз → `TAILQ_REMOVE()` по
   уже отвязанному uthread → `ud1` (assert-trap) внутри
   `workq_thread_terminate` (`panic: Kernel trap type 6=invalid opcode`,
   `RIP=workq_thread_terminate+0x138`). Исправление: шим не трогает workqueue
   bookkeeping, только освобождает стек и завершает поток.
2. **Потоки `pthread_create()` никогда не запускались.** `bsdthread_create`
   создавал поток и оставлял его suspended в расчёте на `thread_resume()` из
   libpthread. libpthread его не вызывает (в трассировке нет ни одного
   `thread_resume`). В дампе это выглядело так: `tid=183 tag=0x0 state=0x9
   cont=thread_bootstrap_return sys=0/0 cs=0` — поток создан и не разу не
   планировался. Исправление: ядро само делает `copyout` имени thread-порта в
   `struct pthread_s` по смещению `0xf8` (это проверка `__pthread_start`:
   `movl 0xf8(%rbx),%eax; leal 1(%rax),%ecx; cmpl $1,%ecx; jbe <trap>`
   «Unable to allocate thread port, possible port leak»), ставит
   `THREAD_TAG_PTHREAD` и вызывает `thread_resume()`.

### Где именно стоит процесс сейчас

После обоих исправлений загрузка доходит до конца boot-задач, а затем:

* главный поток (`tag=0x1`) завершается — это **нормально**: в
  `libdispatch.dylib` `dispatch_main()` в конце делает `pthread_exit(NULL)`
  (проверено дизассемблером: `_dispatch_main` → `_dispatch_main_queue_drain`
  → `__dispatch_program_is_probably_callback_driven=1` → `_pthread_exit`),
  после чего очередь main обслуживается workqueue-потоками;
* в процессе остаются 3 потока, все в ожидании:
  `tid=184 tag=0x30 state=0x1 cont=workq_unpark_continue` (парковка wq),
  `tid=186 tag=0x30 state=0x41 cont=filt_wlwait_continue ev=<kqueue>` (workloop
  ждёт события), `tid=187 tag=0x10 state=0x1 cont=__sleep_continue`
  (sigsuspend — штатный поток обработки сигналов launchd);
* workqueue: `nthreads=2 idle=1 req=0 dying=0` — новых запросов нет;
* QEMU: после ~2 минут CPU-время перестаёт расти (процесс заблокирован, не
  крутится вхолостую);
* launchd больше не открывает ни одного файла: `path`-трассировка показывает
  только `/System/Library/LaunchDaemons/com.apple.jetsamproperties.*.plist`, а
  `/Library/LaunchDaemons/com.crossxnu.hello.plist` не открывается — то есть
  до сканирования job-базы дело не доходит.

Значит, либо в очередь main не попадает работа (тогда нужен разбор
libdispatch-стороны), либо работа есть, но kevent/workloop не будит поток.
Косвенный аргумент в пользу второй версии: гостевые часы идут кратно быстрее
реального времени (`launchd` печатает 45 минут через несколько секунд после
старта), а workqueue убивает «простаивающие» потоки по таймеру — при кривом
timebase это происходит слишком рано, и пробуждение может теряться.
Следующий шаг — проверить и починить пересчёт TSC→timebase
(`osfmk/i386/tsc.c`, `patch 0011`), затем повторить прогон.

### Часы гостя (TSC→timebase), 2026-10-30

Отдельная находка по пути: `launchd` печатал время `1970-01-01 01:17:35` при
загрузке, занимавшей ~2 минуты, то есть гостевые часы шли в десятки раз
быстрее реального времени. Причина: под QEMU/TCG CPUID.0x15 не даёт
работоспособной пары N/M (а `MSR_PLATFORM_INFO` — flex ratio), и `tsc_init()`
уходил в fallback `tscFreq = FSBFrequency` = 100 МГц, тогда как реальный TSC в
эмуляции ~3.8 ГГц. Наш UEFI-loader уже измеряет TSC по firmware-таймеру
(`estimate_tsc_frequency()`, `BS->Stall`) и публикует `TSCFrequency` в device
tree — теперь `tsc_init()` предпочитает это значение (patch 0011).
После правки время в логе стало совпадать с реальным (`00:02:10` вместо
`01:17:35` на том же этапе загрузки).

На само зависание это не повлияло: финальное состояние то же (3 потока,
`req=0`, все в ожидании), но правильные часы убирают целый класс ложных
таймаутов и делают дальнейшую диагностику осмысленной.
| 2026-10-30 | Разобран `panic` `ud1` в `workq_thread_terminate`: наш `bsdthread_terminate` вызывал `workq_thread_terminate()` второй раз (XNU вызывает его сам до передачи в таблицу kext-функций) → `TAILQ_REMOVE()` по уже отвязанному uthread. Двойной вызов убран. |
| 2026-10-30 | Найдено, что потоки `pthread_create()` вообще не запускались: `cont=thread_bootstrap_return sys=0/0 cs=0`. libpthread не вызывает `thread_resume()`; теперь ядро само пишет имя порта в `struct pthread_s+0xf8` (`copyout`) и вызывает `thread_resume()`. |
| 2026-10-30 | Сторожевой дамп планировщика показал: после `logging initialized` главный поток завершается **штатно** (`dispatch_main()` → `pthread_exit`), остаются 3 потока в ожидании и `req=0` у workqueue; процесс блокируется, а не крутится (CPU-время QEMU перестаёт расти). |
| 2026-10-30 | Исправлены гостевые часы: `tsc_init()` теперь берёт `TSCFrequency` из device tree (loader мерил TSC по `BS->Stall`); было ~35× быстрее реального времени. |
| 2026-10-30 | Патч-серия переразбита: `0024` (pthread) и новый `0028-bringup-tracing` (диагностика); `0011` дополнен TSC-частотой из DT. Проверено: `apply-patches.sh` (26 патчей) воспроизводит дерево байт в байт. |

### Что говорит исходник libdispatch (проверено по `upstream/libdispatch`)

* `_dispatch_main_queue_drain()` (src/queue.c) требует, чтобы очередь main
  дренировал **главный поток**: `_dispatch_queue_is_thread_bound(dq)` и
  `_dq_state_drain_locked_by_self(dq_state)`, иначе — `DISPATCH_CLIENT_CRASH`
  («… called after dispatch_main()» / «from the wrong thread»).
* Но в `_dispatch_runloop_queue_wakeup()` есть ветка под `DISPATCH_WAKEUP_MAKE_DIRTY`
  (rdar://81886582): если главный поток уже **отпустил drain-lock** (то есть
  вышел из `dispatch_main`), постановка работы уходит в обычный
  `_dispatch_lane_wakeup()`, и очередь дренит **workqueue-поток**.
  Наблюдение это подтверждает: после выхода главного потока boot-задачи
  продолжали печататься с `tid=185/186/…` (workqueue-потоки).

Следствие: механизм «очередь main обслуживается wq-потоками» у нас работает.
В момент остановки ядро не видит **ни одного** syscall pid 1 (`kevent_qos`,
`workq_kernreturn`, `ulock_wake` — ни одного), то есть libdispatch не просил
поток. Значит, либо в очереди действительно пусто, либо событие потерялось
внутри kevent/workloop до постановки запроса — это и надо проверять
следующим шагом (дамп количества pending-событий kqueue/workloop процесса
из сторожевого таймера).

### Проверка «отложенного продолжения» (вариант 2), 2026-10-30

Гипотеза: после `logging initialized` launchd ждёт срабатывания таймера
(`EVFILT_TIMER` в workloop, как это делают `dispatch_after`/`dispatch_source`
таймеры), а таймеры не доставляются.

Инструментировал `filt_timerarm()`/`filt_timerexpire()` в
`bsd/kern/kern_event.c` (печать первых 20 arm/expire для pid 1).
Результат прогона: **0 arm и 0 expire за 200 с**. То есть launchd вообще не
пользуется kqueue-таймерами — гипотеза закрыта, инструментация откачена.

Дополнительно по дизассемблеру `launchd.real` пройден весь хвост `main()`:
после `launchd_log_init()` идут boot-таски `xpcroleaccountd`, `init_featureflags`,
`EndpointSecurity`, `rc.server`, `tzinit`, `dirhelper`, `rootless-init`,
`finish-demo-restore`, вызов `0x10004d8e4`, `systemstats`, `prng_seedctl`,
создание `/var/run/utmpx`. Ни один из них не появляется в логе и не даёт
syscall'ов, то есть последовательность останавливается на **первом же** таске
после `log_init`.

Остаются две версии, обе требуют проверки состояния libdispatch:

1. Постановка в очередь main вязнет в poke-пути: в
   `_dispatch_runloop_queue_wakeup()` при `DISPATCH_WAKEUP_MAKE_DIRTY` и
   выставленном drain-lock выполняется `_dispatch_runloop_queue_poke()` —
   отправка в runloop-порт (mach-порт main-очереди). Если получателя уже нет
   (главный поток вышел), сообщение просто лежит в порту, а очередь не дренится.
2. Запись работы в очередь была, но её не разбудили (потерянное пробуждение
   в workqueue); тогда `req` был бы больше нуля, а он 0 — версия слабее.

Следующий шаг: трассировать в ядре `mach_msg2_trap`/`ipc_kmsg` для pid 1 в
момент остановки (кому и куда шлётся сообщение, есть ли у порта получатель),
и/или прочитать из сторожевого таймера `__dispatch_main_q` (`dq_state`,
`dq_items_tail`) через `copyin`, найдя базу libdispatch в адресном
пространстве launchd.

### Death-путь workqueue: поток на idlelist, но TH_RUN (2026-10-30)

Гипотеза «ядро убивает поток, который уже разбужен для работы» проверена
диагностикой в `workq_unpark_for_death_and_unlock()` (печать состояния
машино-потока, списка, в котором лежит uthread, и счётчиков wq):

```
crossxnu: wq death: pid=1 tid=186 state=0x4 list=idlelist first_use=0
         flags=0x4 nthreads=3 idle=2 df=0x1 sf=0x0
crossxnu: wq death: pid=1 tid=185 state=0x4 list=idlelist ...
```

`state=0x4` — это `TH_RUN`, то есть поток уже разбужен (планируется), но всё
ещё учитывается в `wq_thidlelist`. Death-политика снимает его оттуда и
отправляет `EXIT_THREAD` (`sf=0x0`, `df=0x1 = WORKQ_UNPARK_FOR_DEATH_WAS_IDLE`),
то есть работа потока выбрасывается: libpthread завершает поток вместо того,
чтобы выполнить событие workloop.

Наивная правка «не убивать поток в `TH_RUN`, а вернуть его в userspace с пустым
списком событий» приводит к панике (page fault по `NULL+0x1a` в
`bsdthread_terminate` → death-путь), поэтому она откачена. Правильное место
исправления — учёт списков: поток, которому шим отдаёт события
(`workq_setup_thread`/`workq_handle_stack_events`), не должен оставаться в
`wq_thidlelist`; его нужно вынимать оттуда (аналог `workq_pop_idle_thread`)
при арминге событий, иначе death-таймер имеет право его «собрать».

### Планировщик здоров, «зависание» — это простой launchd (2026-10-31)

В дерево добавлена диагностика планировщика: кольцевой буфер последних
решений (патч `0028`, `osfmk/kern/sched_prim.c`), который пишется в
`thread_setrun`/`processor_setrun`/`thread_select`/`thread_invoke`/
`processor_idle`/`thread_dispatch`, а разбирается сторожевым таймером
(`crossxnu_sched_dump`) — только слова в горячем пути, никакого `printf`.

Что показал один прогон (`build/serial-mon1.log`, 200 с, монитор QEMU
подключён):

```
crossxnu: sched ring (watchdog), цикл в простое:
  psetrun  tid=103 a=95 b=0 c=5 d=1024   # pri 95, preempt=AST_PREEMPT|URGENT,
                                         # state=IDLE(4), action=eExitIdle(0)
  setrun   tid=103 a=95 b=5 c=1 d=4      # очередь стала 1
  idlebrk  tid=8   a=1  b=0 c=5          # idle-петля вышла, runq=1
  select   tid=102 a=0  b=0 c=1 d=5      # выбирает idle-поток
  selout   tid=103                          # выбрал 103
  invoke   tid=102 a=103                    # переключение idle -> 103
  select   tid=103 a=0 b=95 c=0 d=6         # 103 сразу блокируется
  invoke   tid=103 a=102                    # обратно в idle
```

То есть цикл «проснулись → отработали → заблокировались → ушли в idle»
повторяется штатно, очередь пустеет, `processor->state` меняется
`IDLE(4) → DISPATCHING(5) → RUNNING(6)`. Никаких «осиротевших» потоков в
`TH_RUN` вне очереди в этом прогоне нет.

Прежнее чтение `runq=0` как «счётчик пуст» было **неверным**: планировщик в
этой сборке — `sched_dualq` (символ `sched_dualq_choose_thread`), у него
главная очередь — это `pset->pset_runq`, а `processor->runq` — только очередь
bound-потоков; `thread->__runq.runq` хранит указатель на *процессор*, а не
счётчик. Улик «поток в очереди, а очередь пуста» не существует.

Монитор QEMU в момент простоя (`info registers`):

```
RIP=ffffff8000441137  _machine_idle+0x1c7
RFL=00000297 [--S-APC] CPL=0 II=0 HLT=1     # IF=1 (0x200), CPU в hlt
LAPIC: ISR/IRR пусты, TPR/PPR=0
```

`pal_hlt()` — это `sti; hlt`, то есть процессор спит с **включёнными**
прерываниями и просыпается на каждый таймер: сторожевой таймер (15 с)
продолжал печатать дампы вплоть до конца прогона. Значит это не «мертвый»
процессор и не потерянное прерывание, а настоящее состояние простоя.

Состояние launchd в этот момент (`crossxnu: threads(watchdog)`, все потоки
`TH_WAIT`):

```
tid=184 cont=filt_wlwait_continue   # ожидание workloop (kevent_id, filt_wlwait)
tid=185 cont=workq_unpark_continue  # workqueue-поток припаркован
tid=186 cont=workq_unpark_continue  # workqueue-поток припаркован
tid=188 cont=_sleep_continue        # msleep
```

Последний системный вызов pid 1 — `workq_kernreturn` (368), т.е. парковка
workqueue-потока. Главная очередь libdispatch прочитана из ядра и разобрана
по фактической раскладке `struct dispatch_queue_static_s` (сверено с
`upstream/libdispatch/src/queue_internal.h` и с `llvm-nm` по
`build/dis/libdispatch.dylib`; `__dispatch_main_q` = vmaddr `0x5fe40`,
`__dispatch_mgr_q` = `0x5fec0`):

```
+0x00 isa        _OBJC_CLASS_$_OS_dispatch_queue_main
+0x18 do_targetq -> 0x60440 (статическая root-очередь)
+0x30 dq_items_tail = 0
+0x38 dq_state      = 0x001ffe1000000000   # drain owner = 0 (не захвачен),
                                           # DIRTY (бит 39) = 0
+0x40 dq_serialnum  = 1
+0x48 dq_label      -> "com.apple.main-thread"
+0x78 dq_items_head = 0
```

То есть главная очередь **пуста и не захвачена** никаким drainer'ом: работы
в libdispatch нет.

Наконец, полный список boot-task'ов из лога заканчивается так:

```
(dirs_cleaner) <Notice>: Doing boot task
(dirs_cleaner-usr) <Notice>: Skipping boot-task
<Notice>: launchd logging initialized. name: com.apple.xpc.launchd pid: 1
```

`dirs_cleaner-usr` пропускается штатно (предикат `0x100046d93` в
`launchd.real` сверяет флаги `PerformAlways`/`PerformAfterUserspaceReboot`/
`PerformInRestore` в boot-task словаре). После этого launchd **закончил
список boot-task'ов** и ушёл в простой: новых процессов не появляется,
системных вызовов нет, главная очередь пуста.

**Вывод.** Наблюдаемая «остановка после `logging initialized`» — не дефект
планировщика, не потерянное прерывание и не залипший drain главной очереди:
ядро отдаёт простой корректно, а launchd нечего делать. Дальнейшее
продвижение требует не правок ядра, а конфигурации userland: в ramdisk нет
описания задач/сервисов, которые launchd должен запускать (`launchd.plist`
в образе — системный plist, а не словарь задач), поэтому после boot-task'ов
запускать нечего.

Следующий шаг (userland, не ядро): положить в образ корректный
`/System/Library/xpc/launchd.plist` (словарь boot-task'ов и/или задания),
либо отдельный job (`com.apple.DarwinBootstrapper`/тестовая программа),
и убедиться, что launchd его порождает; это же даст проверку `posix_spawn`
и `execve` «в бою».

Что уже видно про задания (проверено по содержимому образа):

* `/System/Library/LaunchDaemons` — 6 recovery-заданий (`syslogd`,
  `ReportCrash.Root`, `diskimagesiod`, `ramrod`, ...);
* `/Library/LaunchDaemons/com.crossxnu.hello.plist` — тестовое задание
  (`/bin/sh -c echo ...`, `RunAtLoad`, вывод в `/dev/console`);
* ни одно из них launchd не запустил и даже не открыл каталог
  `/System/Library/LaunchDaemons` (в трассировке путей pid 1 он не
  встречается, кроме чтения `jetsamproperties.*.plist`);
* `/System/Library/xpc/launchd.plist` в образе — это системный plist macOS 26
  (`LaunchDaemons`/`Symlinks`/`SystemLibraryTreeState`), а не словарь
  boot-task'ов, поэтому он задания не описывает.

Кроме того, баннер в логе показывает, что `/sbin/launchd.real` из этого
ramdisk — это именно «Darwin Bootstrapper ... root:libxpc_executables-.../
launchd/RELEASE_X86_64», то есть загрузчик инсталлятора, а не системный
launchd с полным набором доменов. Поэтому ожидать от него загрузки
`/Library/LaunchDaemons` нельзя: следующий шаг — либо дать ему тот конфиг,
который он ищет (boot-task'и/задания recovery-режима), либо перейти на
полноценный системный launchd с настоящим userland-деревом.

Экспериментальная правка «никогда не собирать idle-потоки workqueue»
(`workq_death_call_schedule()`) откачена: она больше не нужна, поведение
вернулось к стоковому (перепроверено загрузкой — финальное состояние то же
самое, `hlt` в `machine_idle`, boot-task'и завершены).

### Почему launchd ничего не запускает: он не читает каталоги заданий

Трассировка путей pid 1 сделана полной (без лимита в 800 записей, с именами
вызовов), прогон `build/serial-mon3.log`: 4587 открытий/статов.

`posix_spawn` за весь запуск (то есть спавн/exec/reap в ядре работают):

```
/sbin/mount
/usr/libexec/init_data_protection
/usr/libexec/cc_fips_test
/usr/libexec/dirs_cleaner
/usr/libexec/MobileAssetEarlyBootTask
/usr/sbin/BootCacheControl
/usr/libexec/rc.temporaryDataVolume
/private/var/install/deferred_install
/usr/libexec/applekeystored
```

А вот **каталоги заданий launchd не открывает вообще** — ни
`/System/Library/LaunchDaemons`, ни `/Library/LaunchDaemons`,
ни `/System/Library/LaunchAgents`, ни `/Library/LaunchAgents`
(в трассе нет ни одного `open` на эти пути; из
`/System/Library/LaunchDaemons` читаются только два файла
`com.apple.jetsamproperties.*.plist`, то есть как данные лимитов памяти).

Зато он пытается прочитать ровно такой набор конфигурации:

```
/etc/rc.launchd
/System/Library/CoreServices/SystemVersion.plist
/System/Library/CoreServices/SystemVersionCompat.plist
/private/etc/com.apple.xpc.launchd.limits.plist
/private/var/db/com.apple.xpc.launchd/config/system.plist
/private/var/db/com.apple.xpc.launchd/config/user.plist
/System/Library/Sandbox/com.apple.xpc.launchd.rootless.plist
/System/Volumes/Preboot/<uuid>/.roots-installed
/System/Volumes/iSCPreboot/<uuid>/.roots-installed
```

плюс создаёт `/private/var/log/com.apple.xpc.launchd` и пишет
`launchd.log`. Файлов `config/system.plist` и `config/user.plist` в образе
нет — то есть пользовательской конфигурации заданий тоже нет.

Список boot-task'ов при этом **вкомпилирован в бинарь**: строки
`mount-phase-1`, `dirs_cleaner-usr` и т.п. есть в `launchd.real`
(проверено поиском по бинарю), а «optional boot task not present» — это
проверка наличия helper'а на диске. Список заканчивается на
`dirs_cleaner-usr`, после чего загрузчику делать нечего.

Итог: recovery-`launchd` — это bootstrapper с вкомпилированным списком
задач; он принципиально не сканирует каталоги заданий, поэтому положить
`/Library/LaunchDaemons/com.crossxnu.hello.plist` (или что угодно ещё) и
ждать спавна бессмысленно. Чтобы launchd начал запускать сервисы, нужен
**системный** launchd с настоящим деревом заданий — то есть переход к
«инсталлированному» root'у (пусть и минимальному, собранному руками), а не
к recovery-огрызку.

### Собственный лог launchd (2026-10-31)

Файл `/private/var/log/com.apple.xpc.launchd/launchd.log` живёт в ramdisk и
после загрузки теряется, поэтому добавлена трассировка `write`/`write_nocancel`
для pid 1 (первые 400 записей, до 2 КБ на запись, непечатаемое → `.`).
Что launchd пишет сам:

```
(pid 1)  <Notice>: hello, launchd UUID: ...
         <Notice>: Darwin Bootstrapper Version 7.0.0: ... /launchd/RELEASE_X86_64
         <Notice>: boot-args = -v serial=1 -ignition_level 0
         <Notice>: System Integrity Protection is engaged.
         <Error>:  assertion failed: 99Z999: launchd.real + 60817 [<uuid>]: 0xffffffffffffffff
(system) <Notice>: entering ondemand mode
(system) <Notice>: created
         <Notice>: failed to find AppleKeyStore service
(detect-installed-roots) <Notice>: No cookie from system volume
         <Notice>: No cookie: /System/Volumes/Preboot/<uuid>/.roots-installed
         <Notice>: No cookie: /System/Volumes/iSCPreboot/<uuid>/.roots-installed
(select-boot-mode) <Error>: fsctl(APFSIOC_GET_DEV_BY_ROLE) error: 2
(commit-boot-mode) <Notice>: boot-mode committed: (null)
(allow-non-platform-code) <Notice>: allowing non-platform code now
(sandbox-enable-root-translation) <Notice>: sandbox_enable_root_translation failed: -1, 103
```

То есть: APFS отсутствует (`ENOENT` на `fsctl`), cookie/system volume нет,
sandbox root translation не работает, AppleKeyStore-сервиса нет, и launchd
падает в `assertion failed` на `launchd.real + 0xED71` (это район настройки
односекундного таймера/dispatch-source; аргумент `-1`).

В этом прогоне загрузка остановилась **внутри boot-task'а
`init-with-data-volume`** (в предыдущих — после всего списка), то есть точка
остановки плавает, но всегда это ожидание в userland, а не планировщик.

### Откуда брать системный launchd: SharedSupport.dmg (2026-10-31)

Есть распакованный `SharedSupport.dmg`: `~/dmgwork/Shared Support/`, внутри
`com_apple_MobileAsset_MacSoftwareUpdate` (18 ГиБ) с такими частями:

| запись | формат | что это |
| --- | --- | --- |
| `payloadv2/payload.NNN` (много) | `pbzx` → XZ → AppleArchive (`YAA1`) | полное дерево системы |
| `payloadv2/image_patches/cryptex-system-x86_64` | `RIDIFF10` | **дифф** системного криптекса (1.6 ГиБ) |
| `payloadv2/basesystem_patches/x86_64BaseSystem.dmg` | `BXDIFF50` | **дифф** BaseSystem |
| `AssetData/boot/kernelcache.release.mac16j` | kernelcache | уже используется |

`pbzx` разбирается: 8-байтовое BE-поле размера чанка (8 МиБ), затем
xz-поток; первый же чанк `payload.001` даёт заголовок AppleArchive и имена
вида `System/Library/Frameworks/LinkPresentation.framework/...`, то есть
системные файлы там действительно лежат целиком.

Важно: `~/aa/root` (то, что уже распаковано из BaseSystem) содержит
**тот же самый** bootstrapper-launchd (строка версии совпадает байт в байт),
поэтому «системного» launchd там нет — он внутри `payloadv2`-потоков.

Следующий практический шаг: экстрактор AppleArchive (`YAA1`, с LZFSE) —
своими силами или готовым инструментом; после него можно вытащить
`sbin/launchd`, `usr/lib/dyld`, `usr/lib/system/*.dylib`,
`System/Library/xpc/launchd.plist` и минимальный набор
`System/Library/LaunchDaemons`, то есть собрать «инсталлированный» root.

### Экстрактор на Rust: поток разобран (2026-10-31)

Взяли готовую растовскую реализацию формата — крейт `apple-archive` 0.1
(нужен nightly: он использует `#![feature]`), и написали поверх него
`tools/aar-extract` (папка `tools/aar-extract`, сборка
`build/dis/build-aar-tool.sh`, `rustup` ставится в `$HOME/.cargo`).

Как устроен поток (проверено на реальных данных):

* каждый `AssetData/payloadv2/payload.NNN` — независимый `pbzx`-контейнер;
* блок = 24-байтный заголовок (`u64` BE — размер распакованных данных +
  16 байт) и **самодополняющийся** xz-поток;
* склеенные распакованные блоки всех файлов (2062 блока, **17 121 402 108
  байт**) образуют один непрерывный AppleArchive-поток, причём границы
  блоков режут даже заголовки записей — поэтому читать надо строго
  последовательно (`scripts/pbzx-decode.py | aar-tool`).

Результат прогона: 458 647 записей, 5 ресинхронизаций (некоторые записи
несут данные, не описанные заголовком; инструмент при рассинхроне ищет
следующий `YAA1`), 430 файлов, в том числе:

```
sbin/launchd                              1 236 208 байт
usr/lib/dyld                              2 562 016 байт
System/Library/xpc/launchd.plist          2 411 513 байт
System/Library/LaunchDaemons/*.plist      418 файлов
System/Library/CoreServices/SystemVersion.plist
```

Важное наблюдение: системный `launchd` из payload'а — **тоже**
«Darwin Bootstrapper Version 7.0.0 … launchd/RELEASE_X86_64», но это
*другой* бинарь (1 236 208 против 597 168 байт у recovery-сборки), и строки
`/System/Library/LaunchDaemons` / `/Library/LaunchDaemons` в нём есть.

Подмена `launchd.real` в ramdisk на этот бинарь меняет поведение загрузки
(boot-task'и идут иначе, в текущем прогоне дошли только до `mount-phase-1`),
но каталоги заданий он по-прежнему не открывает — значит загрузка заданий
происходит уже после списка boot-task'ов, и её ещё нужно довести до этого
момента (или собранного «инсталлированного» root'а).

### Что именно нужно launchd: APFS-тома, а не файлы (2026-10-31)

Дальнейшие опыты и трассировка возвратов syscall'ов (в патче `0028` теперь
есть кольцо последних 24 вызовов pid 1 с errno и дамп при
`exit`/`abort_with_payload`) дали точный ответ.

1. **Системный launchd как настоящий init.** Положили бинарь из payload'а
   на место `/sbin/launchd` (pid 1 запускается ядром напрямую, стаб убран в
   `/sbin/launchd.stub`). Поведение не изменилось: те же boot-task'и, те же
   «No cookie…», тот же assert. Значит режим bootstrapper'а выбирается не по
   argv[0] и не по способу запуска.

2. **Заглушки томов.** Создали `System/Volumes/{Data,Preboot,iSCPreboot,Update}`,
   cookie `.roots-installed` в Preboot/iSCPreboot и пустые
   `var/db/com.apple.xpc.launchd/config/{system,user}.plist`. launchd стал
   писать

   ```
   Found cookie: /System/Volumes/Preboot/<uuid>/.roots-installed
   Found roots installed cookie
   assertion failed: … launchd.real + 347679 …: 0xffffffffffffffff
   ```

   и сразу вызывает `abort_with_payload` (syscall 521) — ядро паниковало
   «initproc exited».

3. **Трасса возвратов показала, что виноват не syscall.** За всю загрузку
   1549 неуспешных вызовов, но последние 24 перед abort — только бытовые
   `lstat64 → ENOENT`, `sysctl → EPERM`, затем `kevent_id`, `sigprocmask` и
   `abort_with_payload`. То есть падает внутренний assert, а не системный
   вызов.

4. **Причина видна по строкам самого launchd** (рядом с диагностикой cookie):

   ```
   fsctl(APFSIOC_GET_DEV_BY_ROLE) error: %d
   fsctl(APFSIOC_IS_VOL_LOCKED) error: %d
   Data Volume is %s
   kern.apfsprebootuuid / kern.bootuuid / kern.bootobjectspath
   /System/Volumes/Preboot/%s/%s
   .roots-installed / .DarwinDepot
   ```

   То есть «roots installed» проверяется через APFS-специфичные `fsctl` и
   sysctl'ы. У нас корень — HFS+ на ramdisk, `fsctl(APFSIOC_GET_DEV_BY_ROLE)`
   возвращает `ENOENT` (`error: 2`), поэтому launchd честно пишет
   «No cookie from system volume», а наши файлы-заглушки проходят лишь
   частичную проверку и приводят к assert'у.

**Вывод.** «Инсталлированный» root нельзя собрать одними файлами: launchd
требует **APFS с ролями томов** (System/Data/Preboot), а APFS в XNU — это
`AppleAPFS.kext`, которого у нас нет и который наш порт пока не умеет
загружать/исполнять. Пока это так, единственный достижимый путь — bootstrapper
(загрузка boot-task'ов), после которых он честно простаивает.

Откат: `build/dis/revert-launchd-experiments.sh` (стаб вернулся в
`/sbin/launchd`, recovery-бинарь — в `launchd.real`, заглушки томов удалены,
образ пересобран, загрузка снова доходит до «logging initialized»).

Что понадобится для следующего шага: APFS-драйвер в ядре (или загрузка
`AppleAPFS.kext` из payload'а, что требует рабочего KEXT-загрузчика, IOKit и
`libkern`), и уже на нём — минимальный APFS-том с ролями System/Data.


## 8. Kext-загрузчик: рабочий путь (2026-10-31)

Цель блока — проверить, что порт умеет загрузить сторонний kext, прежде чем
браться за `AppleAPFS.kext`. Собран минимальный kext `tools/hello-kext`
(`com.crossxnu.hello`), который в `start()` печатает строку в консоль.

**Результат: kext загружен и выполнен.** В serial-логе:

```
Kext com.crossxnu.hello calling module start function.
crossxnu: hello.kext start (kmod_info=<ptr> data=0)
```

Паники нет, загрузка продолжается до `load_init_program`/launchd. Это первый
исполненный сторонний kext в нашем ядре.

### 8.1 Динамической загрузки kext'ов в xnu-12377 нет

- `libkern/RELEASE/config_kxld.h` содержит `#define NCONFIG_KXLD 0`;
- `options CONFIG_KXLD` есть в `config/MASTER` (строка 541), но **ни одна**
  группа (`RELEASE`/`DEVELOPMENT`/`DEBUG`) его не перечисляет, поэтому в
  `CONFIG_DEFINES` его нет и `libkern/kxld/*.c` (`optional config_kxld`) в
  сборку не попадают;
- как следствие, `OSKext::loadFromMkext` и `kextd`-протокол вырезаны
  препроцессором.

Вывод: единственный поддерживаемый путь — **prelinked kext из kernel
collection** (`__PRELINK_TEXT` + `__PRELINK_INFO`). Именно так macOS грузит и
`AppleAPFS.kext`, так что для APFS нужен не свой kxld, а сборка и загрузка
KC/AuxKC.

### 8.2 Как kext собирается и попадает в KC

- `tools/kext-loader/build-hello-kext.py` берёт аргументы компиляции из
  `compile_commands.json` ядра (включая `-DKERNEL -DMACH_KERNEL_PRIVATE` и
  `-I EXPORT_HDRS/...`) и линкует `ld64 -kext -undefined dynamic_lookup`.
  Подключать `<sys/systm.h>` нельзя: экспортированные bsd-заголовки смешивают
  kernel- и userland-версии `<sys/types.h>` и падают на `clock_t`/`int32_t`.
  Рабочий минимум — `<mach/kmod.h>` + `<kern/misc_protos.h>`
  (`tools/kext-loader/probe-kext-includes.py`).
- `kc-builder` линкует kext против таблицы символов ядра (24 265 символов),
  патчит `kmod_info` и кладёт код в `__PRELINK_TEXT`; `build/kernel.kc`
  (MH_FILESET) грузится нашим EFI-загрузчиком, ядро стартует с него так же,
  как с обычного `MH_EXECUTE`.
- `com.apple.kpi.*` добавляются в KC codeless-kext'ами
  (`./scripts/build-fileset.sh --kext ... --with-kpi`), иначе зависимости
  kext'а не разрешаются.
- Загружает kext хук в `bsd_init()` (`OSKextLoadKextWithIdentifier`): kext'ы
  из `__PRELINK_INFO` при загрузке только *регистрируются*, а просит их
  грузить IOCatalogue/kextd, которых у нас нет.

### 8.3 Баг kc-tools, который всё блокировал

ld64 кладёт релокации kext'а в **`LC_DYSYMTAB`** (таблицы external/local
relocations), а не в заголовки секций: у такого образа у всех секций
`nreloc = 0`, и проход `link_kext()` по секциям не видел ни одной записи.
Последствия ровно те, что наблюдались:

- `call printf` оставался `e8 00 00 00 00` — вызов следующей инструкции,
  поэтому kext «стартовал» и падал на возврате
  (`Data/Stack execution not permitted`);
- `kmod_info.start/stop` оставались «голыми» смещениями `0xf50`/`0xf70`, и
  OSKext отказывался грузить kext (`module start pointer is outside of kext
  range`).

Фикс — `patches/kc-tools/0002`: проход по `extreloff/nextrel` и
`locreloff/nlocrel` с пересчётом в финальные адреса (extern: символ + addend;
local: сдвиг секций на vmbase). Генератор —
`tools/kext-loader/fix-kc-tools-dysymtab-relocs.py`.

Проверка результата без загрузки:

```
$ python3 tools/kext-loader/dump-kmod-info.py build/kernel.kc 0xffffff80011c1000
  address  @0x09c = 0xffffff80011c0000
  start    @0x0b4 = 0xffffff80011c0f50
  stop     @0x0bc = 0xffffff80011c0f70
```

и `call` в тексте kext'а указывает точно на `_printf` ядра
(`0xffffff8000308da0`).

### 8.4 APFS из BootKernelExtensions.kc: что достаётся и что мешает

`BootKernelExtensions.kc` — это `MH_FILESET` из **204 вложенных Mach-O**
(ядро + kext'ы), у каждого свой `LC_FILESET_ENTRY`, `LC_SYMTAB`,
`LC_DYSYMTAB`, `LC_SEGMENT_64`. APFS лежит там как
`com.apple.filesystems.apfs`:

```
vm=0xffffff8003118000 off=0x3018000 ftype=0xb
__TEXT vm=0xffffff8003118000 filesz=0x1bb000
__DATA vm=0xffffff80032d3000 filesz=0xa000
__DATA_CONST vm=0xffffff80032de000 filesz=0x9000
__LINKEDIT vm=0xffffff800349c000 filesz=0xc4c5ea
symtab: 4419 символов (3162 defined, 1257 undefined), strtab 8.7 МБ
```

Образ **извлекается** как самостоятельный kext (валидный `MH_KEXT_BUNDLE`,
14.8 МБ, символы читаются, дизассемблируется) —
`tools/kext-loader/kc-extract-kext.py` (сдвигает все file-offset'ы:
сегменты, секции, `LC_SYMTAB`, `LC_DYSYMTAB`, `LC_FUNCTION_STARTS`).

**Но загрузить его как есть нельзя:** у всех 204 kext'ов в коллекции
`extrel = 0` и `locrel = 0` — коллекция полностью слинкована, таблиц
релокаций нет. Код уже привязан к *адресам ядра Apple*, а наше ядро
собрано из того же исходника, но адреса функций другие. Обычный линкер
(kc-builder) здесь ничего не сделает: ему нечего применять.

Насколько это далеко от рабочего состояния (`tools/kext-loader/`):

- `kc-symbol-coverage.py`: из 1257 импортов APFS **1072 (85.3%) уже есть в
  нашем ядре**, 185 приходят из соседних kext'ов коллекции, отсутствующих
  полностью — 0.
- `kc-retarget-cost.py` + `otool -tv`: в `__text` 37 157 прямых
  call/jmp, из них **600 различных внешних адресов**; все они резолвятся
  через символьные таблицы самой коллекции (то есть имя символа известно).
  Плюс 18 685 rip-relative ссылок на данные (часть из них — внешние,
  точную цифру даст только полноценный дизассемблер с расчётом адреса
  операнда).

Вывод: путь «взять байты из KC и загрузить» закрыт, но **перевод APFS на
наше ядро в принципе возможен** — через инструмент перезаписи ссылок
(disassembly-based re-targeting): для каждой внешней call/jmp и каждой
внешней rip-relative ссылки найти адрес Apple, сопоставить с именем символа
через симтаблицы KC, подставить адрес из нашего ядра. К этому добавляется
необходимость тащить за APFS 185 символов из соседних kext'ов (цепочка
IOStorageFamily и т.п.).

### 8.5 Варианты следующего шага

| # | Путь | Стоимость | Риск |
|:--|:-----|:----------|:-----|
| 1 | Найти `AppleAPFS.kext` **того же билда без prelink** (KDK) и собрать через `kc-builder` — код уже с релокациями, наши патчи kc-tools готовы | низкая, если KDK доступен | ABI/подпись, но версия та же |
| 2 | Свой «re-targeting» релинкер: 600 внешних call/jmp + rip-relative ссылки, символы из симтаблиц KC | высокая (инструмент + отладка в ядре) | неполный охват ссылок |
| 3 | Портировать открытый APFS-драйвер (linux-apfs-rw, read-only) в VFS XNU, роли томов реализовать самим | высокая, но предсказуемая | несовпадение с APFS-фичами macOS |
| 4 | Реализовать минимальный APFS самим (только чтение нужных томов) | очень высокая | долго |

Пока приоритет — проверить вариант 1 (KDK), потому что он не требует
переписывания кода: если найденный `AppleAPFS.kext` собран под тот же
`xnu-12377.121.6`, то `scripts/build-fileset.sh --kext ... --with-kpi`
соберёт KC, а загрузка пойдёт тем же путём, что уже проверен на
`hello.kext`. Вариант 2 держим как основной, если KDK нет.
### 8.6 Попытка «варианта 2»: ретаргетинг APFS на наше ядро

Инструмент написан и работает, но упёрся в отсутствие данных.

**Что сделано** (`tools/kext-loader/kc-retarget.py`):

- загружает KC, строит диапазоны ядра Apple (621 сегмент) и диапазоны всех
  204 kext'ов, карту `адрес → имя` из символьных таблиц KC;
- дизассемблирует `__text` извлечённого kext'а через capstone 5.0.7
  (установлен в WSL) с точными `disp_offset`/`imm_offset`;
- классифицирует каждую ссылку: внутренняя (оставляем), в другой kext
  (оставляем — они сохранятся, если грузить все kext'ы по их исходным
  адресам), в образ ядра Apple (переписываем на адрес из нашего ядра);
- переписывает три вида: прямые `call/jmp rel32`, rip-relative операнды и
  8-байтовые указатели в секциях данных;
- умеет только отчёт (`--apply` пишет результат), чтобы сначала оценить
  масштаб.

**Блокер:** у образа ядра в KC **нет таблицы символов**. `LC_SYMTAB`
занулён (`symoff=nsyms=stroff=strsize=0`), сегмента `__LINKINFO`, который
использовался в старых kernelcache, в этом формате нет. В `__LINKEDIT`
видны плотные строки имён (`_kfree_external`, `_IOFree`,
`_IOFreeAligned`, …), но массив `nlist_64` перед строковой таблицей не
находится (`tools/kext-loader/kc-recover-syms.py`, сейчас он находит
строковую таблицу kext'а, а не ядра).

Без карты `имя → адрес` для ядра Apple нельзя понять, какой именно
символ стоит за каждым из 600 внешних адресов, а значит нельзя подставить
адрес из нашего ядра. Диапазоны и имена kext'ов есть, ядра — нет.

**Что это значит для варианта 2:** нужна одна из трёх вещей:

1. таблица символов ядра того же билда (KDK/дамп с реальной машины);
2. восстановление таблицы из `__LINKEDIT` (структура строк известна, но
   массив записей пока не найден — это следующий конкретный шаг исследования:
   разобрать формат блока с `_kfree_external` и проверить, есть ли рядом
   адреса);
3. сопоставление функций Apple ↔ наши по коду (сборка из одного исходника:
   порядок функций в `__TEXT_EXEC` близок, различия — наши патчи), что
   позволяет получить `имя → адрес` без таблицы.

Пока не решён этот вопрос, «официальный APFS» через ретаргетинг не
собирается, и вариант 2 остаётся исследовательским, а не инженерным.
### 8.7 KDK как источник непрелинкованного APFS (найдено решение)

KDK (Kernel Debug Kit) 26.7.2 build 25G332 распакован без macOS-инструментов:

```
7z x Kernel_Debug_Kit_26.7.2_build_25G332.dmg     # LZFSE -> HFS
bsdtar -xf "Kernel Debug Kit/KernelDebugKit.pkg"  # xar -> KDK.pkg/Payload
python3 tools/kext-loader/kdk-payload-decode.py KDK.pkg/Payload > payload.cpio
bsdtar -xf payload.cpio "./System/Library/Extensions/apfs.kext"
```

Payload — `pbzx`, но вариант с 16-байтовым заголовком блока
`(u64 uncompressed, u64 compressed)` и **stored-блоками** (не-xz, odc-cpio
как есть). Декодер: `tools/kext-loader/kdk-payload-decode.py`
(295 xz + 3 stored блока → 4.7 ГБ cpio, 8043 записи).

В KDK лежит `System/Library/Extensions/apfs.kext` с **настоящим бинарём**
(universal x86_64 + arm64e). После `lipo -thin x86_64`:

```
Mach-O 64-bit x86_64 kext bundle, NOUNDEFS|DYLDLINK|TWOLEVEL
__TEXT 0x1bb000, __DATA 0xa000, __DATA_CONST 0x9000, __LINKEDIT 0x84a50
dysymtab: extrel=14055 locrel=1942, nundef=1257
```

То есть это **не prelinked kext: релокации на месте**, и наш `kc-builder`
(с фиксом `LC_DYSYMTAB` из §8.3) может его линковать штатно — ретаргетинг
(§8.6) не нужен.

Проверка покрытия символов нашим ядром: из 1257 импортов **1072 уже есть**,
185 приходят из соседних kext'ов (`IOMediaBSDClient::*`,
`CoreAnalyticsHub::*`, …). Значит для сборки нужен замыкающий набор
kext'ов-поставщиков из того же KDK (kc-builder умеет несколько `-kext` и
мержит символы по порядку), после чего — сборка KC и загрузка тем же
путём, что `hello.kext`.

Осталось: (1) построить замыкание зависимостей по KDK, (2) собрать KC с
`apfs`, (3) загрузить и посмотреть, регистрируется ли `com.apple.filesystems.apfs`
в VFS.
### 8.8 Бисекция: панику даёт именно apfs

Проверено на одном и том же ядре (с хуком, но хук срабатывает позже места
падения):

| KC содержит | Результат |
|:--|:--|
| `hello.kext` | грузится, kext стартует |
| `IOStorageFamily.kext` (KDK) | грузится, kext регистрируется |
| `apfs.kext` (KDK) | паника до регистрации kext'ов |
| `apfs` codeless (только plist) | EFI-загрузчик отвергает: `failed to compute vm range: Compromised Data` |

Паника одинаковая во всех «apfs-с-кодом» вариантах:

```
VM bootstrap done: 69 maps, 105 entries and 10 nodes left
panic: Kernel trap, type 14=page fault, CR2: 0xba
RIP: 0xffffff800038be54 -> _vm_pre_fault_with_info +0x1a4  (via _vm_fault)
```

Строки `can't perform kext scan: no kext summary` и `NULL thread->t_tro` —
это уже печать паники (символизация по kext summary и валидация указателя),
а не причина.

Важно: падение происходит **до** регистрации kext'ов, сразу после
`VM bootstrap done`, то есть в коде инициализации ядра, который исполняется
до `standard timeslicing quantum`. В этом месте `startup.c` вызывает
`OSKextRemoveKextBootstrap()` — «выбросить сегменты, использованные для
загрузки kext'ов: KLD, PRELINK symtab, LINKEDIT и symtab». Это первый
подозреваемый: kc-builder переставил `__LINKEDIT` ядра за большой
`__PRELINK_TEXT` apfs (0x141b000), и освобождение диапазонов может задеть
ещё нужные страницы.

Следующие шаги:

1. Инструментировать `OSKextRemoveKextBootstrap()` / `kernel_bootstrap_log`,
   чтобы увидеть точку отказа (и заодно проверить, печатает ли `-v`
   bootstrap-логи).
2. Собрать KC с apfs, размещённым по другому адресу (`-kext-vmbase`), чтобы
   понять, зависит ли паника от раскладки, а не от содержимого kext'а.
3. Отдельно починить EFI-загрузчик: KC без `__PRELINK_TEXT` (codeless)
   сейчас отвергается как «Compromised Data».

## 9. Официальный APFS загружен и запущен (2026-10-31)

Итог длинной цепочки: **Apple APFS из KDK 26.7.2 слинкован нашим
`kc-builder` и запущен в нашем ядре.**

```
apfs_module_start:3724: load: com.apple.filesystems.apfs, v2811.160.7,
                        apfs-2811.160.7.702.4, 2026/10/11
Kext com.apple.filesystems.apfs is now started.
Kext com.apple.filesystems.apfs loaded.
```

Классы IOKit зарегистрированы (`AppleAPFSContainer`, `AppleAPFSContainerScheme`,
`AppleAPFSSnapshot`, `AppleAPFSGraft`, `AppleAPFSMediaBSDClient`), паники нет,
загрузка доходит до launchd.

### 9.1 Что понадобилось (сводка по слоям)

| Слой | Проблема | Решение |
|:--|:--|:--|
| Источник | в KC у всех kext'ов `extrel=locrel=0` | KDK 26.7.2: `apfs.kext` с релокациями (`extrel=14055`) |
| Упаковка KDK | DMG → HFS → xar → pbzx со stored-блоками | `tools/kext-loader/kdk-payload-decode.py` |
| kc-tools | `LC_DYSYMTAB`-релокации не применялись | `patches/kc-tools/0002` |
| kc-tools | file offset считался как `va`, ломая `__kalloc_type` | `0003` (карта сегментов) |
| kc-tools | codeless-kext'ы с `CFBundleExecutable` → NULL `kmod_info` | `0004` (вырезание ключа) |
| kc-tools | вырезание оставляло висячий `<key>` → plist обрывался | `0005`, `0006` |
| kc-tools | локальные релокации в секциях: `target+addend` | `0006` (`addend+load_vmaddr`) |
| ядро | `dep_kmod->reference_count++` при NULL `kmod_info` у codeless-зависимостей | патч `OSKext.cpp` (пропуск) |
| ядро | `strnlen(NULL, …)` из kext'а при старте | диагностика в `strnlen_impl` (возврат 0) |
| KC | `OSBundleLibraries_x86_64` у apfs требует `AppleEFINVRAM` | синтетический codeless-stub (`make-codeless-stubs.py`) |

### 9.2 Порядок сборки

```bash
K=/tmp/kdkroot/System/Library/Extensions     # распакованный KDK
python3 tools/kext-loader/make-codeless-stubs.py build/codeless-stubs \
    $K/corecrypto.kext $K/AppleImage4.kext $K/AppleEffaceableStorage.kext \
    $K/IOStorageFamily.kext $K/CoreAnalyticsFamily.kext $K/apfs.kext \
    $K/CoreTrust.kext $K/IOCryptoAcceleratorFamily.kext
./scripts/build-fileset.sh \
    --kext $K/corecrypto.kext --kext $K/AppleImage4.kext \
    --kext $K/AppleEffaceableStorage.kext --kext $K/IOStorageFamily.kext \
    --kext $K/CoreAnalyticsFamily.kext --kext $K/apfs.kext \
    --kext build/hello-kext/com.crossxnu.hello.kext \
    --codeless $K/CoreTrust.kext --codeless $K/IOCryptoAcceleratorFamily.kext \
    --codeless build/codeless-stubs/AppleEFINVRAM.kext --with-kpi
```

### 9.3 Что дальше

1. Поднять `/System/Volumes` и дождаться, пока launchd увидит APFS-тома с
   ролями (System/Data/Preboot) — см. §7.
2. Убрать диагностику `strnlen` (или оставить под boot-arg), перенести патчи
   `OSKext.cpp`/`subrs.c` в серию `patches/` (сейчас в рабочем дереве).
3. Проверить, монтируется ли APFS-образ (нужен валидный APFS-том в QEMU).

## 10. Chained fixups: проверено, что они не нужны; virtio закрыт (2026-10-31)

Планировалась поддержка `LC_DYLD_CHAINED_FIXUPS` в `kc-tools` как
«разблокировщик всего KDK». Проверка показала, что профита нет, а причина
паники на virtio-наборе была другая.

### 10.1 Замеры по KDK 26.7.2 (718 kext'ов)

`tools/kext-loader/kdk-slice-scan.py /tmp/kdkroot/System/Library/Extensions --summary`:

```
{'has-x86_64': 275, 'arm64-only': 443}
```

То есть 443 kext'а вообще не содержат x86_64-кода. Отдельно:

```
$ kdk-slice-scan.py ... --chainfix          # x86_64 kexts using chained fixups
(пусто)
```

**Ни один x86_64-kext в KDK не использует chained fixups.** Они есть только в
arm64e-срезах (формат указателей 7 = `ARM64E_KERNEL`), которые мы всё равно
не можем исполнить. Все 275 x86_64-kext'ов собраны либо с классическими
релокациями (то, что мы уже применяем через `LC_DYSYMTAB`), либо (реже) с
`LC_DYLD_INFO`-opcode'ами, которые линковщик тоже обрабатывает. Так что
поддержка chainfix была бы мёртвым кодом.

### 10.2 Почему падал virtio-набор

`AppleVirtIOStorage` — **arm64-only** kext:

```
$ tools/kext-loader/chainfix-info.py .../AppleVirtIOStorage.kext/Contents/MacOS/AppleVirtIOStorage
file:            .../AppleVirtIOStorage
slice base:      0x0  size 0x57c90  is64=1
segments:        5
  [0] __TEXT           vmaddr 0x0000000000000000 ...
  ...
  seg[2] __DATA       size 24   page_size 0x1000  format 7 (ARM64E_KERNEL)
```

`macho_view()` брал первый 64-битный срез, поэтому в KC попадал arm64-код, и
ядро падало на первом вызове в kext'е (`_strcmp +0x10`, GP). Отсюда и
подозрение на chained fixups: они действительно были в том срезе, но
исполнять его всё равно нельзя.

Итого путь «virtio-blk + `AppleVirtIOStorage`» закрыт: у Apple нет x86_64
сборки этого kext'а. `AppleVirtIO` и `IOPCIFamily` — двойные (x86_64+arm64),
`AppleVirtIOStorage` — нет.

### 10.3 Что сделано вместо chainfix

`patches/kc-tools/0007`:

* `link_kext()` получает cputype ядра и выбирает срез по архитектуре
  (`macho_view_for_cpu`), а не первый 64-битный;
* отсутствие нужного среза и `LC_DYLD_CHAINED_FIXUPS` — это
  `LINK_UNSUPPORTED`, и `kc-builder` **прерывает сборку** с внятным текстом,
  а не пропускает kext молча (иначе получается KC, который падает далеко от
  причины);
* проверка воспроизводится без реального kext'а:
  `tools/kext-loader/make-chainfix-sample.py`.

Заодно починена серия `patches/kc-tools/`: она была набором снимков, а не
цепочкой инкрементов, поэтому `scripts/build-kc-tools.sh` не мог применить
её целиком (`Hunk #2 FAILED` на `0003`). Пересборка —
`tools/bringup/regen-kc-tools-patches.sh`; применение с нуля сверено с
эталонным деревом, а сборка APFS-набора даёт побайтово тот же KC, что и до
патча.

### 10.4 Настоящий блокер: APFS нужен `IOMedia`

`apfs` грузится и стартует, но монтировать ему нечего: нужен `IOMedia` от
драйвера-провайдера. В KDK все провайдеры (`IOAHCIFamily`+`AppleAHCIPort`,
`IONVMeFamily`, `IOUSBMassStorageDriver`, `IOSCSIArchitectureModelFamily`)
висят на `IOPCIDevice`, а корневой PCI-мост публикует `AppleACPIPlatform`
(класс `AppleACPIPCI`); в самом XNU ни ACPI, ни PCI-перечисления нет.
Символьное замыкание `IONVMeFamily` при этом маленькое и всё x86_64
(8 kext'ов: `IONVMeFamily`, `IOPCIFamily`, `IOStorageFamily`,
`AppleMobileFileIntegrity`, `CoreTrust`, `CoreAnalyticsFamily`,
`AppleImage4`, `corecrypto`), а вот `AppleACPIPlatform` тянет arm64-only
`AppleARMPlatform` и 34 неразрешённых символа (`_PE_arm_debug_panic_hook`,
`_PAGE_SHIFT_CONST`, `IONVRAMController::*`, `*_RESERVED*`).

Варианты (по возрастанию стоимости):

1. **Свой kext-«blockstorage»**: `IOMedia` над буфером в памяти, который
   загрузчик уже умеет читать (`ramdisk.img`) — без PCI/ACPI. Блокер:
   нет `IOKit/storage/IOMedia.h` и `IOStorage.h` (их нет ни в XNU, ни в KDK,
   ни в нашем синтетическом SDK) — нужны заголовки из macOS SDK/Kernel.framework.
2. **NVMe/AHCI через PCI**: нужен работающий `AppleACPIPlatform`
   (ACPI-таблицы, platform expert) — отдельный крупный проект.
3. **Другой KDK** (старше, где есть x86_64-варианты нужных kext'ов) — не
   решает проблему `IOMedia`, только набор драйверов.

## 11. APFS-контейнер смонтирован с RAM-устройства (2026-10-31)

Блокер из §10.4 закрыт вариантом 1: свой kext, который публикует блочное
устройство поверх памяти ядра. `apfs` теперь **монтирует контейнер**, и
загрузка идёт дальше в userland.

```
CrossXnuRAMStorage: 8388608 bytes at <ptr>, 2048 blocks of 4096
apfs_module_start:3724: load: com.apple.filesystems.apfs, v2811.160.7 ...
dev_init:299: disk0 device_handle block size 4096 block count 2048 features 0 internal
nx_mount:1230: disk0 initializing cache w/hash_size 8192 and cache size 32768
nx_mount:1548: disk0 checkpoint search: largest xid 1, best xid 1 @ 1
nx_mount:1575: disk0 stable checkpoint indices: desc 0 data 0
```

`disk0` здесь — это наш kext: `IOBlockStorageDevice` → `IOBlockStorageDriver`
→ `IOMedia` → `AppleAPFSContainerSchemeWholeDisk` → `nx_mount`. Ни PCI, ни
ACPI, ни работы с физической памятью: образ APFS лежит сегментом в самой
коллекции.

### 11.1 Как это устроено

| Слой | Что сделано |
|:--|:--|
| Образ | `__APFSIMG` — сегмент коллекции (`scripts/kc-add-segment.py`), RWX; загрузчик мапит его как любую другую часть KC |
| Доступ | kext ищет сегмент через `getsegbyname("__APFSIMG")` — тот же вызов, что и `bsd_init.c` для `__ROOTIMG`, так что адрес сразу является VA ядра |
| Устройство | `tools/blockstorage-kext/blockstorage.cpp`: `IOBlockStorageDevice` над этим буфером, блок 4096 |
| Публикация | kmod `start()` сам создаёт объект, делает `attach(IOService::getResourceService())` и `registerService()`; `bsd_init.c` просит OSKext загрузить kext по идентификатору прямо перед APFS |
| Медиа | `IOBlockStorageDriver` из `IOStorageFamily` матчится по `device-type=Generic` и создаёт `IOMedia` (`Whole`) |
| Заголовки | `IOKit/storage/*` берутся из SDK (`tools/kext-loader/fetch-sdk-headers.ps1`) в `build/sdk-ext`; в репозиторий не попадают |

### 11.2 Проверка совместимости заголовков (ABI)

Заголовки — из SDK 10.15, а классы — из KDK 26.7.2, поэтому размеры сверены
по самому KDK: каждый класс регистрирует свой размер в `OSMetaClass`, значит
число зашито в статический инициализатор (`tools/kext-loader/kext-class-size.py`).

```
$ kext-class-size.py .../IOStorageFamily
IOBlockStorageDevice                          144   0x90
IOBlockStorageDriver                          344   0x158

$ размеры, которые даёт наш компилятор с заголовками SDK и заголовками ядра
IOStorage                   144   0x90
IOMedia                     208   0xd0
IOBlockStorageDevice        144   0x90
IOBlockStorageDriver        344   0x158
```

Совпадает: подобъект не перерос базовый класс, значит размеры и раскладка
объектов те же, что у боевого `IOStorageFamily`. Порядок виртуальных функций
стабилен по правилам Apple — новые слоты занимают `Reserved*` в конце.

### 11.3 Роли томов

`mkapfs` создаёт том с ролью NONE. Роль — это `u16` в суперблоке тома
(`apfs_superblock.apfs_role`, смещение 0x3C4) под защитой Fletcher-64,
поэтому `tools/kext-loader/apfs-set-role.py` правит поле и пересчитывает
контрольную сумму; `apfsck` из apfsprogs на исправленном образе проходит
без замечаний.

```bash
tools/kext-loader/apfs-set-role.py build/apfs8.img --role system
tools/kext-loader/apfs-set-role.py build/apfs8.img --show
```

### 11.4 Что осталось до launchd

Контейнер смонтирован, но **том — ещё нет**, и launchd это видит:

```
Not booted from APFS, skipping apfs_boot_util
<Error>: fsctl(APFSIOC_GET_DEV_BY_ROLE) error: 2
```

То есть:

1. Нужно смонтировать сам том (VFS `mount("apfs", ...)` по `/dev/disk0`).
   В macOS это делает launchd/`apfs_boot_util`, но только когда корень уже
   APFS, а у нас корень — HFS+ (`md0`), поэтому ветка пропускается.
2. Для `APFSIOC_GET_DEV_BY_ROLE` нужен **смонтированный** том с ролью
   System/Data: сейчас том не материализован, отсюда ENOENT.
3. Том пустой: `mkapfs` умеет только форматировать. Для настоящего launchd
   нужен заполненный System-том (перенос userland из recovery-ramdisk в APFS),
   а apfsprogs пока не умеет писать файлы.

Порядок дальше: смонтировать пустой том (доказать, что `apfs_vfsop_mount`
работает на нашем устройстве) → затем решать, чем наполнять System-том.

Заодно поправлено: `kc-add-rootimg.py` стал обёрткой над общим
`kc-add-segment.py` (имя сегмента — параметр), а хук в `bsd_init.c`
(патч `0028`) теперь грузит наш kext перед APFS.

### 11.5 Устройство публикуется после IOBSD, иначе нет /dev-узла

Первые попытки смонтировать том упирались в то, что `/dev/disk0` вообще не
существовал: BSD-клиенты медиа (`IOMediaBSDClient`, `AppleAPFSMediaBSDClient`)
матчатся по `IOResourceMatch = IOBSD`, а этот ресурс публикует
`IOKitBSDInit()` — в самом конце `bsd_init()`, уже после нашего хука.
Медиа, зарегистрированное раньше, узла не получает никогда.

Поэтому публикация в kext'е отложена: kmod `start()` только создаёт объект,
а `IOTimerEventSource` на отдельном workloop ждёт появления свойства `IOBSD`
у `IOResources`, и лишь затем делает `attach`/`start`/`registerService`.
Проверка в одном прогоне:

```
crossxnu: probe /dev/console -> 2      # до публикации /dev ещё пуст
...
CrossXnuRAMStorage: 8388608 bytes at <ptr>, 2048 blocks of 4096
crossxnu: mount -t apfs /dev/disk0 /mnt1 -> 22
```

То есть `/dev/disk0` теперь появляется (узел контейнера), а монтирование
возвращает `22` (`EINVAL`) — следующий вопрос: APFS не принимает контейнерное
устройство как точку монтирования (в macOS монтируют том, `disk0s1`, либо
контейнер с опцией `role=`), и узла тома `disk0s1` пока нет: тома
перечисляет сам APFS при обработке монтирования.

Смонтировать том из kext'а нельзя: `kernel_mount()` — не экспортируется в
таблицу символов ядра, поэтому kext вызывает `crossxnu_mount_apfs_volume()`
(теперь не `static`), а вся работа с VFS остаётся в `bsd_init.c`.

### 11.6 Причина EINVAL (22) при монтировании APFS-тома: fsmountargs и KERNEL_MOUNT_BASESYSTEMROOT

Причина `EINVAL` (22) при вызове `kernel_mount("apfs", ...)` — не в APFS, а в
проверке самого VFS: kernel-монтирование файловой системы с `VFC_VFSLOCALARGS`
запрещено, если не выставлен специальный флаг. Ниже сначала эта проверка
(§2), потом — как ведёт себя APFS, когда управление до неё всё-таки доходит
(§1, §3: дизассемблирование KDK-драйвера, проверено по символам и строкам
бинарника).

#### 1. Как APFS парсит параметры монтирования

Точка входа операций монтирования VFS в kext'е — `apfs_vfsop_mount` (смещение
`0xa3607` в `__text`, VMA `0xffffff80031bb607`). Аргумент `data` (`fsmountargs`)
передаётся в регистре `%r12`:

```asm
ffffff80031bb733:   testq   %r12, %r12          # fsmountargs == NULL?
ffffff80031bb736:   jne     0xffffff80031bb74d  # если передан указатель -> ветка copyin
ffffff80031bb738:   movq    %r13, %rdi
ffffff80031bb73b:   movl    $0x144, %edx        # размер структуры аргументов: 324 байта
ffffff80031bb740:   callq   _bzero              # при NULL: зануление всей структуры
ffffff80031bb745:   movq    $0x0, -0x88(%rbp)
ffffff80031bb750:   jmp     0xffffff80031bb954
...
# Если fsmountargs != NULL:
ffffff80031bb772:   movl    $0x144, %edx
ffffff80031bb777:   callq   _copyin             # копирование из user_addr_t fsmountargs!
...
# Проверка режима монтирования:
ffffff80031bb954:   movzwl  0x8(%r13), %eax     # eax = args->mount_mode (+0x8)
ffffff80031bb959:   cmpq    $0x8, %rax          # допустимые режимы: 0..8
ffffff80031bb95d:   ja      0xffffff80031bbe40  # если > 8 -> ветка ошибки
...
ffffff80031bbe40:   leaq    str_invalid_mount_mode(%rip), %rsi # "%s:%d: invalid mount mode"
                    callq   _log_warn
                    movl    $0x16, %ebx         # 0x16 = 22 (EINVAL)
```

По смещению `+0x8` структуры аргументов APFS расположено двухбайтовое поле
`mount_mode`. Если оно строго больше `8`, APFS логирует предупреждение
`invalid mount mode` и немедленно завершает вызов с ошибкой `EINVAL` (`22`).

В падавшем вызове эта ветка не исполнялась вообще (см. §2) — она интересна
только тем, что произойдёт, когда управление до APFS всё-таки дойдёт.
Проверено по бинарнику KDK: строка `"%s:%d: invalid mount mode\n"` находится
по смещению `0xa3e40`, проверка `movzwl 0x8(%r13), %eax` / `cmpq $0x8` —
по `0xa3954`, а `$0x144` (324 байта — размер структуры) встречается в
функции трижды. Символы `_container_rootmount` (`0x55568`),
`_container_decompose`, `_rootedRamdisk` в бинарнике есть.

#### 2. Настоящая причина: guard в `mount_common` (`bsd/vfs/vfs_syscalls.c`)

`kernel_mount()` сам выставляет `KERNEL_MOUNT_KMOUNT` (`0x400`), а для
kernel-монтирования в `mount_common()` есть отдельный запрет — строки
1348–1357:

```c
/*
 * VFC_VFSLOCALARGS is not currently supported for kernel mounts,
 * except in ROSV configs and for the initial BaseSystem root.
 */
if (kernelmount && (vfsp->vfc_vfsflags & VFC_VFSLOCALARGS) &&
    ((internal_flags & KERNEL_MOUNT_VOLBYROLE_MASK) == 0) &&
    ((internal_flags & KERNEL_MOUNT_BASESYSTEMROOT) == 0)) {
	error = EINVAL;  /* unsupported request */
	goto out1;
}
```

У APFS стоит `VFC_VFSLOCALARGS` (она ждёт путь к устройству), а передавали мы
только `KERNEL_MOUNT_NOAUTH` (`0x01`) — ни `VOLBYROLE`, ни `BASESYSTEMROOT`
не было. Поэтому `EINVAL` возвращался **до** вызова `VFS_MOUNT`:
`apfs_vfsop_mount` не запускалась, `fsmountargs` не разбирался, и строки
`invalid mount mode` в логе не было — её там и не появлялось.

Отсюда же и код ошибки: ровно `22`, а не `EFAULT` (`14`), потому что до
`copyin()` в ветке `do_copyin_devpath` дело не доходило.

Прежняя редакция этого раздела утверждала, что `mount_common` сдвигал
`fsmountargs` на 8 байт и APFS получала 324 байта стекового мусора. Этот код
(`fsmountargs += sizeof(devpath)`, строка 1520) в нашем вызове **не
исполнялся** — разбор `fsmountargs` начинается уже после guard'а. Более того,
при `KERNEL_MOUNT_BASESYSTEMROOT` указатель на путь берётся из kernel-памяти
как `char **`, а при `VOLBYROLE` весь блок разбора пропускается
(`mount_common()`, строка 1490, исключает `KERNEL_MOUNT_VOLBYROLE_MASK`), так
что сдвиг не срабатывает ни в одном из доступных нам вариантов.

Полезно помнить: `CONFIG_ROSV_STARTUP`, `CONFIG_MOUNT_VM` и
`CONFIG_BASESYSTEMROOT` в этой сборке **включены** (видны как `-D` в
`BUILD/obj/RELEASE_X86_64/**/*.o.json`), то есть mount-by-role и base-root
пути в ядре есть — в отличие от того, что предполагалось в первой редакции.

#### 3. Маршрутизация при `KERNEL_MOUNT_BASESYSTEMROOT` и `_container_rootmount`

Когда флаг `KERNEL_MOUNT_BASESYSTEMROOT` (`0x80` из `<sys/mount_internal.h>`)
передаётся в `kernel_mount()`:
1. `mount_common()` корректно читает путь `devpath = *devnamepp` без лишнего
   сдвига.
2. `fsmountargs` явно сбрасывается в `USER_ADDR_NULL`.
3. Сегмент поиска переключается в системное пространство (`UIO_SYSSPACE`).
4. Внутри `apfs_vfsop_mount` срабатывает ветка `data == USER_ADDR_NULL`:
   буфер аргументов обнуляется (`bzero`), поэтому `mount_mode = 0`.
5. Дальше — **ожидание, а не проверенный факт** (подтвердить может только
   загрузка): режим `mount_mode == 0` по таблице переходов уводит выполнение в
   `_container_rootmount(devvp, ...)` (смещение `0x55568`):
   - `_container_rootmount` проверяет, является ли устройство ramdisk'ом
     (`_rootedRamdisk` по префиксу `md`).
   - Для дисковых устройств (`disk0`) берёт `vnode_specrdev(devvp)` и ищет
     соответствующий `IOMedia` в IORegistry (символа `lookup_registry_devno`
     в бинарнике нет — вероятно, инлайнен или назван иначе).
   - Выполняет декомпозицию контейнера (`_container_decompose`).
   - Находит объект `AppleAPFSMedia` тома в контейнере и извлекает из реестра
     его свойства `"BSD Major"` и `"BSD Minor"`.
   - Конструирует `dev_t` тома, через `bdevvp()` получает vnode тома
     (соответствующий `disk0s1`) и штатно монтирует файловую систему APFS.
   Если это так, узел `/dev/disk0s1` для монтирования не нужен — `dev_t`
   собирается из реестра.

#### 4. Проверка ARV при монтировании контейнера

В логе инициализации контейнера наблюдалась строчка:
```
authenticate_efi_forwarded_roothash:3984: evaluating authenticity of root hash
populate_value_from_memory_descriptor:14523: populate_value_from_memory_descriptor md is NULL
apfs_extract_root_hash_and_manifest_x86:14579: populate_value_from_memory_descriptor for root hash failed: 22
authenticate_efi_forwarded_roothash:3989: apfs_extract_root_hash_and_manifest failed with error: Invalid argument (22)
```
Дизассемблирование `authenticate_efi_forwarded_roothash` показало, что проверка
ARV (Authenticated Root Volume) активируется, когда роль тома установлена в
`system` (`0x0001`), а загрузчик EFI не передал хеш корневой файловой системы
(`md is NULL`). Код функции на строке 3989 логирует предупреждение (`_log_warn`),
после чего зануляет возвращаемое значение (`xorl %r15d, %r15d`) и возвращает 0.
Это предупреждение **не является фатальным** и не прерывает инициализацию схемы
контейнера.

#### 5. Что изменено в коде

В `crossxnu_mount_apfs_volume()` (`upstream/xnu/bsd/kern/bsd_init.c` и патч
`patches/0028-bringup-tracing.patch`):
1. К вызову `kernel_mount` добавлен `KERNEL_MOUNT_BASESYSTEMROOT` (`0x80`):
   `(KERNEL_MOUNT_NOAUTH | KERNEL_MOUNT_BASESYSTEMROOT)`. Он снимает guard из
   §2 и заодно велит VFS трактовать `fsmountargs` как kernel-указатель
   `char **`. По комментарию в `<sys/mount_internal.h>` этот флаг и предназначен
   для «монтирования базового корневого тома вместо полного» во время
   `bsd_init()` — ровно наш случай.
2. Если первая попытка вернула ошибку — повтор без `MNT_RDONLY` (только
   `MNT_DONTBROWSE`). Это не про «незафиксированные транзакции»: просто
   дешёвый способ в одном прогоне проверить, не отвергает ли APFS read-only
   монтирование.
3. Кандидаты перебираются от узла тома к контейнеру: `/dev/disk0s1`,
   `/dev/disk0s2`, `/dev/disk0s3`, `/dev/disk0`.

Статус: собирается, серия патчей консистентна (`0028` реверсится чисто), и
**загрузкой подтверждено** — см. §11.7.


### 11.7 Том APFS смонтирован (`mount -t apfs /dev/disk0 /mnt1 -> 0`)

Прогон `build/serial-mnt6.log`:

```
crossxnu: no APFS volume node yet, polling
CrossXnuRAMStorage: 8388608 bytes at <ptr>, 2048 blocks of 4096
crossxnu: mount -t apfs /dev/disk0 /mnt1 -> 0
apfs_vfsop_mount:2886: disk1s1 failed to find named root snapshot: Need authenticator (81)
apfs_log_op_with_proc:3197: disk1s1 mounting volume crossxnu, requested by: kernel_task (pid 0)
handle_mount:903: disk1s1 setting dev block size to 4096 from 512
apfs_log_op_with_proc:3197: disk1s1 mount-complete volume crossxnu
```

Что это подтверждает:

- `EINVAL` действительно давал guard в `mount_common` (§11.6.2), а не APFS:
  с `KERNEL_MOUNT_BASESYSTEMROOT` тот же вызов проходит.
- Ветка `data == NULL` ведёт в контейнерно-корневое монтирование, и `dev_t`
  тома берётся из IORegistry: узел `/dev/disk0s1` не нужен, APFS сама
  публикует `disk1s1` (том `crossxnu`) и монтирует его.
- Строка `failed to find named root snapshot: Need authenticator (81)` —
  ожидаемая: хеш корня загрузчик не передаёт, permissive-профиль это
  допускает, монтирование продолжается.

Чего это не даёт: `launchd` по-прежнему стартует с HFS-корня (`md0`) и пишет
`Not booted from APFS, skipping apfs_boot_util`; том пустой и висит на
`/mnt1`, поэтому поведение `launchd` не меняется — он останавливается там же,
где и до правки. Чтобы монтирование на что-то влияло, том APFS должен **быть
корнем** (pivot, как делает `imageboot.c` для BaseSystem) и **быть
наполненным**.

Ограничение по размеру: образ APFS лежит сегментом `__APFSIMG` в KC, а KC
должен оставаться ниже `0x2800000` (bootinfo) — то есть на образ остаётся
~8 МБ. Настоящий System-том туда не влезет. Выход — реальный диск вместо
сегмента; в KDK есть x86_64-срезы у `AppleAHCIPort` и `IONVMeFamily`
(`AppleVirtIOStorage` по-прежнему только arm64e, virtio-blk закрыт).

## 12. Настоящий диск: APFS-том на AHCI (2026-10-31)

Потолок из §11.7 (~8 МБ на образ, пока он лежит сегментом в KC) снят: том
APFS теперь живёт в файле на хосте и отдаётся гостю через AHCI. Размер
выбирается какой угодно — 256 МиБ в проверке ниже, дальше можно гигабайты.

### 12.1 Почему свой драйвер, а не Apple-стек

Стек Apple требовал бы `IOPCIFamily` плюс PCI-нубы (в macOS их публикует
ACPI/`AppleACPIPlatform`), а в этом ядре нет ни ACPI, ни `IOPCIFamily`:
платформенный экспертиз — наш заглушечный (`crossxnu: using built-in platform
expert stub for "ACPI"`). В KDK при этом есть x86_64-срезы у `IOAHCIFamily`,
`IOPCIFamily`, `AppleAHCIPort`, `IONVMeFamily`, но `IONVMeFamily` тянет
`AppleARMPlatform`, `AppleSMC`, `AppleEmbeddedPCIE`, `RTBuddy`, а
`AppleVirtIOStorage` остаётся arm64-only (virtio-blk закрыт, §10).

Поэтому AHCI реализован прямо в нашем kext'е — тем же способом, что и
RAM-бэкенд: `IOBlockStorageDevice` → `IOBlockStorageDriver` → `IOMedia` →
APFS. Кекст называется `com.crossxnu.driver.CrossXnuBlockStorage`
(`tools/blockstorage-kext/blockstorage.cpp`) и выбирает бэкенд в `start()`:
AHCI, если найден диск, иначе сегмент `__APFSIMG`.

Что понадобилось и чем это сделано:

| Задача | Решение |
| --- | --- |
| найти контроллер | PCI config space механизмом #1 через порты `0xCF8/0xCFC` (класс `0x010601`), `inl`/`outl` инлайновым ассемблером |
| включить декодирование | `PCI_COMMAND` = memory space + bus master |
| отобразить ABAR | `IOMemoryDescriptor::withPhysicalAddress()` + `map(kIOMapAnywhere \| kIOMapInhibitCache)` |
| DMA-память | `IOMallocContiguous()` (command list 1 КиБ/1 КиБ, command table 4 КиБ/128 Б, bounce 256 КиБ) |
| команды | `IDENTIFY` (0xEC), `READ DMA EXT` (0x25), `WRITE DMA EXT` (0x35), один слот, один PRDT-элемент |
| ёмкость | слова 100–103 IDENTIFY (LBA48), блок 512 байт |

### 12.2 Две ошибки, которые нашлись по логам

1. **«port never went idle»** (`kIOReturnTimeout`, `0xE00002D6`) на обоих
   портах. Проверка простоя ждала `PxCI == 0 && PxCMD.CR == 0`, но `CR`
   поднят всё время, пока поднят `ST`, — условие невыполнимо. Правильно ждать
   только `PxCI == 0`; `CR` проверяется отдельно, после снятия `ST`.
2. **Выбран не тот диск.** Эвристика «самый большой» выбрала ESP (1.2 ГиБ,
   FAT) вместо образа APFS (256 МиБ), и APFS ожидаемо ответила `ENOENT`.
   Заменено на содержательную проверку: читаем блок 0 и смотрим магию `NXSB`
   по смещению `0x20` (§11.1). Теперь лог сам говорит, что на порту:
   `port 0: block 0 is not APFS`, `port 1: block 0 is APFS (NXSB)`.

Отдельная грабли: после переименования kext'а я пересобрал KC, но не ядро —
`bsd_init.c` продолжал просить `...CrossXnuRAMStorage`, kext не загружался
(в логе ни одной его строки), и молча работал только RAM-бэкенд. Правило:
меняется идентификатор — пересобирается и ядро.

### 12.3 Прогон

`build/apfs256.img` (mkapfs + роль system), `build/serial-ahci4.log`:

```
CrossXnuBlockStorage: AHCI at 00:1f.2 (vendor 8086 device 2922)
CrossXnuBlockStorage: ABAR 81084000 cap c0141f05 pi 0000003f
CrossXnuBlockStorage: port 0 attached, sig 00000101
CrossXnuBlockStorage: port 0: 2457601 sectors (1200 MiB) "QEMU HARDDISK"
CrossXnuBlockStorage: port 0: block 0 is not APFS
CrossXnuBlockStorage: port 1 attached, sig 00000101
CrossXnuBlockStorage: port 1: 524289 sectors (256 MiB) "QEMU HARDDISK"
CrossXnuBlockStorage: port 1: block 0 is APFS (NXSB)
CrossXnuBlockStorage: using port 1, 524289 sectors (APFS)
apfs: disk1s1 mounting volume ahtest, requested by: kernel_task (pid 0)
apfs: disk1s1 mount-complete volume ahtest
crossxnu: mount -t apfs /dev/disk0 /mnt1 -> 0
```

### 12.4 Как повторить

```
# 256 МиБ образ APFS с ролью system
tools/bringup/make-apfs-image.sh 256M build/apfs256.img ahtest
python3 tools/kext-loader/apfs-set-role.py --role system build/apfs256.img

# kext + коллекция (второй аргумент "none" — без сегмента __APFSIMG)
python3 tools/kext-loader/build-blockstorage-kext.py
tools/kext-loader/build-apfs-image-kc.sh /tmp/kdkroot/System/Library/Extensions build/apfs8.img
mcopy -o -i build/esp32.img build/kernel.kc ::/EFI/BOOT/kernel

# загрузка со вторым диском на AHCI
pwsh -File tools/kext-loader/boot-serial.ps1 -Log build/serial-ahci.log -Seconds 240 `
  -ExtraArgs '-drive','file=build/apfs256.img,format=raw,if=ide,index=1'
```

Что дальше: сегмент `__APFSIMG` больше не нужен (KC можно собирать с `none`
и он станет меньше), а том всё ещё пустой и висит на `/mnt1` — чтобы это
меняло поведение launchd, его надо наполнить и сделать корнем (§11.7).
