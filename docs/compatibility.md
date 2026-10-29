# Бинарная совместимость с macOS

Цель crossxnu: **сборка** переносится на Linux, но **результат** остаётся
ядром Darwin для того же ABI. Этот документ фиксирует, что именно
понимается под совместимостью, какие инварианты сохраняются и какие
отличия пока остаются.

## 1. Что такое «бинарно совместимо»

Совместимость — не одно свойство, а набор поверхностей. Все они
привязаны к конкретной ветке XNU (`xnu-12377.121.6`, macOS 26.5).

| Поверхность | Что должно совпадать |
|:------------|:---------------------|
| BSD syscalls | номера и типы аргументов из `bsd/kern/syscalls.master` |
| Mach traps | `mach_trap_table`, номера и семантика port rights |
| Commpage | адрес, версия/feature word, layout полей |
| Mach-O | формат ядра, сегменты, load commands, chained fixups |
| KPI/kext ABI | имена и типы символов, layout `OSObject`/`OSMetaClass`, vtable order |
| Struct layouts | публичные и приватные структуры, которых касаются kext'ы |
| Compiler flags | `-fno-rtti`, `-fno-exceptions`, `-fno-threadsafe-statics`, visibility/inlining |
| arm64e | PAC-конвенции (пока не цель) |

Компилятор не обязан быть побайтово тем же; важно, чтобы **ABI** и
**поведение** совпадали. Бит-в-бит совпадение ядра не требуется и
недостижимо из-за версий LLVM, LTO и layout.

## 2. Инварианты crossxnu

1. **Тот же исходник.** `upstream/xnu` = `xnu-12377.121.6`.
2. **Тот же target.** `x86_64-apple-macos26.5`.
3. **Те же определяющие флаги.** `APPLE`, `KERNEL`, `KERNEL_PRIVATE`,
   `XNU_KERNEL_PRIVATE`, `MACH_KERNEL_PRIVATE`, платформенные `CONFIG_*`
   берутся из `config/MASTER.x86_64`; мы их не редактируем.
4. **Те же ABI-флаги C++.** `-fapple-kext`, `-fno-rtti`,
   `-fno-exceptions`, `-fno-threadsafe-statics`, `-fno-c++-static-destructors`.
5. **Тот же формат.** Ядро — Mach-O, не ELF. `ld64.lld`, не GNU ld.
6. **Те же таблицы.** `syscalls.master`, `mach_trap_table`, commpage —
   генерируются из исходников ветки.
7. **Никаких вырезанных подсистем ядра.** DriverKit/Exclaves исключены
   из **сборки** как не-ядерные компоненты; их исходники на месте.

## 3. Что заменено и почему это не ломает ABI

| Замена | Влияние |
|:-------|:--------|
| Apple clang → LLVM clang 23 | разные предупреждения и codegen-детали; ABI-флаги те же. Требуется проверка symbol table |
| cctools `ld` → `ld64.lld` | Mach-O loader/linker; поддерживает большинство нужных флагов, но не все |
| `libtool` → `llvm-ar --format=darwin` | формат BSD-архива; статические библиотеки совместимы |
| `mig` Apple → MIG из `bootstrap_cmds` | тот же исходник Apple; версия MIG должна соответствовать ветке |
| `ctfconvert`/`ctfmerge` → отключены | CTF — отладочные метаданные; на код и ABI не влияет |
| `dsymutil` → отключён | dSYM — отладочный артефакт |
| `codesign` → no-op | ядро не подписывается; для phase 1 допустимо |
| Apple SDK → synthetic SDK | заголовки из тех же исходников; нет Apple-бинарников |
| `unifdef` → копия | заголовки содержат лишние `#if`-ветки, но `KERNEL_PRIVATE` выбирает нужные |

## 4. Известные отличия (phase 1)

### 4.1. `ld64.lld` и `-static`

`ld64.lld` (LLVM 23) предупреждает:

