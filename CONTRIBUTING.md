# Contributing

Спасибо, что помогаете PortMach. Правила простые.

## Язык

- Документация и обсуждения — русский или английский.
- Код, имена файлов, commit messages — английский.
- В документах допустим bilingual-формат, как в `MachOS/README.md`.

## Патчи

1. Один патч — одна причина; см. [`docs/patches.md`](docs/patches.md).
2. Патч должен применяться к чистому `xnu-12377.121.6`.
3. Если патч меняет ABI — `ABI-RISK:` в заголовке и запись в
   [`docs/compatibility.md`](docs/compatibility.md).
4. Не добавляйте Apple-бинарники, SDK, kext'ы, shared cache.
5. Не «упрощайте» ядро, вырезая подсистемы; исключение не-ядерных
   компонентов (DriverKit) должно быть обосновано и временно.

## Сборка перед PR

```bash
./scripts/bootstrap.sh
./scripts/build.sh --arch x86_64 --config RELEASE --target exporthdrs
# и, если линковка уже работает:
./scripts/build.sh --arch x86_64 --config RELEASE
```

Приложите:
- версию clang/LLVM (`clang --version`);
- лог `build/log/...`;
- что именно изменилось в поведении сборки/ABI.

## Стиль скриптов

- `set -euo pipefail`;
- пути только через `scripts/env.sh`;
- никаких `sudo` внутри скриптов;
- комментарии — почему, а не что.

## Лицензия

Отправляя патч, вы соглашаетесь, что он распространяется под APSL-2.0
(для кода XNU) или MIT (для оригинальных скриптов), см.
[`docs/legal.md`](docs/legal.md).
