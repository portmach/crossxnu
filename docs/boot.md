# Boot в QEMU (phase 1)

**Статус:** ядро доходит до ранней инициализации, но пока падает в
`kalloc_type_distribute_budget()` (divide error). Полной загрузки нет.

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
- После этого ядро доходит до `kalloc_type_distribute_budget()` и делит
  на ноль: статический разбор `__kalloc_type` не даёт ни одного view
  (`total_sig == 0`). Патч 0014 берёт границы секции из Mach-O header
  (`_mh_execute_header` для bare kernel), но деление всё ещё
  воспроизводится — значит, проблема не только в boundary symbols.

## Fileset-путь

Собран `kc-tools` (PureDarwin, BSD-3-Clause) и `build/kernel.kc`:

```bash
./scripts/build-kc-tools.sh
./scripts/build-fileset.sh
```

`kc-builder` делает `MH_FILESET` с флагом `MH_DYLIB_IN_CACHE`;
загрузчик это уже понимает (`KC_hdrs_vaddr`). Проверка fileset в QEMU
дала **ту же** панику `kalloc_type_distribute_budget()`.

Диагностика через QEMU monitor: `kt_count = 8` (var views),
`kt_freq_list[0] = 1`, `kt_freq_list_total` полностью нулевой. Секция
`__kalloc_type` непустая, первые записи выглядят валидно
(`kt_flags=0x806c`, `kt_size=0x30`). То есть проблема уже в
`kalloc_type_view_copy()`/`kt_buffer`, а не в отсутствии секции.

Следующий шаг — инструментировать `kalloc_type_view_copy()` и
`kalloc_type_handle_parray_var()`, а не добавлять новые section-патчи.

## Bare-путь (экспериментально)

Bare `MH_EXECUTE` доходит до того же места; патчи 0013/0014/0015 —
временные обходы, не ABI-путь. Не использовать как основу для
полного userland.