```
ld64.lld: warning: Option `-static' is not yet implemented.
```

Для x86_64 XNU передаёт `-pie` и `-nostdlib`; итоговый файл может иметь
`MH_DYLDLINK`/`LC_DYLD_CHAINED_FIXUPS`, которых нет у Apple-ядра.
Это **главный незакрытый риск** для загрузчика. Варианты:

1. дождаться `-static` в LLD и перейти на новую версию;
2. пост-обработка Mach-O: убрать dyld load commands и флаг `MH_DYLDLINK`;
3. собственный минимальный Mach-O линкер/упаковщик (phase 2).

Пока ядро не загружено в QEMU, считать этот пункт **открытым**.

### 4.2. `libcc_kext`

Apple-сборка линкует `-lcc_kext` — compiler-rt builtins для kext.
В crossxnu библиотека пока не собрана; линковка может дать undefined
`__divdi3`/`__udivti3` и т.п. План: собрать `compiler-rt` builtins под
`x86_64-apple-darwin` и положить как `libcc_kext.a` в synthetic SDK.

### 4.3. `libfirehose_kernel`

`libkern/os/log.c` использует firehose. Apple SDK даёт
`libfirehose_kernel.a`; crossxnu должен собрать его из
`upstream/libdispatch` (`src/firehose/firehose_buffer.c`) с MIG-заголовками.
Пока библиотека не собрана, линковка ядра не завершится.

### 4.4. Apple type builtins

XNU 26.5 использует три builtin'а Apple clang:

- `__builtin_xnu_type_summary(type)`;
- `__builtin_xnu_type_signature(type)`;
- `__builtin_xnu_types_compatible(a, b)`.

В LLVM/clang 23 их нет. Патчи 0004/0005 дают fallback:

- summary: для top-level указателя — pointer-гранула, иначе data+padding;
  `KALLOC_TYPE_IS_DATA_ONLY()` для указателей false, для остального true;
  вложенные в агрегаты указатели не распознаются;
- signature = `""` → kalloc_type не эмитит layout-сигнатуру;
- types_compatible = `1` → compile-time проверки указателей отключены.

Последствия:

- **не** меняется layout структур и vtable;
- **меняется** hardening/telemetry kalloc_type (сигнатуры, проверки);
- возможны отличия в `kalloc_type_view` metadata, которые видит
  `kalloc_type` introspection.

Это осознанный компромисс phase 1. Для полной совместимости нужен
патч LLVM/clang с реализацией этих builtin'ов (или Apple clang, что
противоречит цели).

### 4.5. DriverKit / IIG

DriverKit-заголовки генерируются Apple-инструментом **IIG**, которого
нет в open source. В crossxnu:

- `iokit/DriverKit` исключён из `exporthdrs` (патчи 0002/0003);
- `*_Methods`-макросы IIG не инжектятся (патч 0006);
- заголовки `DriverKit/*.h` — либо обычные файлы XNU, либо пустые
  заглушки.

Для **ядра macOS** это означает: классы IOKit не получают
DriverKit-dispatch методы (`SetDispatchQueue`, `CopyDispatchQueue`,
`_Dispatch`). Слот `Dispatch` в `OSMetaClassBase` сохраняется, поэтому
 layout vtable не меняется, но DriverKit-сервисы в phase 1 не работают.
Кext'ы, не использующие DriverKit, это не затрагивает; для DriverKit
нужен IIG или его реимплементация.

### 4.6. `libTightbeam`, `TrustedExecutionMonitor`, `Exclaves`

Для macOS 26 Apple линкует `libTightbeam.a` (если есть в SDK/KDK),
`libTrustedExecutionMonitor_Kernel`, `libsptm_xnu` для arm64e/SPTM.
В crossxnu x86_64 эти библиотеки не используются; для arm64 они
понадобятся. `Tightbeam`/SPTM — отдельные открытые/закрытые компоненты;
пока цель — x86_64.

### 4.7. CTF/dSYM

`DO_CTFMERGE=0`, `BUILD_DSYM=0`. Это **не** влияет на загружаемое ядро,
но лишает DTrace-метаданных и dSYM. Включать после того, как появится
`ctfconvert`/`ctfmerge` (dtrace) или их замена.

### 4.8. `AvailabilityVersions`

`availability.pl` из upstream содержит версии до macOS 14.3 (на момент
фиксации). Для `_symbol_aliasing.h` этого достаточно, но список
`__DARWIN_ALIAS_STARTING_MAC___MAC_26_*` может быть неполным. Это
влияет на **экспортируемые заголовки**, не на код ядра. Нужен
обновлённый `availability.dsl` под 26.5.

## 5. Как проверять совместимость

### 5.1. Symbol table

Главный тест phase 1:

```bash
# Apple-сборка (эталон) и crossxnu
llvm-nm -g --defined-only Apple/kernel   | sort > apple.syms
llvm-nm -g --defined-only crossxnu/kernel | sort > cross.syms
diff -u apple.syms cross.syms
```

Расхождения делятся на:

- **лишние** символы — обычно артефакты LTO/LLVM;
- **пропавшие** — реальная проблема (KPI/kext ABI);
- **изменившиеся типы** — проверить `nm` type-код и demangle.

### 5.2. Mach-O

```bash
llvm-otool -hv kernel          # magic, cputype, filetype, flags
llvm-otool -l kernel           # сегменты и load commands
llvm-otool -L kernel           # dylibs (должно быть пусто)
```

Ожидается: `MH_EXECUTE`, `MH_PIE`, `__TEXT/__DATA/__LINKEDIT`,
`__HIB` (x86_64), без `LC_LOAD_DYLINKER`.

### 5.3. ABI-таблицы

- `bsd/kern/syscalls.master` — номер/арность/типы;
- `osfmk/kern/syscall_sw.c` — `mach_trap_table`;
- `osfmk/mach/commpage.h` + `osfmk/i386/commpage/commpage.c` — layout;
- `config/*.exports` — KPI symbol sets;
- `SETUP/kextsymboltool` + `System.kext` — symbol sets.

### 5.4. Kext smoke test (phase 5)

- собрать простой kext против synthetic SDK;
- загрузить в QEMU;
- проверить `OSObject`/`OSMetaClass` layout, `OSKext` loading,
  KPI symbol resolution.

## 6. Политика изменений

- Любой патч, меняющий **код** ядра (не только сборку), требует
  отдельного обоснования и записи в этом файле.
- Патчи, меняющие ABI, запрещены до phase 5; если без них нельзя
  собрать — они помечаются `ABI-RISK` и блокируют релиз.
- Сравнение symbol table с Apple-сборкой — обязательный шаг перед
  объявлением phase 1 завершённой.
