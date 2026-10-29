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
