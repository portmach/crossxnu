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

## 8. Kext-загрузчик: что выяснено (2026-10-31)

Цель блока — проверить, что наш порт умеет загрузить сторонний kext, прежде
чем браться за `AppleAPFS.kext`. Собран минимальный kext
`tools/hello-kext` (`com.crossxnu.hello`), который в `start()` печатает
строку в консоль.

### 8.1 Динамической загрузки kext'ов в xnu-12377 нет

`kxld` в этой версии **не собирается**:

- `libkern/RELEASE/config_kxld.h` содержит `#define NCONFIG_KXLD 0`;
- `options CONFIG_KXLD` есть в `config/MASTER` (строка 541), но **ни одна**
  группа (`RELEASE`/`DEVELOPMENT`/`DEBUG`) его не перечисляет, поэтому в
  `CONFIG_DEFINES` его нет и `libkern/kxld/*.c` (`optional config_kxld`) в
  сборку не попадают;
- соответственно `OSKext::loadFromMkext`, `loadKextWithIdentifier` для
  не-prelinked kext'ов и `kextd`-протокол вырезаны препроцессором.

Вывод: единственный поддерживаемый в этой XNU путь — **prelinked kext из
kernel collection** (`__PRELINK_TEXT` + `__PRELINK_INFO`). Именно так macOS
загружает и `AppleAPFS.kext`, так что для APFS нужен не свой kxld, а сборка
и загрузка KC/AuxKC.

### 8.2 kext собирается и линкуется в KC

- `build/dis/build-hello-kext.py` берёт аргументы компиляции из
  `compile_commands.json` ядра (включая `-DKERNEL -DMACH_KERNEL_PRIVATE` и
  все `-I EXPORT_HDRS/...`) и линкует `ld64 -kext -undefined dynamic_lookup`.
  Важно: подключать `<sys/systm.h>` нельзя — экспортированные bsd-заголовки
  смешивают kernel- и userland-версии `<sys/types.h>`, и на `clock_t`/
  `int32_t` всё падает. Минимальный рабочий набор — `<mach/kmod.h>` +
  `<kern/misc_protos.h>` (проверяется `build/dis/probe-kext-includes.py`).
- `kc-builder` линкует kext против таблицы символов ядра (24 265 символов),
  патчит `kmod_info` и кладёт код в `__PRELINK_TEXT`; `build/hello.kc`
  (MH_FILESET, 17 207 296 байт) грузится **нашим же EFI-загрузчиком** и ядро
  стартует с него так же, как с обычного `MH_EXECUTE`.

### 8.3 Найденные баги kc-tools

1. `kmod_info.start/stop` оставались «голыми» смещениями (`0xf50`, `0xf70`):
   ld64 оформляет их локальными релокациями, а `link_kext` перебазирует
   только внешние символы. OSKext отказывался стартовать kext
   (`module start pointer is outside of kext range` →
   `kOSKextReturnInternalError`). Фикс — `patches/kc-tools/0002-*`,
   генератор `build/dis/fix-kc-tools-kmod-start.py`.
2. Остаётся: `call printf` внутри текста kext'а после линковки имеет
   `rel32 = 0` (`e8 00 00 00 00`), то есть BRANCH-релокация на внешний
   символ не применяется; из-за этого kext «стартует», но паникует на
   возврате/вызове (`Data/Stack execution not permitted`). Это следующий
   баг kc-tools, который надо закрыть до APFS.

### 8.4 Что уже подтверждено в рантайме

- Kext из `__PRELINK_INFO` регистрируется: `Kext com.crossxnu.hello, v1.0
  registered and available for loading`.
- Хук в `bsd_init()` (`OSKextLoadKextWithIdentifier`) доводит загрузку до
  `calling module start function` — то есть путь prelinked-kext'а в нашем
  ядре работает.
- `com.apple.kpi.*` приходится добавлять в KC как codeless-kext'ы
  (`scripts/build-fileset.sh --with-kpi`), иначе зависимости не разрешаются.

### 8.5 Следующие шаги

1. Починить BRANCH-релокации внешних символов в `link_kext` (kc-tools) —
   после этого `hello.kext` должен реально печатать строку.
2. Собрать Aux/Pageable-KC из реального `AppleAPFS.kext`, извлечённого из
   `BootKernelExtensions.kc` (kc-tools умеет только собирать, экстрактора
   нет — писать свой), и загрузить его тем же путём.
