# Архитектура сборки

Этот документ объясняет, **как** XNU собирается без Apple-инструментов и
почему замены выбраны именно такие. Это не пересказ `Makefile`; здесь
зафиксированы границы замены и инварианты, которые нельзя терять.

## 1. Принцип: меняем хост, не цель

```
                 ┌──────────────────────────────┐
                 │ upstream/xnu (xnu-12377.121.6)│
                 └──────────────┬───────────────┘
                                │ make + патчи
       ┌────────────────────────┼─────────────────────────┐
       │                        │                         │
┌──────▼──────┐         ┌───────▼────────┐        ┌───────▼────────┐
│ host tools  │         │ компиляция     │        │ компоновка     │
│ SETUP/*     │         │ clang -target  │        │ ld64.lld       │
│ MIG         │         │ x86_64-apple   │        │ Mach-O         │
│ availability│         │ -mkernel       │        │ kernel         │
└──────┬──────┘         └───────┬────────┘        └───────┬────────┘
       │                        │                         │
       └────────────┬───────────┴────────────┬────────────┘
                    │                        │
             ┌──────▼──────┐          ┌──────▼──────┐
             │ synthetic   │          │ LLVM tools  │
             │ kernel SDK  │          │ (bin/)      │
             └─────────────┘          └─────────────┘
```

Целевая тройка — `x86_64-apple-macos26.5`. Компилятор — LLVM/clang,
линкер — `ld64.lld`. Ядро остаётся Mach-O; никакого ELF-«порта» нет.

## 2. Замены инструментов

| Apple | crossxnu | Почему так |
|:------|:---------|:-----------|
| `xcrun` | `toolchain/bin/xcrun` | XNU-мейкфайлы спрашивают SDK/tool path; шим отвечает из `CROSSXNU_SDK` |
| `clang`/`clang++` | `toolchain/bin/clang{++,}` | добавляют `-target x86_64-apple-macos26.5`, убирают `-arch`, включают `-fuse-ld=lld` на линковке |
| `ld` (cctools) | `ld64.lld` (через clang) | понимает Mach-O, `-filelist`, `-sectcreate`, `-segaddr`, `-exported_symbols_list` |
| `libtool` | `toolchain/bin/libtool` → `llvm-ar --format=darwin` | XNU использует только static-архивы; `llvm-libtool-darwin` не понимает `-csD`/`-ca` |
| `strip` | `llvm-strip` | Mach-O поддержан; `-S -x` совместимы |
| `nm`,`otool`,`lipo` | `llvm-nm`,`llvm-otool`,`llvm-lipo` | достаточно для проверок и XNU-правил |
| `unifdef` | `toolchain/bin/unifdef` | phase 1: копирует заголовок; `KERNEL_PRIVATE` уже задан при компиляции |
| `decomment` | `toolchain/bin/decomment` | копия; комментарии в заголовках безвредны |
| `install` (BSD) | `toolchain/bin/install` | убирает `-c -S`, сохраняет `-m` |
| `mig`/`migcom` | `build/mig/*` из `bootstrap_cmds` | Apple MIG собирается host-clang; драйвер адаптирован под Linux |
| `kextsymboltool` | собирается из `SETUP/kextsymboltool` | нужен для `System.kext`/symbol sets |
| `ctfconvert`/`ctfmerge` | отключены (`DO_CTFMERGE=0`) | только DWARF/CTF-метаданные; на код не влияет |
| `dsymutil` | `build/...dSYM` отключён | отладочный артефакт; включается отдельно |
| `codesign` | `true` | ядро не подписывается в phase 1 |
| `availability.pl` | `upstream/AvailabilityVersions` | генерирует `sys/_symbol_aliasing.h` |
| Apple SDK | synthetic SDK | заголовки XNU + `AvailabilityVersions` + DriverKit-заголовки; без Apple-бинарников |

## 3. Synthetic SDK

`build/sdk/` повторяет те пути, которые XNU ожидает от `SDKROOT`:

```
build/sdk/
├── usr/include/mach-o/                 # из EXTERNAL_HEADERS
├── usr/local/include/kernel/
│   ├── firehose/                       # из libkern/firehose
│   └── DriverKit/                      # .h из iokit/DriverKit + заглушки IIG
├── usr/local/include/iBoot/            # пусто (kernel не использует)
├── usr/local/libexec/availability.pl
└── System/Library/Frameworks/Kernel.framework/Versions/A/PrivateHeaders/
    ├── AppleFeatures/                  # пусто
    └── platform/                       # пусто
```

`-Wmissing-include-dirs` в clang 23 включён в `-Weverything` и является
ошибкой; поэтому каталоги должны существовать, даже если пусты.

### 3.1. Почему не нужен Apple SDK

Для сборки **ядра** Apple SDK нужен ради:

- `Kernel.framework/{Headers,PrivateHeaders}` — это экспортированные
  заголовки самого XNU; `make exporthdrs` создаёт их из исходников;
