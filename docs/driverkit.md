# DriverKit/IIG: генерация без SDK

**Статус:** интегрировано 2026-10-29.
**Инструмент:** [`Nyktis/iig-port`](https://github.com/Nyktis/iig-port)
(MIT), portable-реализация Apple IIG на libclang.

## Почему это вообще проблема

Apple `iig` — закрытый инструмент из Xcode. В open-source XNU лежат только
входные файлы `iokit/DriverKit/*.iig`; без IIG нет ни `DriverKit/*.h`, ни
`*.iig.cpp`. Именно поэтому сначала пришлось исключать DriverKit-файлы:
это не «забыли сгенерировать», а отсутствие генератора.

Ручные stub-классы для IOKit не годятся: IIG задаёт C++-layout, vtable и
`_Methods`/`_KernelMethods`, а не только имена. Ошибки
`IODMACommand::CompleteDMA` и `IOSystemStateNotification` были именно
следствием отсутствующих сгенерированных заголовков.

## Что сделано

- `upstream/iig-port` — submodule, MIT.
- `scripts/build-iig.sh` собирает `iig` из `iig.cpp` + libclang.
- `scripts/generate-driverkit.sh` генерирует 18 заголовков и
  `.iig.cpp` из `iokit/DriverKit/*.iig`.
- `toolchain/shims/iig/include` — минимальные host-заголовки для
  парсинга Darwin-типов на Linux (не SDK).
- `patches/0006` (отключение `_OS_ADD_METHODS_dispatch`) удалён:
  теперь `IODMACommand_Methods` и остальные макросы существуют.
- `patches/0008` (исключение DriverKit-файлов) удалён.
- `scripts/build-firehose.sh` собирает `libfirehose_kernel.a`.

Генерация запускается из `bootstrap.sh` после `make-sdk.sh`:

```bash
./scripts/bootstrap.sh
```

## Проверка совпадения с Apple

`iig-port` содержит эталонный вывод Xcode IIG для XNU 26.0
(`DriverKit-440`). Сравнение с нашим выводом:

- 18 заголовков и `.edits` совпадают, кроме строки баннера
  `portable` и реальных изменений 26.5 (например, `IOUserServer::Panic`);
- `.iig.cpp` отличается только баннером для 17 файлов;
- `IOUserServer` отличается из-за нового метода в 26.5.

Это не побайтовое доказательство ABI-идентичности с Xcode 26.5, но
несравнимо лучше ручных заглушек. Для strict/full-kext всё равно нужно
сравнить таблицу символов и vtable с Apple-сборкой.

## Что это дало

- DriverKit-файлы компилируются, `IODMACommand::CompleteDMA` и
  `_Methods`-макросы на месте.
- Ядро **линкуется** (`kernel`/`kernel.unstripped`).
- `libfirehose_kernel` и `libcc_kext`-shim собираются скриптами.
- Осталась проблема Mach-O layout (`ld64.lld` игнорирует `-static`,
  `-segaddr`, `-image_base`), а не IIG.

## Ограничения

- `iig-port` основан на поведении Xcode 26.3, а не 26.5; при обновлении
  XNU нужно перегенерировать и по возможности сравнивать с эталоном.
- `iig-port` — сторонний MIT-проект, не Apple; ошибки генератора — наши.
- Для распространения соблюдать MIT/NOTICE `iig-port` (см.
  [`legal.md`](legal.md)).
