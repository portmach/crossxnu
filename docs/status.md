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
| 1 | DriverKit/IIG (`IODMACommand::CompleteDMA` и следующие) | **отложено до phase 5**; см. [`driverkit.md`](driverkit.md) | средний: DriverKit ABI |
| 2 | `libfirehose_kernel.a` отсутствует | собрать `firehose_buffer.c` из `libdispatch` с MIG-заголовками | нет (код Apple) |
| 3 | `-lcc_kext` отсутствует | собрать `compiler-rt` builtins под `x86_64-apple-darwin` | нет |
| 4 | `ld64.lld` не умеет `-static` | обновить LLD / пост-обработка Mach-O / свой упаковщик | **высокий** |
| 5 | `__builtin_xnu_type_*` | fallback-патчи 0004/0005 | средний (hardening) |
| 6 | `libTightbeam` | только для arm64/новых платформ | нет для x86_64 |

## 4. Как воспроизвести текущее состояние

```bash
git clone --recurse-submodules https://github.com/portmach/crossxnu.git
cd crossxnu
./scripts/bootstrap.sh
./scripts/build.sh --arch x86_64 --config RELEASE --jobs "$(nproc)"
```

Ожидаемый результат на текущем этапе: сборка доходит до
`iokit/Kernel/IODMACommand.cpp` и останавливается на
`IODMACommand::CompleteDMA` — это **осознанно отложенный DriverKit**.
До линковки (`libfirehose_kernel`/`libcc_kext`, `ld64.lld -static`)
дело пока не доходит. Это **не** считается успехом phase 1; критерий —
готовый Mach-O и совпадающая таблица символов.

## 5. Ближайшие шаги

1. Собрать `libfirehose_kernel.a`:
   - MIG для `firehose.defs`/`firehose_reply.defs`;
   - `firehose_buffer.c` с `-DKERNEL=1`;
   - положить в `build/sdk/usr/local/lib/kernel/`.
2. Собрать `libcc_kext.a` из compiler-rt builtins.
3. Довести `ld64.lld`-линковку:
   - проверить `-static`/`-add_split_seg_info`/`-kernel`;
   - при необходимости — пост-обработка Mach-O (убрать `LC_DYLD_*`,
     `MH_DYLDLINK`).
4. Сравнить symbol table с Apple-сборкой `xnu-12377.121.6`.
5. Вернуть DriverKit/Exclaves после появления IIG или замены.
6. Повторить для `DEVELOPMENT`, затем для `arm64`.

## 6. Журнал

| Дата | Событие |
|:-----|:--------|
| 2026-10-29 | Зафиксирован `xnu-12377.121.6`; собран MIG; `make exporthdrs` проходит; начата компиляция объектов |
| 2026-10-29 | Добавлены fallback'и для Apple builtins; исключён DriverKit; собираются `osfmk`/`bsd`/`iokit` объекты |
| 2026-10-29 | Открыты блокеры: `libfirehose_kernel`, `libcc_kext`, `ld64.lld -static` |
