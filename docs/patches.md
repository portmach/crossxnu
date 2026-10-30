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

`patches/kc-tools/*.patch` применяются `scripts/build-kc-tools.sh` к копии submodule в `build/kc-tools-src`, поэтому закреплённый коммит PureDarwin остаётся чистым. Сейчас там один патч: всегда собирать prelink-слой, чтобы `__PRELINK_INFO` существовал даже для KC без kext'ов — иначе XNU уходит в `readBooterExtensions()` и остаётся без kext summary.

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
| `0028-bringup-tracing.patch` | временная bring-up диагностика: трассировка syscall/mach-trap/path для pid 1, дамп планировщика и workqueue по сторожевому таймеру |

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
