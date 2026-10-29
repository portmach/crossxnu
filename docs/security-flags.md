# Security flags reference

Справочник по флагам, которые влияют на TrustCache/CodeSignature в
crossxnu. **Все они относятся к security-политике, а не к ABI.**

## 1. Build-time

| Флаг / переменная | Где | Значение | Что делает |
|:------------------|:----|:---------|:-----------|
| `--security permissive` | `scripts/build.sh` | по умолчанию | добавляет `-DCROSSXNU_SECURITY_PERMISSIVE=1` |
| `--security strict` | `scripts/build.sh` | future | `-DCROSSXNU_SECURITY_PERMISSIVE=0`, Apple-поведение |
| `CROSSXNU_SECURITY_PERMISSIVE` | C-препроцессор | `0`/`1` | включает permissive-ветки в `kern_codesigning.c`, `kern_trustcache.c`, `ubc_subr.c` |
| `CFLAGS_EXTRA` | XNU make | строка | сюда build.sh добавляет `-DCROSSXNU_SECURITY_PERMISSIVE=...`; вручную не задавайте, используйте `--security` |
| `CROSSXNU_SDK` | окружение | путь | synthetic SDK; не security-флаг, но от него зависит сборка `TrustCache`/`CodeSignature` |
| `-I toolchain/shims/permissive` | `CFLAGS_EXTRA` (permissive) | путь | SDK-free заглушки `TrustCache/API.h`, `CodeSignature/Entitlements.h`, `CoreEntitlements/V2/*` |

`CROSSXNU_SECURITY_PERMISSIVE=1` **не** вырезает код: `cs_*` syscalls,
`cs_blob`, entitlements parser и AMFI-интерфейс остаются. Меняются только
решения «доверять/не доверять».

## 2. SDK-free permissive shims

`toolchain/shims/permissive/` содержит **не-Abi** заглушки, которые
подключаются только при `--security permissive`:

| Файл | Что даёт | Опасность |
|:-----|:---------|:----------|
| `TrustCache/API.h` | opaque-типы и константы, достаточные для компиляции `kern_trustcache.c` | нельзя передавать в настоящий AMFI; в permissive код до AMFI не доходит |
| `CodeSignature/Entitlements.h` | четыре browser-entitlement строки | строки нужно сверить с 26.5; при permissive enforcement всё равно выключен |
| `CoreEntitlements/V2/API.h` | использует V1-типы XNU + opaque `CEKernelAPI_t` | AMFI с V2-интерфейсом не должен вызываться |

Это не замена SDK для strict-режима. Для strict нужны настоящие
заголовки 26.5; иначе layout/строки могут разойтись.

## 3. XNU `CS_CONFIG_*` (биты `cs_config`)

Определены в `bsd/sys/code_signing.h`. В permissive-сборке патч 0007
выставляет их в `code_signing_configuration()`.

| Бит | Имя | Что означает | В permissive |
|:----|:----|:-------------|:-------------|
| `1 << 0` | `CS_CONFIG_UNRESTRICTED_DEBUGGING` | разрешает debugger/`task_for_pid`-подобные сценарии | **включён** |
| `1 << 1` | `CS_CONFIG_ALLOW_ANY_SIGNATURE` | не требовать валидную подпись | **включён** |
| `1 << 2` | `CS_CONFIG_ENFORCEMENT_DISABLED` | отключает enforcement модифицированного кода | **включён** |
| `1 << 3` | `CS_CONFIG_GET_OUT_OF_MY_WAY` | «не мешать»: пропускать trust evaluation | **включён** |
| `1 << 4` | `CS_CONFIG_INTEGRITY_SKIP` | не проверять integrity | **включён** |
| `1 << 5` | `CS_CONFIG_RELAX_PROFILE_TRUST` | ослабить доверие к profile | не меняется |
| `1 << 6` | `CS_CONFIG_DEV_MODE_POLICY` | политика developer mode | не меняется |
| `1 << 25` | `CS_CONFIG_REM_SUPPORTED` | Restricted Execution Mode | не включается (x86_64) |
| `1 << 26` | `CS_CONFIG_MAP_JIT` | MAP_JIT | остаётся |
| `1 << 27` | `CS_CONFIG_DEVELOPER_MODE_SUPPORTED` | developer mode | остаётся |
| `1 << 28` | `CS_CONFIG_COMPILATION_SERVICE` | compilation service | остаётся |
| `1 << 29` | `CS_CONFIG_LOCAL_SIGNING` | local signing | остаётся |
| `1 << 30` | `CS_CONFIG_OOP_JIT` | out-of-process JIT | остаётся |
| `1 << 31` | `CS_CONFIG_CSM_ENABLED` | code signing monitor | остаётся |

