# Security policy: подробно

Дополняет [`../SECURITY.md`](../SECURITY.md). Здесь — техническое
обоснование permissive-режима и границы между TrustCache и
CodeSignature.

## 1. Две подсистемы, не одна

```
                    ┌─────────────────────────────┐
                    │        CodeSignature        │
                    │  cs_* syscalls, cs_blob,    │
                    │  CDHash, entitlements,       │
                    │  AMFI, amfid/taskgated       │
                    └──────────────┬──────────────┘
                                   │ использует
                    ┌──────────────▼──────────────┐
                    │         TrustCache          │
                    │  быстрый whitelist CDHash   │
                    │  (libTrustCache / AMFI)     │
                    └─────────────────────────────┘
```

- **CodeSignature** — зонтичная система. Она отвечает за то, что вообще
  означает «подписанный код», какие у него entitlements, какие
  `cs_*`-флаги, как `amfid`/`taskgated` принимают решения.
- **TrustCache** — один из входов этой системы: быстрый ответ «этот
  CDHash уже известен и доверен». Он не заменяет проверку подписи и не
  отменяет entitlements.

Поэтому permissive TrustCache **не** делает CodeSignature permissive
автоматически. Нужен отдельный профиль.

## 2. Почему нельзя просто «вырезать»

### 2.1. ABI

`TrustCache_t`, `TrustCacheRuntime_t`, `TrustCacheQueryToken_t` — это
структуры, которые пересекают границу XNU ↔ AMFI kext. Если XNU
собирается с другим layout, AMFI kext будет писать/читать не туда.
Поэтому для strict-режима нужны настоящие заголовки из SDK/точной
копии 26.5.

В permissive-режиме можно сделать так, чтобы XNU **не разыменовывал**
эти структуры: тогда допустимы opaque-типы. Но это должно быть явно
спроектировано, а не «пустой заголовок на удачу».

### 2.2. Runtime

`trust_cache_runtime_init()` проверяет `amfi != NULL` и падает в panic,
если AMFI kext нет (`bsd/kern/kern_trustcache.c`). То есть пустой
`TrustCache/API.h` не спасает: ядро упадёт на инициализации.

`cs_*` syscalls и `cs_blob` — часть пользовательского ABI. `launchd`,
`libSystem`, `amfid`, `taskgated`, TCC и сетевые extension'ы используют
их. «Вырезать» = сломать userland.

### 2.3. Полнота userland

Если сделать все CDHash доверенными, приложения запустятся, но:

- подпись/целостность не проверяются;
- entitlements перестают быть ограничением;
- часть системных сервисов может проверять `CS_VALID`/`CS_DEBUGGED` и
  вести себя иначе;
- AMFI-политика может всё равно блокировать код.

Это не «совместимость», а другой security-профиль.

## 3. Профили

| Профиль | TrustCache | CodeSignature | AMFI | Назначение |
|:--------|:-----------|:--------------|:-----|:-----------|
| `permissive` (phase 1) | allow-all / empty | не enforced; `ALLOW_ANY_SIGNATURE`/`GET_OUT_OF_MY_WAY` | Apple AMFI с boot-args или crossxnu.AMFI | загрузка/отладка на произвольном железе |
| `strict` (future) | Apple trust caches / allowlist | проверка подписи и entitlements | Apple AMFI | приближение к macOS |
| `disabled` | нет | нет | нет | только синтаксическая сборка, не runtime |

`permissive` — **не** «по умолчанию безопасно». Это явно выбранный
режим, который должен быть виден в логах и документации.

## 4. Как должен работать permissive

### 4.1. Build

- `CodeSignature/Entitlements.h` — реальные константы (SDK/открытый
  источник); неправильные строки ломают фичи, но не ABI.
- `TrustCache/*` — либо настоящие заголовки, либо opaque-типы +
  compile-time ветка, которая не вызывает AMFI. Второй вариант —
  только для permissive; strict требует настоящих.
- `kern_trustcache.c`: под `CROSSXNU_SECURITY_PERMISSIVE`:
  - не паниковать при `amfi == NULL`;
  - `trust_cache_runtime_init()` — no-op/empty runtime;
  - `trust_cache_query()` — `KERN_SUCCESS`/`allow`;
  - не вызывать `amfi->TrustCache.*`.
- `kern_codesigning.c`: под тем же флагом выставлять
  `CS_CONFIG_ALLOW_ANY_SIGNATURE | CS_CONFIG_GET_OUT_OF_MY_WAY` в
  RELEASE (Apple парсит `amfi_get_out_of_my_way` только в
  DEVELOPMENT/DEBUG).
- `cs_*` syscalls и `cs_blob` не трогать.

### 4.2. Boot

Планируемый boot-arg:

```
crossxnu.security=permissive
```

(или `crossxnu_cs=permissive`; имя фиксируется в phase 2).

Он должен:
- печататься в boot log;
- быть видимым в `sysctl kern.crossxnu.security`;
- не включаться «по умолчанию» в strict-сборке.

Apple boot-args (`amfi=0x80`, `amfi_get_out_of_my_way=1`,
`cs_enforcement_disable=1`) — **не** наш интерфейс; они зависят от
версии/AMFI kext и в RELEASE XNU могут не парситься. Использовать их
можно как дополнительный слой, но не как гарантию.

### 4.3. AMFI

- Если загружается Apple AMFI kext, он может применять собственную
  политику независимо от XNU. Тогда permissive-режим должен либо
  передавать ему соответствующие boot-args, либо использовать
  собственный `crossxnu.AMFI`.
- `crossxnu.AMFI` реализует `amfi_t` и TrustCache-таблицу:
  - `query` → allow для всех;
  - `loadModule` → сохранить/проигнорировать;
  - `getCapabilities` → разумные значения;
  - entitlements — разбор без enforcement.
- Это отдельный kext; XNU ABI не меняется.

## 5. Что это значит для full userland

- `cs_*` syscalls должны существовать и возвращать согласованные
  значения; иначе `libSystem`/`amfid` сломаются.
- Entitlements должны **разбираться** (для API), даже если не
  ограничивают.
- Приложения, которые проверяют `CS_VALID`/`CS_DEBUGGED`, могут вести
  себя иначе; это ожидаемо в permissive.
- Apple-signed приложения и kext'ы могут всё ещё проверяться AMFI;
  permissive-режим не гарантирует их загрузку без trust caches.

## 6. Тесты, которые нужны до слова «работает»

1. Ядро грузится в QEMU с `crossxnu.security=permissive`.
2. `csops` на unsigned/ad-hoc/signed бинарнике не падает.
3. `launchd` стартует; `amfid`/`taskgated` не в panic-loop.
4. kext без подписи загружается (или явно отклоняется с понятным
   логом — это тоже решение).
5. `sysctl kern.crossxnu.security` показывает `permissive`.
6. В `uname -v`/boot log есть предупреждение.

До этого момента формулировка в README «ядро не реализует
безопасность» — **правильная и обязательная**.
