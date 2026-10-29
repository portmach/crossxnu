# Версии upstream

Все версии зафиксированы; «последняя» сама по себе не является версией.

| Компонент | Тег / коммит | Зачем | Лицензия |
|:----------|:-------------|:------|:---------|
| XNU | `xnu-12377.121.6` / `ac9718fb1af618d5ce8678d0dc6e8a58f252216f` | ядро Darwin/macOS 26.5 | APSL-2.0 |
| bootstrap_cmds | `bootstrap_cmds-138` / `c71d2d72f48995baaea76148f61002e5299841de` | MIG (`mig`, `migcom`) | APSL-2.0 |
| AvailabilityVersions | `AvailabilityVersions-157.2` / `149b1777f3e8c2133042d8e188f72e3adf6a7110` | `availability.pl` для `sys/_symbol_aliasing.h` | APSL-2.0 |
| libdispatch | `libdispatch-1542.100.32` / `701f4d1a24ae9c6863901bbbb22624b7d1b87321` | `libfirehose_kernel`, `os/` headers | Apache-2.0 |
| iig-port | `ea6d147d668ca15d490da638012243fcd705f30d` | portable DriverKit IIG | MIT |
| cctools-port | `904de2a71d4da6a9b30d2efaf912a10ddc7d9ddb` | Apple cctools/`ld64` 956.6 на Linux | APSL-2.0 |

## Почему именно 26.5

`xnu-12377.121.6` — тег ветки macOS 26.5. Нумерация XNU (`12377.x.y`) не
совпадает с маркетинговой (`26.5`); соответствие:

| macOS | XNU |
|:------|:----|
| 26.0 | `xnu-12377.1.9` |
| 26.1 | `xnu-12377.41.6` |
| 26.2 | `xnu-12377.61.12` |
| 26.3 | `xnu-12377.81.4` |
| 26.4 | `xnu-12377.101.15` |
| 26.5 | `xnu-12377.121.6` |

## Как обновлять

```bash
cd upstream/xnu
git fetch --depth 1 origin tag xnu-<new>
git checkout --detach xnu-<new>
cd ../..
# перебазировать patches/, обновить scripts/versions.sh и docs/versions.md
./scripts/bootstrap.sh
./scripts/build.sh --arch x86_64 --config RELEASE
```

После обновления обязательно:

1. `git -C upstream/xnu describe --tags` — проверить, что тег тот;
2. `patches/series` применяется целиком;
3. `make exporthdrs` проходит;
4. symbol table сравнён с Apple-сборкой нового тега.

## Замечание про `AvailabilityVersions`

`availability.pl` — источник списка версий для `_symbol_aliasing.h`.
В зафиксированном `AvailabilityVersions-157.2` список заканчивается
macOS 14.3; для 26.5 он неполон. Это влияет на экспортируемые заголовки,
не на код ядра. При появлении нового тега `AvailabilityVersions`
обновить его и перегенерировать SDK.
