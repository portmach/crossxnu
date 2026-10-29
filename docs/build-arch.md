# Сборка crossxnu на Arch Linux

> **Security:** phase 1 работает в permissive-режиме. TrustCache и
> CodeSignature не обеспечивают защиту macOS; см. [`../SECURITY.md`](../SECURITY.md).

Документ описывает **проверенный** путь: Arch Linux x86_64 в WSL2, без
macOS, без Xcode, без Apple SDK. Все команды выполняются внутри WSL.

## 1. Требования к хосту

| Параметр | Минимум | Рекомендуется |
|:---------|:--------|:--------------|
| ОС | Arch Linux x86_64 (rolling) | Arch Linux в WSL2 |
| Ядро | Linux 6.x | актуальное |
| CPU | 4 ядра | 8+ ядер |
| RAM | 8 ГБ | 16+ ГБ |
| Диск | 20 ГБ свободно | 30+ ГБ (BUILD + логи) |
| Файловая система | ext4/btrfs внутри WSL | **не** `/mnt/c` |

Сборка XNU — это ~14 000 единиц трансляции, LTO и финальная компоновка.
На 8 ядрах RELEASE-ядро собирается десятки минут; на 4 ядрах — заметно
дольше. 8 ГБ RAM хватает, но при `-j$(nproc)` возможен OOM на LTO-этапе.

> **WSL:** держите исходники и `build/` в `~/...` (ext4 внутри виртуального
> диска WSL). `/mnt/c/...` — это 9p; метаданные и мелкие файлы работают
> на порядок медленнее, а XNU состоит из мелких файлов.

## 2. Зависимости

### 2.1. Пакеты Arch

```bash
sudo pacman -S --needed \
    base-devel clang lld llvm git python \
    bison flex m4 bc rsync cpio xz zstd perl
```

| Пакет | Зачем |
|:------|:------|
| `clang`, `lld`, `llvm` | целевой компилятор и Mach-O линкер `ld64.lld`; `llvm-ar`, `llvm-strip`, `llvm-nm`, `llvm-otool`, `llvm-lipo` |
| `make` (base-devel) | сборочная система XNU |
| `git` | submodules и патчи |
| `python` | `availability.pl`, вспомогательные скрипты |
| `bison`, `flex`, `m4` | парсер/лексер для MIG и `SETUP/config` |
| `bc`, `rsync`, `cpio`, `xz`, `zstd`, `perl` | генерация, упаковка, `newvers.pl` |

Проверка версий:

```bash
clang --version          # проверено на 23.1.4
ld64.lld --version
llvm-ar --version
bison --version
flex --version
```

`clang` должен быть достаточно новым: XNU 26.5 использует C++23
(`-std=gnu++2b`), `-fapple-kext`, `-mkernel`, `-fbounds-safety`-пробы и
LLVM LTO. Слишком старый clang (≤ 17) не подойдёт.

### 2.2. Что **не** требуется

- macOS, Xcode, Command Line Tools;
- Apple SDK (`MacOSX*.sdk`), KDK;
- Apple `cctools` (`ld`, `libtool`, `strip`, `nm`, `otool`, `lipo`);
- Apple `mig`/`migcom`, `ctfconvert`, `ctfmerge`, `keystsymboltool`,
  `codesign`, `iig`.

Всё это заменяется LLVM-инструментами, сборкой Apple open source
(`bootstrap_cmds`, `AvailabilityVersions`) и host-compat слоем из
[`toolchain/`](../toolchain).

## 3. Исходники и версии

```bash
git clone --recurse-submodules https://github.com/portmach/crossxnu.git
cd crossxnu
git submodule status
```

Зафиксировано:

| Компонент | Версия | Зачем |
|:----------|:-------|:------|
| `upstream/xnu` | `xnu-12377.121.6` | ядро |
| `upstream/bootstrap_cmds` | `bootstrap_cmds-138` | MIG |
| `upstream/AvailabilityVersions` | master (pinned commit) | `availability.pl` для `sys/_symbol_aliasing.h` |
| `upstream/libdispatch` | `libdispatch-1542.100.32` | `libfirehose_kernel` (следующий шаг) |

Если submodules не подтянулись:

```bash
./scripts/fetch-deps.sh
```

`fetch-deps.sh` клонирует недостающие репозитории в `upstream/` и
переключает их на зафиксированные коммиты. Он не делает `sudo` и не
ставит пакеты.

## 4. Bootstrap: один раз на дерево

