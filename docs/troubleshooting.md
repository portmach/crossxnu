# Troubleshooting

Короткий справочник по ошибкам, которые уже встречались. Полный контекст —
[`build-arch.md`](build-arch.md) и [`status.md`](status.md).

## `xcrun: unsupported invocation`

Мейкфайл вызвал системный `xcrun` вместо шима. Проверьте:

```bash
which xcrun            # должен быть toolchain/bin/xcrun
echo "$PATH" | tr ':' '\n' | head
```

`scripts/build.sh` передаёт `XCRUN=...` явно; если запускаете `make`
вручную — передайте так же.

## `no such include directory: .../usr/local/include/kernel`

Не создан synthetic SDK. Выполните:

```bash
./scripts/make-sdk.sh
```

Каталоги `usr/local/include/{kernel,iBoot}` и
`Kernel.framework/.../PrivateHeaders/{AppleFeatures,platform}` должны
существовать, даже если пусты: clang 23 считает
`-Wmissing-include-dirs` ошибкой.

## `def: No such file or directory`

Собирается `iokit/DriverKit` и вызывается Apple IIG (`def`).
В phase 1 DriverKit исключён патчами 0002/0003. Проверьте:

```bash
cd upstream/xnu && git diff -- iokit/Makefile iokit/conf/Makefile.template
```

Если патчи не применились — `./scripts/apply-patches.sh`.

## `unknown builtin '__builtin_xnu_type_summary'`

Upstream clang не имеет Apple-расширений. Патч 0004 даёт fallback.
Если ошибка осталась — проверьте, что `patches/series` применён
целиком; затем очистите `BUILD/obj` и пересоберите.

Аналогично для `__builtin_xnu_type_signature` и
`__builtin_xnu_types_compatible`.

## `fatal error: 'TrustCache/API.h' file not found`

В permissive-сборке используется `toolchain/shims/permissive/TrustCache/API.h`
(см. `--security permissive`). Если файл всё ещё не найден — проверьте,
что `CFLAGS_EXTRA` содержит `-I.../toolchain/shims/permissive`.
Strict-сборка требует настоящий заголовок из SDK 26.5.

## `fatal error: 'os/firehose_buffer_private.h' file not found`

Не скопированы `os/*.h` из `libdispatch` в SDK. `make-sdk.sh` делает это,
если submodule `upstream/libdispatch` инициализирован.

## `undefined symbol: __firehose_*`

Не собрана `libfirehose_kernel.a`. Это следующий шаг phase 1:
`src/firehose/firehose_buffer.c` из libdispatch + MIG-заголовки.

## `ld64.lld: warning: Option '-static' is not yet implemented`

LLVM 23 ещё не реализовал `-static` для Mach-O. Ядро может получить
`MH_DYLDLINK`/`LC_DYLD_*`. Это главный риск загрузки; см.
`compatibility.md` §4.1. Варианты: обновить LLVM, пост-обработка
Mach-O, свой упаковщик.

## OOM / killed на LTO

Уменьшите параллелизм:

```bash
./scripts/build.sh --jobs 2
```

и увеличьте RAM WSL (`%UserProfile%\.wslconfig` → `memory=16GB`).

## Сборка идёт очень медленно

Дерево на `/mnt/c`. Перенесите в ext4:

```bash
mkdir -p ~/src && cp -a /mnt/c/.../crossxnu ~/src/ && cd ~/src/crossxnu
```