Важно: `CS_CONFIG_ALLOW_ANY_SIGNATURE`/`GET_OUT_OF_MY_WAY` — это **не**
«подпись валидна», а «проверку можно не делать». `csops` и другие
потребители всё равно получают согласованные флаги/структуры.

## 4. Boot-args XNU (только DEVELOPMENT/DEBUG)

Эти аргументы парсятся в `kern_codesigning.c` под `#if DEVELOPMENT || DEBUG`.
В **RELEASE** они не действуют; для RELEASE permissive используется
`CROSSXNU_SECURITY_PERMISSIVE` (патч 0007).

| Boot-arg | Тип | Действие |
|:---------|:----|:---------|
| `amfi=0x01` | mask | `CS_CONFIG_UNRESTRICTED_DEBUGGING` |
| `amfi=0x02` | mask | `CS_CONFIG_ALLOW_ANY_SIGNATURE` |
| `amfi=0x80` | mask | `ALLOW_ANY_SIGNATURE` + `GET_OUT_OF_MY_WAY` |
| `amfi_allow_any_signature=1` | int | `ALLOW_ANY_SIGNATURE` |
| `amfi_unrestrict_task_for_pid=1` | int | `UNRESTRICTED_DEBUGGING` |
| `amfi_get_out_of_my_way=1` | int | `ALLOW_ANY_SIGNATURE` + `GET_OUT_OF_MY_WAY` |
| `cs_enforcement_disable=1` | int | `ALLOW_ANY_SIGNATURE` + `ENFORCEMENT_DISABLED` + `GET_OUT_OF_MY_WAY` |
| `cs_integrity_skip=1` | int | `INTEGRITY_SKIP` |
| `amfi_relax_profile_trust=1` | int | `RELAX_PROFILE_TRUST` |
| `amfi_dev_mode_policy=1` | int | `DEV_MODE_POLICY` |
| `pmap_cs_allow_any_signature=1` | int | arm64/PPL: разрешает `ALLOW_ANY_SIGNATURE` |

Это **Apple-флаги**, а не интерфейс crossxnu. AMFI kext может иметь свои
собственные boot-args; они могут применяться независимо.

## 5. TrustCache (permissive)

Патч 0007 в permissive-режиме:

- `trust_cache_runtime_init()` — не инициализирует runtime и не паникует
  при отсутствии AMFI;
- `load_static_trust_cache()` — no-op;
- `load_trust_cache()` / `load_trust_cache_with_type()` /
  `load_legacy_trust_cache()` — возвращают `KERN_SUCCESS` без загрузки;
- `query_trust_cache()` — возвращает `KERN_SUCCESS` (токен обнулён);
- `check_trust_cache_runtime_for_uuid()` — `KERN_SUCCESS`;
- `static_trust_cache_capabilities()` — нулевые capabilities;
- `unload_trust_cache()` — `KERN_SUCCESS`.

Это значит: **любой CDHash считается доверенным**. TrustCache больше не
является ограничением. AMFI, если загружен, может всё равно применять
свою политику; permissive-ядро её не отменяет.

## 6. CodeSignature (permissive)

Патч 0007:

- `code_signing_configuration()` выставляет биты из §3;
- `startup.c` отключает `AMFI_bootarg_disable_mach_hardening`;
- `kern_cs.c`/`ubc_subr.c` не паникуют, если AMFI отсутствует;
- entitlements parser остаётся; `cs_*` и `cs_blob` не меняются.

Что это **не** делает:

- не подделывает подпись;
- не отключает AMFI kext (если он загружен);
- не гарантирует запуск Apple-приложений без trust caches;
- не делает систему безопасной.

## 7. Планируемый runtime-флаг

В phase 2 появится единый boot-arg:

```
crossxnu.security=permissive
```

и sysctl:

```
kern.crossxnu.security: permissive
```

Он должен:
- быть явным (не «тихий» дефолт в strict-сборке);
- печататься в boot log;
- не конфликтовать с `CROSSXNU_SECURITY_PERMISSIVE` (build-time
  permissive — обязательное условие; boot-arg может только ужесточать
  или подтверждать).

## 8. Что выбрать

| Задача | Флаги |
|:-------|:------|
| Собрать/загрузить на произвольном железе | `--security permissive` (по умолчанию) |
| Отладка userland/kext | permissive + `cs_debug=1` (DEVELOPMENT/DEBUG) |
| Приближение к macOS | `--security strict` + Apple AMFI/trust caches (future) |
| Проверить, что ABI не сломан | strict-сборка и сравнение symbol table |

**Не** используйте permissive-режим как security boundary. Подробности —
[`../SECURITY.md`](../SECURITY.md) и [`security-policy.md`](security-policy.md).
