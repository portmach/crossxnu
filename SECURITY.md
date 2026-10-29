# Security policy / Политика безопасности

> **Коротко:** crossxnu находится в **permissive security mode**.
> Ядро **не проверяет** доверие к коду и **не обеспечивает** security-модель
> macOS. Не используйте его как замену защищённому macOS и не выставляйте
> в сеть/на устройство, где важна безопасность.

## 1. Область действия

Это относится к двум связанным подсистемам:

| Подсистема | Что делает в macOS | Что делает crossxnu сейчас |
|:-----------|:-------------------|:---------------------------|
| **TrustCache** | быстрый whitelist CDHash'ей, которым разрешено исполняться/загружаться; наполняется Apple Secure Boot / iBoot / kext-загрузкой | **не проверяется**; permissive |
| **CodeSignature** | `cs_*` syscalls, разбор code signature blobs, CDHash, entitlements, AMFI, `amfid`/`taskgated` | **не enforced**; syscalls/ABI сохраняются, проверки отключены или permissive |

TrustCache — **часть** CodeSignature/AMFI, а не отдельная «опция». Нельзя
сделать TrustCache permissive и при этом считать, что CodeSignature
работает: AMFI и `cs_*` — отдельный слой.

## 2. Что именно не защищено

В permissive-режиме:

- неподписанный код может исполняться;
- CDHash не сверяется с trust cache;
- подпись и целостность кода не проверяются;
- entitlements не являются ограничением: приложение не получает
  привилегии «по подписи», но и не блокируется за их отсутствие;
- AMFI-политика (хардненинг, restricted entitlements) не гарантируется;
- kext-подпись/доверие не обеспечивается на уровне нашего ядра.

Это **не** «совместимость с macOS»; это сознательное отключение защиты
ради загрузки и отладки на произвольном железе.

## 3. Текущий статус

- [x] Решение: phase 1 — permissive.
- [x] README/документация предупреждают.
- [ ] Runtime-реализация permissive (ядро ещё не линкуется/не грузится).
- [ ] Единый boot-arg `crossxnu.security=permissive`.
- [ ] Замена Apple AMFI на собственный провайдер или явная политика
      поверх Apple AMFI.
- [ ] Strict-режим и тесты.

Пока ядро не загружается, «permissive» — это **заявленный режим
сборки/поведения**, а не проверенная runtime-функция. Не считайте
отсутствие проверок «работающим» до phase 2.

## 4. Планируемая архитектура

Один профиль безопасности, а не набор разрозненных заглушек:

```text
crossxnu.security=permissive   (phase 1, по умолчанию)
    trustcache:  allow-all / empty runtime
    codesign:    CS_CONFIG_ALLOW_ANY_SIGNATURE | CS_CONFIG_GET_OUT_OF_MY_WAY
    entitlements: parse, do not enforce
    amfi:        Apple AMFI with permissive boot-args, or crossxnu.AMFI stub

crossxnu.security=strict       (future)
    trustcache:  Apple trust caches / user allowlist
    codesign:    verify signatures, enforce entitlements
    amfi:        Apple AMFI or compatible implementation
```

### 4.1. TrustCache

- Build: нужны реальные типы `TrustCache_t`/`TrustCacheRuntime_t` или
  явно изолированный permissive-путь, который их не разыменовывает.
- Runtime: в permissive-режиме `kern_trustcache.c` не должен паниковать
  при отсутствии AMFI и не должен вызывать `amfi->TrustCache.query`.
- Если используется Apple AMFI kext, его собственная политика может
  игнорировать наш permissive-флаг; тогда нужен либо AMFI boot-arg, либо
  собственный провайдер.

### 4.2. CodeSignature

- `cs_*` syscalls и `cs_blob` **не удаляются**: это ABI, их ждёт userland.
- `CodeSignature/Entitlements.h` — только константы; нужны настоящие
  значения, иначе entitlement'ы будут молча не работать.
- В permissive-режиме XNU должен:
  - не отклонять код из-за отсутствия/недействительности подписи;
  - сохранять разбор entitlements (для совместимости API), но не
    использовать их как запрет;
  - выставлять `CS_CONFIG_ALLOW_ANY_SIGNATURE` и
    `CS_CONFIG_GET_OUT_OF_MY_WAY` (в RELEASE — через явный патч, т.к.
    Apple парсит `amfi_get_out_of_my_way` только в DEVELOPMENT/DEBUG).
- `amfi_get_out_of_my_way`/`amfi=0x80` — не «наш» флаг; это Apple
  boot-args, и их поддержка зависит от сборки/AMFI kext.

### 4.3. AMFI

AMFI — отдельный kext, который регистрирует `amfi_t` через
`amfi_interface_register()`. XNU не реализует trust-проверки сам.

Для full userland есть два пути:

1. **Apple AMFI** (рекомендуется для совместимости): загрузить
   `AppleMobileFileIntegrity.kext`, использовать его boot-args; trust
   caches — из пользовательского образа macOS.
2. **crossxnu.AMFI**: собственный kext с `amfi_t` и TrustCache-таблицей,
   permissive-политикой. Это отдельный компонент; XNU ABI не меняется.

## 5. Что нельзя делать

- Не выдавать permissive-режим за «полную совместимость с macOS».
- Не коммитить Apple trust caches, AMFI kext, SDK или ключи.
- Не отключать проверки «тихо»: режим должен быть явным, логируемым и
  отображаться в `uname`/boot log/документации.
- Не использовать проект как security boundary.

## 6. Reporting

Это исследовательский проект, а не продукт с программой bug bounty.
Если вы нашли проблему, которая **ухудшает** и без того permissive
режим (например, panic/повреждение памяти, а не «отсутствие проверки»),
оформите issue с логом и шагами. Не публикуйте эксплойты против
macOS/третьих лиц.
