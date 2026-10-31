# Серия патчей

Патчи — единственный способ, которым crossxnu меняет XNU. Они лежат в
`patches/`, применяются по порядку из `patches/series` к чистому
`upstream/xnu` (тег `xnu-12377.121.6`).

## 1. Правила

1. **Один патч — одна причина.** Не смешивайте host-tools и ABI-fallback.
2. **Номер = порядок.** `0001`, `0002`, …; `series` — единственный
   источник порядка.
3. **Заголовок с rationale.** В начале патча — `Subject`, затем 1–3
   абзаца: что сломано, почему нельзя иначе, как проверить.
4. **Не менять версию XNU.** Патч не трогает `config/version.c.template`
   и тег.
5. **ABI-риск маркируется.** Если патч меняет layout/vtable/поведение
   ядра — в заголовке `ABI-RISK:` и запись в
   [`compatibility.md`](compatibility.md).
6. **Патч должен применяться к чистому дереву.** `apply-patches.sh`
   делает `git checkout -- .`; локальные правки не сохраняются.

## 2. Формат

Патчи — `git diff`/`git format-patch`, применяются `git apply`.
Заголовок:

```
Subject: [PATCH 000N/9999] <area>: <short description>

<why>
<what changes>
<effect on kernel ABI; "none" if none>
```

> После `bootstrap.sh` submodule `upstream/xnu` выглядит «грязным»:
> это применённые патчи в рабочем дереве. В индекс суперпроекта
> попадает только зафиксированный коммит XNU; не коммитьте содержимое
> submodule как изменения родительского репозитория.

## 3. Текущая серия

