# crossxnu

Кроссплатформенная сборка ядра **XNU** (Darwin/macOS) вне macOS: без Xcode,
без Apple SDK и без Apple-утилит. Ядро на выходе остаётся **Mach-O** и
бинарно совместимым с macOS; меняется только сборочное окружение.

Это часть проекта [PortMach](https://github.com/portmach): «собирается где
угодно, загружается где угодно, остаётся совместимым с macOS».

## Базовая версия

| Параметр | Значение |
|:---------|:---------|
| Исходники | [`apple-oss-distributions/xnu`](https://github.com/apple-oss-distributions/xnu) |
| Тег | `xnu-12377.121.6` (macOS 26.5) |
| Коммит | `ac9718fb1af618d5ce8678d0dc6e8a58f252216f` |
| Лицензия XNU | APSL-2.0 |

Версия зафиксирована в [`upstream/xnu`](upstream/xnu) (git submodule) и в
[`docs/versions.md`](docs/versions.md). Патчи серии применяются только к
этому тегу; другая версия XNU — это другая ветка совместимости.

## Что уже работает (phase 1)

- [x] Сборка host-инструментов XNU (`SETUP/*`) на Linux.
- [x] Сборка Apple **MIG** (`mig`, `migcom`) из `bootstrap_cmds` на Linux.
- [x] Генерация MIG-заголовков и `.c` для XNU.
- [x] `make exporthdrs` — экспорт заголовков XNU без macOS.
- [x] Компиляция объектных файлов ядра `RELEASE`/`x86_64` LLVM/clang.
- [ ] Компоновка ядра в Mach-O (`ld64.lld`) — в работе, см.
      [`docs/status.md`](docs/status.md).
- [ ] `libfirehose_kernel` и `libcc_kext` — в работе.
- [ ] `arm64` — после стабилизации `x86_64`.

Статус с логами и известными блокерами: [`docs/status.md`](docs/status.md).

## Быстрый старт (Arch Linux / WSL2)

```bash
# 1. Зависимости (Arch)
sudo pacman -S --needed base-devel clang lld llvm git python \
    bison flex m4 bc rsync cpio xz zstd perl

# 2. Репозиторий и зафиксированные исходники
git clone --recurse-submodules https://github.com/portmach/crossxnu.git
cd crossxnu

# 3. Подготовка: MIG, host-compat, synthetic SDK, патчи
./scripts/bootstrap.sh

# 4. Сборка ядра
./scripts/build.sh --arch x86_64 --config RELEASE --jobs "$(nproc)"
```

Результат:

```
upstream/xnu/BUILD/obj/RELEASE_X86_64/kernel
```

Подробные требования, объяснение каждого шага и ручные команды:
[`docs/build-arch.md`](docs/build-arch.md).

> **Важно:** собирайте в файловой системе Linux (`~/src/...`), а не в
> `/mnt/c/...`. Сборка XNU — это десятки тысяч файлов; 9p-монтирование
> Windows-диска замедляет её в разы.

## Что внутри

| Путь | Назначение |
|:-----|:-----------|
| [`upstream/xnu`](upstream/xnu) | XNU `xnu-12377.121.6`, git submodule |
| [`upstream/bootstrap_cmds`](upstream/bootstrap_cmds) | Apple MIG (`mig`, `migcom`) |
| [`upstream/AvailabilityVersions`](upstream/AvailabilityVersions) | `availability.pl` для `sys/_symbol_aliasing.h` |
| [`patches/`](patches/) | серия патчей к XNU, `series` — порядок применения |
| [`toolchain/bin`](toolchain/bin) | `xcrun`, `clang`, `clang++`, `libtool`, `strip`, `nm`, `otool`, `unifdef`, `install` и др. |
| [`toolchain/include`](toolchain/include) | минимальные host-заголовки Darwin/Mach-O для сборки утилит |
| [`scripts/`](scripts/) | bootstrap, MIG, SDK, патчи, сборка |
| [`docs/`](docs/) | архитектура, совместимость, статус, патчи |

## Контракт совместимости

1. **Исходники ядра не вырезаются.** Патчи касаются сборочной системы,
   host-инструментов и нескольких мест, где Apple-компилятор предоставляет
   нестандартные builtin'ы. Компоненты, не входящие в ядро macOS
   (DriverKit, Exclaves), исключены из первой сборки, но их исходники
   остаются в дереве.
2. **Целевой ABI не меняется.** Используются те же `-D`-определения,
   `-O2`, `-mkernel`, `-fapple-kext`, `-fno-rtti`, `-fno-exceptions`,
   тот же `xnu-12377.121.6`, те же таблицы syscall/Mach trap.
3. **Ядро остаётся Mach-O**, а не ELF: иначе kext'ы и IOKit C++ ABI
   теряются сразу.
4. **Никаких Apple-бинарников в репозитории.** SDK не поставляется;
   synthetic SDK генерируется из открытых исходников XNU и
   `AvailabilityVersions`.

Текущие отличия от сборки Apple и их влияние на ABI перечислены в
[`docs/compatibility.md`](docs/compatibility.md). Их нельзя замалчивать:
пока они есть, сборка считается **phase 1**, а не релизом.

## Документация

- [Сборка на Arch Linux / WSL2](docs/build-arch.md)
- [Архитектура сборки и замены инструментов](docs/architecture.md)
- [Бинарная совместимость: что сохраняем и что пока нет](docs/compatibility.md)
- [Статус, логи, блокеры](docs/status.md)
- [Правила серии патчей](docs/patches.md)
- [Версии upstream и обновление](docs/versions.md)

## Лицензии

Оригинальные скрипты и документация этого репозитория — MIT.
Патчи и код, производные от XNU, — APSL-2.0. MIG — APSL-2.0,
`AvailabilityVersions` — APSL-2.0. См. [`docs/legal.md`](docs/legal.md).

---

## English summary

`crossxnu` is a patch series plus a portable toolchain that builds the
Darwin XNU kernel on Linux without Xcode, the Apple SDK, or Apple's cctools.
The output is still a Mach-O kernel for the pinned `xnu-12377.121.6`
(macOS 26.5) branch; the build host changes, the target ABI does not.
Phase 1 currently covers host tools, MIG, header export and kernel object
compilation; linking and the two Apple static libraries are still in
progress. See [`docs/status.md`](docs/status.md).
