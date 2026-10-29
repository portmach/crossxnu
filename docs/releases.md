# Release notes и обязательные предупреждения

Каждый релиз/сборка crossxnu обязан содержать security-предупреждение.
Это не «дисклеймер в углу»: если его нет, релиз считается некорректно
оформленным.

## Шаблон

```markdown
# crossxnu <version> (<date>)

> ## ⚠️ SECURITY: permissive mode
>
> Это ядро **не реализует security-модель macOS**. TrustCache и
> CodeSignature работают в permissive-режиме: подпись, CDHash и
> entitlements не enforced. Любой загруженный код считается доверенным.
> Не используйте в production и на недоверенных устройствах.
> Подробности: SECURITY.md, docs/security-policy.md.

- XNU: xnu-12377.121.6
- Target: x86_64-apple-macos26.5
- Config: RELEASE / DEVELOPMENT
- Security profile: permissive
- Known blockers: ...
- Build log: ...
```

## Обязательный чек-лист релиза

- [ ] В README и release notes есть блок `SECURITY: permissive mode`.
- [ ] Указаны XNU-тег, target, config.
- [ ] Указан security profile (`permissive`/`strict`).
- [ ] Перечислены известные ABI/security gap'ы.
- [ ] В логе сборки видно предупреждение (build.sh печатает его).
- [ ] Нет Apple SDK/trust caches/AMFI/kext'ов в артефактах.
- [ ] Для strict-релиза — отдельный профиль и тесты, а не «почти
      permissive».

## Текущий статус

Phase 1: **permissive**. Ядро ещё не линкуется/не грузится, поэтому
runtime-поведение не проверено. Формулировка «ядро не реализует
безопасность» обязательна и точна.