```bash
./scripts/bootstrap.sh
```

Что происходит:

1. **Проверка хоста** — Linux, x86_64, наличие clang/lld/make/bison/flex.
2. **Патчи XNU** — `patches/series` применяется к `upstream/xnu`
   (см. [`patches.md`](patches.md)). Дерево должно быть чистым; скрипт
   делает `git checkout -- .` и применяет серию заново.
3. **MIG** — `bootstrap_cmds/migcom.tproj` собирается host-clang в
   `build/mig/migcom`; драйвер `mig` адаптируется под Linux
   (`/usr/bin/arch` → `uname -m`).
4. **Host-compat** — `toolchain/lib/hostcompat.c` собирается в
   `toolchain/lib/libhostcompat.a` (`getprogname`, `setmode`, `getmode`,
   `fcopyfile`, `uuid_generate`, `NXGetLocalArchInfo`).
5. **Synthetic SDK** — `build/sdk/`:
   - `usr/local/libexec/availability.pl` + `availability.dsl`;
   - `usr/include/mach-o/*` из `EXTERNAL_HEADERS`;
   - `usr/local/include/kernel/{firehose,DriverKit}`;
   - пустые `Kernel.framework/.../PrivateHeaders/{AppleFeatures,platform}`,
     чтобы `-Wmissing-include-dirs` не срабатывал;
   - `usr/local/include/iBoot`.
6. **Проверка** — печатает версии и путь к SDK.

Bootstrap **не** собирает ядро. Это отдельный шаг, чтобы можно было
пересобирать ядро, не повторяя MIG/SDK.

> **Текущее ограничение (2026-10-29):** `bootstrap.sh` и
> `build.sh --target exporthdrs` проходят полностью; `build.sh` без
> `--target` доходит до компиляции объектов и останавливается на
> отсутствующих `TrustCache/API.h` / `CodeSignature/Entitlements.h`
> и на линковке (`libfirehose_kernel`, `libcc_kext`, `ld64.lld -static`).
> Это ожидаемое состояние phase 1; см. [`status.md`](status.md).

### 4.1. Ручной bootstrap (если скрипт сломался)

```bash
# MIG
./scripts/build-mig.sh
# host compat
./scripts/build-host-tools.sh
# synthetic SDK
./scripts/make-sdk.sh
# патчи
./scripts/apply-patches.sh
```

## 5. Сборка ядра

```bash
./scripts/build.sh --arch x86_64 --config RELEASE --jobs "$(nproc)"
```

Скрипт:

- выставляет `SDKROOT_RESOLVED`, `SDKROOT`, `SDKVERSION=26.5`,
  `PLATFORM=MacOSX`, `RC_DARWIN_KERNEL_VERSION=12377.121.6`;
- подменяет `CC/CXX/HOST_CC/MIG/MIGCOM/LIBTOOL/STRIP/NM/OTOOL/LIPO/UNIFDEF/...`
  на `toolchain/bin/*`;
- отключает CTF/dSYM (`DO_CTFMERGE=0`, `BUILD_DSYM=0`) — это только
  отладочные метаданные, не код ядра;
- добавляет `CFLAGS_EXTRA` с подавлением новых диагностик clang 23,
  которых не было в Apple clang (см. [`compatibility.md`](compatibility.md));
- пишет лог в `build/log/`.

Эквивалент без обёртки (сокращённо; полный набор переменных — в
`scripts/build.sh`):

```bash
make -C upstream/xnu -j"$(nproc)" \
    XCRUN="$PWD/toolchain/bin/xcrun" \
    SDKROOT_RESOLVED="$PWD/build/sdk" \
    SDKVERSION=26.5 PLATFORM=MacOSX \
    HOST_SDKROOT_RESOLVED=/ HOST_OS_VERSION=26.5 \
    CC="$PWD/toolchain/bin/clang" CXX="$PWD/toolchain/bin/clang++" \
    HOST_CC="$PWD/toolchain/bin/clang-host" \
    MIG="$PWD/build/mig/mig" MIGCOM="$PWD/build/mig/migcom" \
    LIBTOOL="$PWD/toolchain/bin/libtool" STRIP="$PWD/toolchain/bin/strip" \
    NM="$PWD/toolchain/bin/nm" OTOOL="$PWD/toolchain/bin/otool" \
    LIPO="$PWD/toolchain/bin/lipo" UNIFDEF="$PWD/toolchain/bin/unifdef" \
    BUILD_DSYM=0 DO_CTFMERGE=0 \
    RC_DARWIN_KERNEL_VERSION=12377.121.6 \
    ARCH_CONFIGS=X86_64 KERNEL_CONFIGS=RELEASE \
    all
```

