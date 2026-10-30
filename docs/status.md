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
| 2026-10-30 | **HFS+ пишется**: свежий том монтируется, `mkdir -p`, запись/чтение файла и `df` работают (`/dev/md1 on /private/var (hfs, local)`) || 2026-10-30 | `launchd` с записываемым `/var`: убраны `security-critical blob` и `Text page corruption` (permissive: не enforced launch constraints и cdhash текстовых страниц), SIGILL остался настоящим `#UD` || 2026-10-30 | SIGILL в `launchd` опознан: `__pthread_workqueue_supported` в libsystem_pthread делает `trap` со строкой `BUG IN LIBPTHREAD: libpthread has not been initialized` — не хватает `com.apple.kec.pthread` || 2026-10-30 | Встроенная таблица `pthread_functions` вместо kext'а: `launchd` прошёл trap «libpthread has not been initialized» (маска возможностей в `bsdthread_register`), упёрся в libdispatch (`Unable to limit cooperative pool size`) || 2026-10-30 | libdispatch прошёл `wq_limit_cooperative_threads` (permissive: запрос игнорируется без workqueue) и упёрся в `Root queue initialization failed` — нужны настоящие workqueue-потоки || 2026-10-30 | Первый заход на `bsdthread_create` (`thread_create_immovable` + `thread_set_wq_state64` + порт) ломал `load_init_program` — откатан до `ENOTSUP`; нужен поэтапный разбор || 2026-10-30 | `bsdthread_create` проверен по шагам: поток создаётся, состояние (`rip/rsp/rdi/rsi/rdx`) читается обратно, порт отдаётся; новый поток сразу ловит trap в libpthread, из-за чего pid 1 умирает || 2026-10-30 | `bsdthread_create` разобран по трапам libpthread: нужен `rdi = pthread_t`, `r9 = 0x10000000`, `thread_set_tsd_base`; дальше упор в поле порта `pthread+0xf8` || 2026-10-30 | `bsdthread_create` заработал (поток создаётся приостановленным, порт отдаётся через retval) — pid 1 переживает создание потоков || 2026-10-30 | Сняты атрибуты `bsdthread_create`: `flags=0x90008ff`, `wqthread = threadstart-0x14`; для workqueue-потоков нужна отдельная точка входа |