| # | Файл | Назначение | ABI |
|:--|:-----|:-----------|:----|
| 0001 | `0001-build-remove-darwin-host-probes.patch` | убрать `sysctl`/`sw_vers` из top-level make; фиксированные значения throttle | нет |
| 0002 | `0002-exclude-driverkit-from-headers.patch` | не экспортировать DriverKit/Exclaves заголовки | нет (не ядро) |
| 0003 | `0003-exclude-driverkit-from-kernel-build.patch` | не собирать DriverKit/IIG в `iokit/conf` | нет (DriverKit не входит в ядро) |
| 0004 | `0004-kalloc-type-builtins-fallback.patch` | fallback для `__builtin_xnu_type_summary/signature/types_compatible` | **да, hardening**: сигнатуры kalloc и compile-time проверки |
| 0005 | `0005-iokit-and-trap-portability.patch` | fallback в `IOLib.h`; UD1-asm в `trap.h` | **минимальный**: trap-инструкция та же (#UD), проверки типов ослаблены |
| 0007 | `0007-security-permissive-profile.patch` | permissive TrustCache/CodeSignature под `CROSSXNU_SECURITY_PERMISSIVE` | **security**: проверки отключены, ABI сохранён |
| 0009 | `0009-iokit-internal-ioservice-include.patch` | полный `IOService` для `IOKitKernelInternal.h` | нет |
| 0010 | `0010-kextsymboltool-output-file.patch` | `kextsymboltool` пишет во временный файл вместо `/dev/null` | нет |
| 0011 | `0011-tsc-zero-granularity.patch` | QEMU CPUID.0x15 denominator=0 / flex ratio=0; плюс приоритет `TSCFrequency` из device tree (loader измеряет TSC по firmware-таймеру) — без него гостевые часы шли в ~35 раз быстрее реального времени | **да, timing**: все таймауты и «idle»-эвристики workqueue |
| 0012 | `0012-early-sse-enable.patch` | включить CR4.OSFXSR до C-кода | нет |
| 0013 | `0013-x86-bare-kc-static.patch` | bare `MH_EXECUTE` считать `KCFormatStatic` | средний: KC |
| 0014 | `0014-kalloc-static-section-bounds.patch` | границы `__kalloc_type`-секций через Mach-O headers; fileset top-level; zero-zone guards | **да, kalloc**: без type-зон бюджет не распределяется |
| 0015 | `0015-read-random-early-fallback.patch` | `read_random` использует early DRBG, пока corecrypto KEC не загружен | нет (только путь без KEC) |
| 0016 | `0016-vm-map-store-no-corecrypto.patch` | не инициализировать per-CPU kmem RNG без `g_crypto_funcs`; fallback на `kmem_get_random16` | нет (только путь без corecrypto KEC) |
| 0017 | `0017-platform-expert-stub.patch` | под `CROSSXNU_SECURITY_PERMISSIVE` `IOPanicPlatform` работает как встроенный platform expert (без ACPI) | **security/boot**: заглушка платформы, не macOS-совместимая |
| 0018 | `0018-pthread-kec-optional.patch` | `pthread_init` не паникует без `com.apple.kec.pthread` | нет (только путь без KEC) |
| 0019 | `0019-wait-max-cpus-stub.patch` | `ml_wait_max_cpus` не ждёт ACPI-перечисления CPU под permissive stub | нет (только путь без ACPI) |
| 0020 | `0020-commpage-updates-before-init.patch` | time-update commpage не трогают страницы до `commpage_populate()` | нет (только ранний boot) |
| 0021 | `0021-aes-without-corecrypto.patch` | AES key wrappers возвращают ошибку без `g_crypto_funcs` (TFO при `dlil_init`) | нет (только путь без KEC) |

### Что не покрыто серией: vendored-деревья

`upstream/xnu/bsd/hfs/` — копия `upstream/hfs/core` (HFS+ не входит в состав
XNU), поэтому её правки не видны в `git -C upstream/xnu diff` и не попадают в
`patches/`. Всё, что там меняется, перечисляется здесь:

- `hfs_catalog.c`: четыре копии Finder Info (по 32 байта) переведены с
  `bcopy()` на `__nochk_bcopy()` — иначе `_FORTIFY_SOURCE_STRICT` сворачивает
  проверку «32 > 16» в безусловный `ud2` и создание каталога паникует; разбор —
  в [`hfs.md`](hfs.md#запись-на-свежий-том-fortify_source_strict-и-cat_create).

Скрипт, который воспроизводимо раскладывает `upstream/hfs/core` в
`upstream/xnu/bsd/hfs` (вместе с ручными шимами), пока не написан — это в
списке ближайших шагов в [`status.md`](status.md).

### Патчи kc-tools

`patches/kc-tools/*.patch` применяются `scripts/build-kc-tools.sh` к копии submodule в `build/kc-tools-src`, поэтому закреплённый коммит PureDarwin остаётся чистым.

Важно: это **цепочка инкрементов**, а не набор снимков. Каждый патч собран
как diff от состояния после предыдущего, поэтому `patch` применяет их строго
по порядку имён. Долгое время они были снимками от закреплённого коммита
(каждый содержал всё предыдущее), и последовательное применение падало на
`0003` с `Hunk #2 FAILED` — то есть `build-kc-tools.sh` не мог собрать
инструменты вообще. Пересобрать серию из рабочего дерева можно скриптом
`tools/bringup/regen-kc-tools-patches.sh`: он восстанавливает деревья стадий,
пересобирает диффы и требует, чтобы в `patches/kc-tools/` лежали именно
снимки (иначе просит `git checkout -- patches/kc-tools/`).

| Патч | Что делает |
|:--|:--|
| `0001` | всегда собирать prelink-слой, чтобы `__PRELINK_INFO` существовал даже для KC без kext'ов — иначе XNU уходит в `readBooterExtensions()` и остаётся без kext summary |
| `0002` | применять релокации из `LC_DYSYMTAB` (`extreloff`/`locreloff`) — у слинкованных ld64 kext'ов `nreloc` в секциях обнулён |
| `0003` | пересчитывать адрес через карту сегментов (`orig_va_to_foff`), а не как `va` — иначе `__kalloc_type` и строки классов читаются из мусора |
| `0004` | вырезать `CFBundleExecutable` у codeless-kext'ов: с ним `OSKext` ищет исполняемый файл, получает NULL `kmod_info` и падает в `kext_get_vm_map` |
| `0005` | вырезать ключ только когда значение рядом (иначе в plist остаётся висячий `<key>` и парсер обрывается) |
| `0006` | локальные секционные релокации: `addend + load_vmaddr` вместо `target + addend`; плюс фикс вырезания из `0005` |
| `0007` | связывать только срез целевой архитектуры и отказываться от `LC_DYLD_CHAINED_FIXUPS` (см. ниже) |

`0007` появился после разбора паники `_strcmp +0x10` на virtio-наборе:
`macho_view()` брал **первый 64-битный срез** fat-файла, а сиблинг
`AppleVirtIOStorage` в KDK существует **только для arm64**. Ядро получало
arm64-код и падало на первом вызове в kext'е, далеко от места ошибки. Теперь
`link_kext()` берёт cputype ядра, выбирает соответствующий срез, а
отсутствие такого среза (или `LC_DYLD_CHAINED_FIXUPS`, который линковщик не
применяет) — это ошибка сборки, а не молча пропущенный kext:
`kc-builder` печатает причину и завершает работу.

Проверка обеих веток (arm64-only и chained fixups) без реального kext'а:

```bash
# arm64-only: AppleVirtIOStorage из KDK
build/kc-tools/bin/kc-builder -kernel upstream/xnu/BUILD/obj/RELEASE_X86_64/kernel \
    -kext /tmp/kdkroot/System/Library/Extensions/AppleVirtIOStorage.kext -o /tmp/x.kc
# chained fixups: синтетический образ из любого kext'а
python3 tools/kext-loader/make-chainfix-sample.py \
    build/hello-kext/com.crossxnu.hello.kext build/cf.kext
build/kc-tools/bin/kc-builder -kernel upstream/xnu/BUILD/obj/RELEASE_X86_64/kernel \
    -kext build/cf.kext -o /tmp/y.kc
```

Обе команды должны завершиться ошибкой `cannot be linked ... aborting`.

## 4. Как добавить патч

```bash
# 1. Правьте upstream/xnu (после bootstrap патчи уже применены)
$EDITOR upstream/xnu/osfmk/...

# 2. Сгенерируйте diff только по нужным файлам
git -C upstream/xnu diff -- path/to/file > patches/0007-my-change.patch

# 3. Добавьте имя в patches/series (в конец)
echo 0007-my-change.patch >> patches/series

# 4. Проверьте применение с нуля
./scripts/apply-patches.sh
```

Если патч меняет **код ядра**, обновите:
- `docs/compatibility.md` (раздел «Известные отличия»);
- `docs/status.md` (влияние на сборку);
- при необходимости — тест в `tests/`.

## 5. Обновление XNU

1. Поднимите `upstream/xnu` на новый тег.
2. `patches/` перебазируйте по одному; каждый патч должен либо
   примениться, либо быть объявленным устаревшим с объяснением.
3. Обновите `scripts/versions.sh`, `docs/versions.md`.
4. Прогоните `bootstrap.sh` и `build.sh`; сравните symbol table.

Не обновляйте тег «заодно» с другими изменениями: смешение версии и
патчей делает diff с Apple-сборкой бессмысленным.

### Bring-up серия 0022–0028

Появилась после первых успешных загрузок: это то, что делает ядро пригодным
для запуска настоящего userland на не-macOS железе. Проверено: `git checkout -- .`
в сабмодуле `upstream/xnu` + `scripts/apply-patches.sh` (26 патчей) +
`scripts/sync-hfs.sh` восстанавливают рабочее дерево **байт в байт**, и ядро
собирается (размер совпадает; SHA-256 отличается только вшитой датой сборки).

| Патч | Что делает |
|:-----|:-----------|
| `0022-hfs-filesystem-in-kernel.patch` | регистрирует HFS+ из `bsd/hfs` в `bsd/conf/files`, правки `vfs_subr.c` для root-mount |
| `0023-serial-console-and-md-devices.patch` | serial-шим консоли, `md1` и дисковые ioctl в `memdev`, glue в `bsd_init.c` |
| `0024-pthread-kext-replacement.patch` | встроенная таблица `pthread_functions` вместо `com.apple.kec.pthread`: `bsdthread_create/register/terminate`, workqueue-потоки с kevent-протоколом |
| `0025-security-permissive-runtime.patch` | permissive-режим: пропуск signed blobs, отключение taint-проверки текстовых страниц, отчёт о user `#UD` |
| `0026-crypto-without-corecrypto.patch` | md5/sha2 без corecrypto KEC (ранние вызовы до загрузки kext) |
| `0027-iokit-platform-glue.patch` | glue `IOKitBSDInit` и `iokit/conf/files` для сборки без Xcode |
| `0028-bringup-tracing.patch` | временная bring-up диагностика: трассировка syscall/mach-trap/path для pid 1, дамп планировщика (кольцевой буфер решений `thread_setrun`/`processor_setrun`/`thread_select`/`thread_invoke`/`processor_idle`/`thread_dispatch` + `crossxnu_sched_dump`) и workqueue по сторожевому таймеру. Здесь же — хук в `bsd_init.c`, который просит OSKext загрузить `com.crossxnu.driver.CrossXnuBlockStorage` перед `com.apple.filesystems.apfs`, а также монтирует том APFS через `kernel_mount()` с флагом `KERNEL_MOUNT_BASESYSTEMROOT` (см. `docs/status.md` §11) |

Существенные детали `0024` (проверены на живой загрузке, см. `docs/status.md`):

* `bsdthread_terminate()` из `pthread_shims.c` **сам** вызывает
  `workq_thread_terminate()` для `THREAD_TAG_WORKQUEUE` — шиму kext-таблицы
  этого делать нельзя, повторный вызов ловит `ud1` в `TAILQ_REMOVE()` по уже
  отвязанному uthread.
* `bsdthread_create()` создаёт поток и **сам** его возобновляет, предварительно
  записав `copyout` имя thread-порта в `struct pthread_s` по смещению `0xf8`:
  иначе `__pthread_start()` падает с «Unable to allocate thread port», а если
  оставить поток suspended — он не запустится никогда (libpthread не вызывает
  `thread_resume()`).

`0028` — диагностика, а не функциональность: её можно и нужно выкинуть, когда
ранний userland станет стабильным.
