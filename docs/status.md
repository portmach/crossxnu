# Статус сборки

> Обновлено: 2026-10-29. Всё, что здесь написано, проверялось на
> Arch Linux x86_64 в WSL2, clang 23.1.4, XNU `xnu-12377.121.6`.

## 1. Матрица

| Хост | Target | Конфигурация | Статус |
|:-----|:-------|:-------------|:-------|
| Arch Linux (WSL2), x86_64 | `x86_64-apple-macos26.5` | `RELEASE` | компиляция объектов идёт; линковка не завершена |
| Arch Linux, x86_64 | `x86_64-apple-macos26.5` | `DEVELOPMENT` | не проверялось |
| Arch Linux, x86_64 | arm64 | — | не поддерживается (нужен KDK/Tightbeam/SPTM) |
| macOS | любой | — | вне scope |

## 1.1. Security status

**Phase 1 — permissive.** TrustCache и CodeSignature не обеспечивают
security-модель macOS: подпись/доверие/entitlements не enforced. Это
осознанное решение, а не «пока не заметили». См. [`../SECURITY.md`](../SECURITY.md)
и [`security-policy.md`](security-policy.md).

Пока ядро не линкуется и не грузится, permissive-режим — **заявленный
профиль**, а не проверенная runtime-функция.

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
      `libsa`, `security` (тысячи объектов; см. лог).
- [x] `RELEASE`/`x86_64` флаги совпадают с Apple-схемой (`-O2`, `-mkernel`,
      `-fapple-kext`, `-fno-rtti`, `-fno-exceptions`).
- [ ] Все объекты — в процессе; новые диагностики clang 23
      подавляются в `scripts/build.sh` (`CFLAGS_EXTRA`).

## 3. Блокеры линковки (по состоянию на 2026-10-29)

| # | Блокер | Что нужно | Риск для ABI |
|:--|:-------|:----------|:-------------|
| 1 | Mach-O layout: `__TEXT.vmaddr=0`, флаг `DYLDLINK`, `-static`/`-segaddr`/`-image_base` не реализованы в `ld64.lld` | перейти на cctools-port `ld64` или пост-обработка Mach-O | **высокий** |
| 2 | DriverKit ABI | `iig-port` уже генерирует; сравнить vtable/символы с Apple 26.5 | средний: DriverKit ABI |
| 3 | `libcc_kext` — shim, не реальный C++ runtime | собрать/подключить Apple-совместимый `libcc_kext` | средний |
| 4 | `__builtin_xnu_type_*` | fallback-патчи 0004/0005 | средний (hardening) |
| 5 | `libTightbeam` | только для arm64/новых платформ | нет для x86_64 |

## 4. Как воспроизвести текущее состояние

```bash
git clone --recurse-submodules https://github.com/portmach/crossxnu.git
cd crossxnu
./scripts/bootstrap.sh
./scripts/build.sh --arch x86_64 --config RELEASE --jobs "$(nproc)"
```

Ожидаемый результат на текущем этапе: DriverKit генерируется через
`iig-port`, все объекты компилируются, `libfirehose_kernel` и
`libcc_kext`-shim подставляются, **`kernel` линкуется**. Но Mach-O пока
непригоден для загрузки: `__TEXT.vmaddr=0`, флаг `DYLDLINK`, потому что
`ld64.lld` игнорирует `-static`/`-segaddr`/`-image_base`. Это **не**
считается успехом phase 1; критерий — правильный Mach-O и совпадающая
таблица символов.

## 5. Ближайшие шаги

1. Перейти на cctools-port `ld64` (Apple-совместимый линкер) или
   пост-обработка Mach-O:
   - `-static`, `-segaddr`, `-image_base`, `-alias_list`;
   - убрать `MH_DYLDLINK`/`LC_DYLD_*`, выставить `__TEXT.vmaddr`.
2. Проверить `kextsymboltool`/symbolsets на реальном `ld64`.
3. Собрать полноценный `libcc_kext` вместо shim.
4. Сравнить symbol table и DriverKit vtable с Apple-сборкой
   `xnu-12377.121.6`.
5. Повторить для `DEVELOPMENT`, затем для `arm64`.

## 6. Журнал

| Дата | Событие |
|:-----|:--------|
| 2026-10-29 | Зафиксирован `xnu-12377.121.6`; собран MIG; `make exporthdrs` проходит; начата компиляция объектов |
| 2026-10-29 | Добавлены fallback'и для Apple builtins; исключён DriverKit; собираются `osfmk`/`bsd`/`iokit` объекты |
| 2026-10-29 | Открыты блокеры: `libfirehose_kernel`, `libcc_kext`, `ld64.lld -static` |
