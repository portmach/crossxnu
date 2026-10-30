# Boot в QEMU (phase 1)

**Статус:** ядро линкуется, грузится в QEMU, проходит kalloc, kext scan,
PRNG, `vm_map_store`, IOKit и доходит до BSD init со встроенным
platform-expert stub. Сейчас падает на обновлении commpage до её
инициализации. Полной загрузки нет.

## Схема

```text
OVMF (edk2-x86_64-code.fd)
  └─ BOOTX64.EFI  (PureDarwin/xnu-loader)
       ├─ читает EFI/BOOT/kernel (Mach-O)
       ├─ строит boot_args, devicetree и EFI memory map
       ├─ ExitBootServices + SetVirtualAddressMap
       └─ копирует сегменты на физические адреса
          и прыгает в XNU `_start` (32-bit compat)
```

Загрузчик: [`PureDarwin/xnu-loader`](https://github.com/PureDarwin/xnu-loader)
(BSD-3-Clause), сборка через GNU-EFI.

## Сборка загрузчика

Нужен `gnu-efi` (Arch: `gnu-efi`) и CMake.

```bash
git clone https://github.com/PureDarwin/xnu-loader.git
cmake -S xnu-loader -B xnu-loader/build \
    -DGNU_EFI_DIR=/usr -DARCH=x86_64
cmake --build xnu-loader/build -j"$(nproc)"
```

Штатное правило `objcopy --target=efi-app-x86_64` в GNU binutils без
`--enable-targets` не работает. Рабочий вариант:

```bash
objcopy -I elf64-x86-64 \
    -j .text -j .sdata -j .data -j .rodata \
    -j .dynamic -j .dynsym -j .rel -j .rela -j .reloc \
    -O pei-x86-64 --subsystem=efi-app \
    xnu-loader/build/xnu-loader.so BOOTX64.EFI
```

## ESP и QEMU

```text
build/esp/EFI/BOOT/BOOTX64.EFI
build/esp/EFI/BOOT/kernel
build/esp/EFI/BOOT/boot-args.txt   # необязательно; сейчас "-v"
```

QEMU (Windows-сборка; OVMF из `C:\Program Files\qemu\share`):

```powershell
qemu-system-x86_64.exe -machine q35 -cpu Skylake-Client -m 2048 -smp 1 `
  -drive if=pflash,format=raw,readonly=on,file=...\edk2-x86_64-code.fd `
  -drive if=pflash,format=raw,file=...\esp-vars.fd `
  -drive file=fat:rw:...\build\esp,format=raw,if=ide `
  -boot order=c -display none -vga std -serial none `
  -monitor tcp:0.0.0.0:5555,server,nowait
```

`-cpu` обязателен: на `qemu64`/`max` XNU падает
`panic("Unsupported CPU")` в `cpuid_set_info`.

## Что уже проверено

- Загрузчик читает kernel, все сегменты, devicetree и memory map.
- Переход в `_start` происходит; ядро выполняет раннюю инициализацию.
- Исправлены три portability-проблемы QEMU:
  - `CPUID.0x15` denominator = 0 → патч 0011;
  - SSE-инструкции до `fpu_init` → патч 0012 (CR4.OSFXSR в `start.s`);
  - x86 bare kernel определяется как `KCFormatDynamic` → патч 0013
    (для bare `MH_EXECUTE` считаем `KCFormatStatic`).
- Патч 0014 (границы `__kalloc_type` из Mach-O headers + zero-zone
  guards) — kalloc проходит.
- Патч 0013 (`bare MH_EXECUTE` → `KCFormatStatic`) нужен только для
  bare-пути.
- Патч 0015: `read_random()` использует early DRBG, пока corecrypto
  KEC не загружен (иначе `prng_funcs.refresh(NULL)`).
- Патч 0016: `vm_map_store_crypto_init()` не трогает
  `crypto_random_kmem_ctx_size()` без `g_crypto_funcs`, а fallback в
  `vmgo_chunk_select_random_slot()` идёт через `kmem_get_random16()`.
- Дальше ядро доходит до IOKit и падает:

```text
Unable to find driver for this platform: "ACPI". @IOPlatformExpert.cpp:2365
```

Это не «kext scan»: в логе выше видно, что startup-фаза дошла до
`IOPlatformExpert`, а драйвер платформы (`AppleACPIPlatformExpert`) —
kext, которого в KC нет.

Полезно: серийный лог снимается boot-аргументом `serial=1` и
`-serial file:build/serial.log`. Без него panic screen прокручивает
причину вверх, и видна только строка символайзера
`can't perform kext scan: no kext summary`.

## Fileset-путь

Собран `kc-tools` (PureDarwin, BSD-3-Clause) и `build/kernel.kc`:

```bash
./scripts/build-kc-tools.sh
./scripts/build-fileset.sh
```

`kc-builder` делает `MH_FILESET` с флагом `MH_DYLIB_IN_CACHE`;
загрузчик это уже понимает (`KC_hdrs_vaddr`).

`kc-builder` теперь **всегда** собирает prelink-слой: даже при нуле
kext'ов в KC есть `__PRELINK_INFO` с пустым
`_PrelinkInfoDictionary`. Это заставляет XNU идти по prelinked-пути, а
не читать mkext из `/chosen/memory-map` (которого UEFI-загрузчик не
создаёт). Патч лежит в `patches/kc-tools/` и применяется
`scripts/build-kc-tools.sh` к копии submodule.

`WARNING: did not find UUID in Primary KC!` — ожидаемо: synthetic KC
пока без `_PrelinkKernel`/KernelCache UUID.

### Встроенный platform expert stub

Патч 0017 (`CROSSXNU_SECURITY_PERMISSIVE`) заставляет встроенный
`IOPanicPlatform` работать как platform expert: он вызывает
`IOPlatformExpert::start()`, публикует сервис и не паникует. Это
заглушка для bring-up, не macOS-совместимый ACPI-драйвер.

После неё выяснилось, что без kext'ов не хватает ещё двух вещей:

- `com.apple.kec.pthread` — патч 0018 разрешает `pthread_init()` без
  таблицы функций (pthread-сисколлы при этом не работают);
- ACPI-перечисления CPU — патч 0019 заставляет `ml_wait_max_cpus()`
  объявить boot CPU вместо бесконечного ожидания.

Теперь ядро доходит до BSD init. Следующий блокер —
`commpage_update_mach_approximate_time()`: планировщик обновляет
commpage раньше, чем она инициализирована, и `commPagePtr32` указывает
в невалидную страницу.

### Kext'ы в fileset

`build-fileset.sh` умеет принимать реальные kext'ы и codeless KPI:

```bash
./scripts/build-fileset.sh --with-kpi \
    --kext /path/AppleACPIPlatformExpert.kext \
    --kext /path/IOACPIFamily.kext
```

`--with-kpi` добавляет `config/System.kext/PlugIns/*.kext` как codeless
(с `CFBundleVersion=9999.0.0`: сырую версию `12377.121.6` OSKext
отвергает). Это нужно, потому что реальные Apple-kext'ы объявляют
`OSBundleLibraries` на `com.apple.kpi.*`.

Без реального platform expert'а ядро падает на
`Unable to find driver for this platform: "ACPI"` — это текущий блокер.
Кексты Apple нужно взять из macOS-установки (BootKC/SystemKC или
`/System/Library/Extensions`); в репозитории их нет.

## Bare-путь (экспериментально)

Bare `MH_EXECUTE` доходит до того же места; патч 0013 и bare-вариант
границ секций в 0014 — временные обходы, не ABI-путь. Не использовать
как основу для полного userland.