### 5.1. Варианты конфигурации

| `--config` | Флаги | Назначение |
|:-----------|:------|:-----------|
| `RELEASE` | `-O2`, assertions off | первый целевой вариант, ближе всего к Apple RELEASE |
| `DEVELOPMENT` | `-O2`, assertions on | отладка |
| `DEBUG` | `-O0` | только для расследования |

Начинайте с `RELEASE`: он меньше и быстрее линкуется. `DEVELOPMENT`
потребует больше диска и времени.

`arm64` пока не поддерживается: нужен `KDKROOT`, `libTightbeam`,
`TrustedExecutionMonitor` и отдельная проверка указателей/PAC. После
стабилизации x86_64 — см. [`status.md`](status.md).

## 6. Результат и проверка

Ожидаемые артефакты:

```
upstream/xnu/BUILD/obj/RELEASE_X86_64/kernel
upstream/xnu/BUILD/obj/RELEASE_X86_64/kernel.unstripped
upstream/xnu/BUILD/obj/RELEASE_X86_64/kernel.dSYM/      (если BUILD_DSYM=1)
```

Проверка Mach-O:

```bash
file upstream/xnu/BUILD/obj/RELEASE_X86_64/kernel
# Mach-O 64-bit x86_64 executable

llvm-otool -hv upstream/xnu/BUILD/obj/RELEASE_X86_64/kernel
llvm-otool -l  upstream/xnu/BUILD/obj/RELEASE_X86_64/kernel | head -80
llvm-nm -g     upstream/xnu/BUILD/obj/RELEASE_X86_64/kernel | head
```

Критерий phase 1 — не «файл существует», а:

1. это `MH_EXECUTE`/`MH_PIE` Mach-O x86_64;
2. сегменты `__TEXT`, `__DATA`, `__LINKEDIT`, `__HIB` на месте;
3. таблица экспортируемых символов совпадает с Apple-сборкой того же тега
   (см. [`compatibility.md`](compatibility.md));
4. `syscalls.master` и `mach_trap_table` не разошлись.

## 7. Чистая пересборка

```bash
rm -rf upstream/xnu/BUILD build/log
./scripts/build.sh --arch x86_64 --config RELEASE
```

Полный сброс с патчами:

```bash
git -C upstream/xnu checkout -- .
./scripts/bootstrap.sh
```

## 8. Частые проблемы

| Симптом | Причина | Решение |
|:--------|:--------|:--------|
| `xcrun: unsupported invocation` | вызван системный `xcrun`, а не шим | проверьте `XCRUN=$PWD/toolchain/bin/xcrun`, `PATH` |
| `no such include directory: .../usr/local/include/kernel` | не выполнен `make-sdk.sh` | `./scripts/make-sdk.sh` |
| `def: No such file or directory` | собирается DriverKit/IIG | патчи 0002/0003 должны исключать DriverKit; проверьте `patches/series` |
| `unknown builtin '__builtin_xnu_type_*'` | upstream clang не имеет Apple builtin | патчи 0004/0005; см. `compatibility.md` |
| `ld64.lld: warning: Option '-static' is not yet implemented` | LLD ещё не умеет static | временно: пост-обработка Mach-O или патч LLD; см. `status.md` |
| `undefined symbol: __firehose_*` | не собрана `libfirehose_kernel` | `scripts/build-firehose.sh` (после реализации) |
| OOM на LTO | мало RAM | `--jobs 2`, увеличить RAM/WSL memory |
| Медленно на `/mnt/c` | 9p | перенести дерево в `~/src` |

## 9. WSL2: практические заметки

- Выделите WSL 12–16 ГБ RAM в `%UserProfile%\.wslconfig`:
  ```ini
  [wsl2]
  memory=16GB
  processors=8
  ```
  затем `wsl --shutdown`.
- `df -h /` должен показывать десятки гигабайт; при нехватке —
  `wsl --manage archlinux --resize` (или `wsl --shutdown` + `diskpart`).
- Не собирайте в `/mnt/c/Users/...`; клонируйте репозиторий в
  `~/src/crossxnu`.
- `sudo` в bootstrap не нужен; пакеты ставятся отдельно, вручную.
