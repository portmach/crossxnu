# crossxnu

Кроссплатформенная сборка ядра **XNU** (Darwin/macOS) вне macOS: без Xcode,
без Apple SDK и без Apple-утилит. Ядро на выходе остаётся **Mach-O** и
бинарно совместимым с macOS; меняется только сборочное окружение.

Это часть проекта [PortMach](https://github.com/portmach): «собирается где
угодно, загружается где угодно, остаётся совместимым с macOS».

> ## ⚠️ Security status: permissive
>
> **crossxnu пока не реализует security-модель macOS.**
> TrustCache и CodeSignature находятся в **permissive-режиме**: ядро не
> проверяет доверие к CDHash, не требует подписи и не обеспечивает
> enforcement entitlements. Любой код, который загрузится, считается
> доверенным; это **небезопасно** и **не предназначено для production**.
>
> Это осознанное решение phase 1, а не баг сборки. Для permissive-режима
> используются SDK-free заглушки [`toolchain/shims/permissive`](toolchain/shims/permissive);
> полный Apple SDK не требуется. Подробности, границы режима и план
> перехода к strict — в [`SECURITY.md`](SECURITY.md) и
> [`docs/security-policy.md`](docs/security-policy.md).

## Состояние на сегодня

Ядро собирается и **загружается на обычном x86_64-железе (QEMU)**, поднимает
настоящий macOS-userland и доходит до работающего `launchd` в роли pid 1.

Проверено на реальных загрузках (см. [`docs/status.md`](docs/status.md)):

- [x] Сборка host-инструментов XNU, Apple **MIG**, заголовков и `exporthdrs` на Linux.
- [x] Компиляция и **компоновка** ядра в Mach-O (`ld64.lld`), без LTO.
- [x] Загрузка через UEFI-загрузчик [`PureDarwin/xnu-loader`](https://github.com/PureDarwin/xnu-loader) в QEMU (`q35`, Skylake-Client).
- [x] `IOPlatformExpert`, kext scan, kalloc, commpage, PRNG, AES — стартуют без Apple KEC.
- [x] BSD init, сеть, монтирование HFS+ root с RAM-диска (recovery-образ пользователя).
- [x] **macOS userland выполняется**: `uname`, `sw_vers`, `ls`, `ps`, `mount`, `sysctl`, `cat`.
- [x] HFS+ **пишется**: отдельный scratch-том `md1` монтируется в `/private/var`, `newfs_hfs`, `mkdir`, запись/чтение файлов.
- [x] Замена `com.apple.kec.pthread`: встроенная таблица `pthread_functions`, `bsdthread_create/register/terminate`, workqueue-потоки с kevent-протоколом.
- [x] `launchd` работает как **pid 1**: проходит bootstrap, все boot-задачи (`mount-phase-1/2`, `dirs_cleaner`, …) и печатает `launchd logging initialized`.

Что пока не работает (честно):

- [ ] После инициализации логирования `launchd` замолкает — вероятно, блокируется на заглушках `psynch_*`, которые ещё возвращают `ENOTSUP`; задания из `/Library/LaunchDaemons` не запускаются.
- [ ] `setiopolicy_np` не реализован (нефатальный assertion в `launchd`).
- [ ] Нет `libfirehose_kernel`/`libcc_kext` в полном виде; нет `arm64`; LTO выключен.
- [ ] System cryptex (`RIDIFF10`/`BXDIFF50`) не собран, поэтому обычный system-root пока не запускается — используется recovery-userland.

## Базовая версия

| Параметр | Значение |
|:---------|:---------|
| Исходники | [`apple-oss-distributions/xnu`](https://github.com/apple-oss-distributions/xnu) |
| Тег | `xnu-12377.121.6` (macOS 26.5) |
| Коммит | `ac9718fb1af618d5ce8678d0dc6e8a58f252216f` |
| Загрузчик | `PureDarwin/xnu-loader` `8295cd8` |
| HFS+ | [`apple-oss-distributions/hfs`](https://github.com/apple-oss-distributions/hfs) (сабмодуль, дерево генерируется) |
| Лицензия XNU | APSL-2.0 |

Версия зафиксирована в [`upstream/xnu`](upstream/xnu) (git submodule) и в
[`docs/versions.md`](docs/versions.md). Патчи серии применяются только к
этому тегу; другая версия XNU — это другая ветка совместимости.

## Что нужно локально

**Для сборки** — Linux x86_64 (Arch Linux, WSL2 подходит):

```bash
sudo pacman -S --needed base-devel clang lld llvm git python \
    bison flex m4 bc rsync cpio xz zstd perl
```

Плюс ~2 ГБ на дерево сборки. Собирайте в Linux-ФС (`~/src/...`), а не в
`/mnt/c/...`: XNU — это десятки тысяч файлов, 9p-монтирование Windows-диска
замедляет сборку в разы.

**Для загрузки** (только если хотите увидеть userland) — то, чего в
репозитории принципиально нет и не будет, вы берёте из своей macOS:

- recovery-образ/root (HFS+), из которого собирается ramdisk;
- `dyld` и системные dylib'и (`libsystem_pthread`, `libdispatch`, `libsystem_c`, …);
- `launchd` и остальные бинарники recovery-userland'а;
- OVMF (`edk2-x86_64-code.fd`) и QEMU.

## Сборка

```bash
# 1. Репозиторий вместе с зафиксированными сабмодулями
git clone --recurse-submodules https://github.com/portmach/crossxnu.git
cd crossxnu

# 2. Подготовка: сабмодули, патчи XNU, дерево HFS+, MIG, host-инструменты,
#    synthetic SDK, DriverKit/IIG
./scripts/bootstrap.sh

# 3. Ядро
./scripts/build.sh --arch x86_64 --config RELEASE --security permissive \
    --jobs "$(nproc)"
```

Результат: `upstream/xnu/BUILD/obj/RELEASE_X86_64/kernel` (Mach-O, ~17 МБ),
рядом `kernel.unstripped` и `kernel.ctf`.

Что делают шаги 2 и 3 подробно:

| Скрипт | Назначение |
|:-------|:-----------|
| `scripts/fetch-deps.sh` | склонировать сабмодули, если клонировали без `--recurse-submodules` |
| `scripts/apply-patches.sh` | `git checkout -- .` в `upstream/xnu` и применить 25 патчей из `patches/series` |
| `scripts/sync-hfs.sh` | сгенерировать `upstream/xnu/bsd/hfs` и `bsd/hfs_encodings` из `upstream/hfs` + `patches/hfs` |
| `scripts/build-mig.sh` | собрать Apple MIG (`mig`, `migcom`) из `bootstrap_cmds` |
| `scripts/build-host-tools.sh` | host-инструменты XNU (`SETUP/*`) |
| `scripts/make-sdk.sh` | synthetic SDK из открытых заголовков |
| `scripts/generate-driverkit.sh` | сгенерировать `iokit/DriverKit/*.iig.cpp` (IIG-порт) |
| `scripts/build.sh` | собственно сборка ядра, `--security permissive\|strict` |

Воспроизводимость: `git checkout -- .` в сабмодуле + `apply-patches.sh` +
`sync-hfs.sh` восстанавливают рабочее дерево **байт в байт**; ядро
пересобирается в тот же размер (SHA-256 отличается только датой сборки,
которая вкомпилирована в строку версии).

## Запуск в QEMU

Ядро грузится как `EFI/BOOT/kernel` через загрузчик `BOOTX64.EFI`
(он же умеет читать `boot-args.txt`). Минимальный ESP:

```text
EFI/BOOT/BOOTX64.EFI     # upstream/xnu-loader
EFI/BOOT/kernel          # результат сборки
EFI/BOOT/boot-args.txt   # необязательно, например "-v serial=1"
ramdisk.img              # HFS+ recovery-образ с userland (свой)
```

Пример запуска:

```bash
qemu-system-x86_64 -machine q35 -cpu Skylake-Client -m 4096 -smp 1 \
    -drive if=pflash,format=raw,readonly=on,file=edk2-x86_64-code.fd \
    -drive if=pflash,format=raw,file=esp-vars.fd \
    -drive file=esp32.img,format=raw,if=ide \
    -display none -vga std -serial tcp:127.0.0.1:4444,server=on,wait=off \
    -monitor none -no-reboot
```

Скрипты для воспроизводимых прогонов (шаблон ESP и ramdisk собираются
локально, в репозиторий они не входят):

- `scripts/hfs-image.py` — собрать HFS+ ramdisk из дерева recovery-рута;
- `scripts/serial-run.ps1` — поднять QEMU, подключиться к serial по TCP и писать транскрипт (Windows/pwsh);
- `scripts/run-console.ps1` — интерактивная консоль.

Подробности: [`docs/boot.md`](docs/boot.md), запуск userland —
[`docs/userland.md`](docs/userland.md), HFS+ — [`docs/hfs.md`](docs/hfs.md).

## Что внутри

| Путь | Назначение |
|:-----|:-----------|
| [`upstream/xnu`](upstream/xnu) | XNU `xnu-12377.121.6`, git submodule (все правки — в `patches/`) |
| [`upstream/xnu-loader`](upstream/xnu-loader) | UEFI-загрузчик, git submodule + наши правки в `patches/xnu-loader/` |
| [`upstream/hfs`](upstream/hfs) | исходники HFS+; в ядро попадают через `scripts/sync-hfs.sh` |
| [`upstream/bootstrap_cmds`](upstream/bootstrap_cmds) | Apple MIG (`mig`, `migcom`) |
| [`upstream/libdispatch`](upstream/libdispatch), [`iig-port`](upstream/iig-port), [`cctools-port`](upstream/cctools-port), [`kc-tools`](upstream/kc-tools) | сборка userland/kext-инструментов |
| [`patches/`](patches/) | серия патчей к XNU (`series` — порядок), а также `patches/hfs`, `patches/xnu-loader` |
| [`toolchain/`](toolchain/) | обёртки компилятора/утилит, host-заголовки, shims (включая `permissive/`) |
| [`userland/`](userland/) | статический init (`init.c`), `rc.local`, `rc.launchd`, тестовый LaunchDaemon |
| [`scripts/`](scripts/) | bootstrap, MIG, SDK, патчи, сборка, образы, серийная консоль |
| [`docs/`](docs/) | архитектура, совместимость, статус, патчи, лицензии |

## Контракт совместимости

1. **Исходники ядра не вырезаются.** Патчи касаются сборочной системы,
   host-инструментов и нескольких мест, где Apple-компилятор предоставляет
   нестандартные builtin'ы. DriverKit генерируется portable IIG
   (`iig-port`), Exclaves пока исключены; исходники остаются в дереве.
2. **Целевой ABI не меняется.** Те же `-D`-определения, `-O2`, `-mkernel`,
   `-fapple-kext`, `-fno-rtti`, `-fno-exceptions`, тот же
   `xnu-12377.121.6`, те же таблицы syscall/Mach trap.
3. **Ядро остаётся Mach-O**, а не ELF: иначе kext'ы и IOKit C++ ABI
   теряются сразу.
4. **Никаких Apple-бинарников в репозитории.** SDK не поставляется;
   synthetic SDK генерируется из открытых исходников. Дерево `bsd/hfs`
   генерируется скриптом, а не хранится копией. Это проверяется
   [`scripts/check-publish.sh`](scripts/check-publish.sh).

Текущие отличия от сборки Apple и их влияние на ABI перечислены в
[`docs/compatibility.md`](docs/compatibility.md). Их нельзя замалчивать:
пока они есть, сборка считается **phase 1**, а не релизом.

## Документация

- [Security policy / политика безопасности](SECURITY.md)
- [Security policy: подробно](docs/security-policy.md)
- [Security flags reference](docs/security-flags.md)
- [Boot в QEMU](docs/boot.md)
- [Userland: как запускается macOS-окружение](docs/userland.md)
- [HFS+: ядро, том, запись](docs/hfs.md)
- [Сборка на Arch Linux / WSL2](docs/build-arch.md)
- [Архитектура сборки и замены инструментов](docs/architecture.md)
- [Бинарная совместимость: что сохраняем и что пока нет](docs/compatibility.md)
- [Статус, логи, блокеры](docs/status.md)
- [Правила серии патчей](docs/patches.md)
- [Версии upstream и обновление](docs/versions.md)
- [Лицензии и границы распространения](docs/legal.md)
- [DriverKit/IIG: генерация без SDK](docs/driverkit.md)

## Лицензии

Оригинальные скрипты и документация этого репозитория — MIT.
Патчи и код, производные от XNU, — APSL-2.0. MIG — APSL-2.0,
`AvailabilityVersions` — APSL-2.0. См. [`docs/legal.md`](docs/legal.md).

---

## English summary

`crossxnu` is a patch series plus a portable toolchain that builds the Darwin
XNU kernel on Linux without Xcode, the Apple SDK, or Apple's cctools. The
output is still a Mach-O kernel for the pinned `xnu-12377.121.6` (macOS 26.5)
branch; the build host changes, the target ABI does not.

Phase 1 already builds, links and boots the kernel in QEMU: it brings up
IOPlatformExpert, kexts, BSD init and a real macOS recovery userland from an
HFS+ RAM disk, and runs `launchd` as pid 1 through its bootstrap and boot
tasks. The built-in pthread table replaces `com.apple.kec.pthread`, including
workqueue threads with the kevent upcall protocol. The kernel is in
permissive security mode: no trust cache or code signature enforcement.

Not done yet: `psynch_*` are stubs (launchd stalls after logging init),
no arm64, no LTO, and the system cryptex is not assembled, so a normal
system root does not boot yet. See [`docs/status.md`](docs/status.md).