- `usr/local/include/kernel/{firehose,os,...}` — открытые заголовки
  libdispatch/libplatform; `firehose` уже есть в XNU;
- `usr/local/lib/kernel/libfirehose_kernel.a` — открытый libdispatch;
- `libcc_kext.a` — compiler-rt builtins, собирается из LLVM;
- `Availability.h` — открытый `AvailabilityVersions`.

Apple SDK остаётся нужен для **kext-разработки** и пользовательских
заголовков; crossxnu сознательно не поставляет его.

## 4. MIG

MIG — отдельный проект (`bootstrap_cmds`). Сборка MIG на Linux требует
двух вещей, которых нет в glibc:

1. **Darwin-типы** (`boolean_t`, `vm_offset_t`, `vm_size_t`) и заголовки
   `<mach/...>`, `<sys/types.h>` в Darwin-смысле.
2. **C11**, а не C23: в C23 `bool` — ключевое слово, а MIG использует
   `bool` как имя параметра (`strbool(boolean_t bool)`).

`scripts/build-mig.sh` собирает `migcom` с `-std=gnu11 -nostdinc` и
минимальным набором host-заголовков, а не с системным glibc. Это
изолирует MIG от конфликтов `__int64_t`/`pthread`-типов.

Драйвер `mig` — это `mig.sh` из Apple с заменой `/usr/bin/arch` на
`uname -m`; `MIGCOM`/`MIGCC` передаются через окружение.

## 5. Host-инструменты XNU

`SETUP/*` — обычные C-программы, но с macOS-зависимостями:

| Инструмент | Зависимость | Решение |
|:-----------|:------------|:--------|
| `installfile` | `<copyfile.h>`, `fcopyfile` | `toolchain/include/copyfile.h` + `libhostcompat` |
| `replacecontents` | `getprogname` | `libhostcompat` + `-include libc.h` |
| `setsegname` | `<mach-o/swap.h>`, `vm_offset_t` | минимальные Mach-O заголовки + `libhostcompat` |
| `kextsymboltool` | `<mach-o/arch.h>`, `uuid_generate` | `NXGetLocalArchInfo` + `uuid_generate` в `libhostcompat` |
| `config` | bison/flex | системные `bison`/`flex` |
| `decomment` | `<libc.h>` | `toolchain/include/libc.h` |

`clang-host` добавляет `-I toolchain/include`, `-I build/sdk/usr/include`,
`-I upstream/xnu/EXTERNAL_HEADERS` и линкует `libhostcompat`.

## 6. Патчи к XNU

Полный список — [`patches/series`](../patches/series). Кратко:

| Патч | Что делает | Влияние на ядро |
|:-----|:-----------|:----------------|
| 0001 | убирает `sysctl`/`sw_vers` из top-level make | нет; только throttle сборки |
| 0002 | исключает DriverKit из `iokit` export | нет; DriverKit не часть macOS kernel |
| 0003 | исключает DriverKit/Exclaves из `iokit/conf` | нет; см. 0002 |
| 0004 | fallback `__builtin_xnu_type_summary` | ослабляет compile-time проверки kalloc; см. compatibility |
| 0005 | fallback `__builtin_xnu_type_signature` / `types_compatible` | теряет kalloc signatures; см. compatibility |
| 0006 | убирает IIG-инъекцию `Dispatch` в `OSMetaClass` | vtable слот сохраняется, DriverKit dispatch не поддержан |

Патчи 0002/0003 — это **временное** исключение не-ядерных компонентов.
Их исходники остаются в дереве; после появления IIG/DriverKit-сборки
они будут возвращены.

## 7. Почему не CMake/Meson

В phase 0 рассматривались CMake/Meson. Для phase 1 выбран путь
«XNU make + тонкий слой совместимости», потому что:

- make-файлы XNU — это **спецификация** того, что попадает в ядро;
  переписывание на CMake немедленно создаёт второй источник истины;
- нужно быстро получить diff с Apple-сборкой и найти расхождения;
- CMake-порт — отдельный проект, который имеет смысл после того, как
  symbol table совпадёт.

Когда crossxnu начнёт стабильно линковаться, появится «oracle»:
`make`-сборка Apple против CMake-сборки crossxnu, сравнение символов и
сегментов. До этого CMake только увеличит риск.

## 8. Инварианты

1. `upstream/xnu` — ровно `xnu-12377.121.6`; патчи не меняют версию.
2. Компилятор — LLVM/clang, target `x86_64-apple-macos26.5`.
3. `-mkernel`, `-fapple-kext`, `-fno-rtti`, `-fno-exceptions`,
   `-fno-threadsafe-statics` — как в Apple-сборке.
4. `KERNEL_CONFIGS=RELEASE` для первого артефакта; `DEVELOPMENT/DEBUG`
   не меняют ABI, но включают assertions.
5. Ядро — Mach-O `MH_EXECUTE`/`MH_PIE`, не ELF.
6. Никакие Apple-бинарники не коммитятся.
