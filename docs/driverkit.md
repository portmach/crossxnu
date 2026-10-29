# DriverKit: отложено до phase 5

**Статус:** решение принято 2026-10-29.
**Область:** permissive-сборка `x86_64`, phase 1.

## Решение

DriverKit/IIG **не реализуем** в phase 1 вручную. Сборка останавливается
на DriverKit-зависимых местах IOKit (`IODMACommand::CompleteDMA` и
следующие), и это фиксируется как известное ограничение, а не
маскируется заглушками.

Полноценный DriverKit возвращаем, когда появятся **реальные проблемы с
kext’ами** (phase 5), а не сейчас.

## Почему нельзя просто налепить stub-классы

`DriverKit/*.h` — это не обычные заголовки. Это вывод **IIG** из
`iokit/DriverKit/*.iig`:

- генерирует C++-классы и их методы;
- задаёт порядок виртуальных функций;
- добавляет `_Methods`/`_KernelMethods`;
- генерирует константы и `.iig.cpp` с реализациями.

Примеры, на которых мы уже остановились:

| Место | Что требуется |
|:------|:--------------|
| `IOSystemStateNotification : IOService` | полный `IOService`, а не forward declaration |
| `IOUserServer.h` | `OSAction` (можно forward, но только для указателя) |
| `IODMACommand.cpp` | `CompleteDMA()` — метод, сгенерированный IIG |
| `IOBufferMemoryDescriptor` | layout/поля, которые использует DriverKit-код |

Если объявить `CompleteDMA()` вручную, нужно:

- попасть в vtable в правильном порядке;
- реализовать метод (или сделать no-op, меняя поведение);
- повторить это для десятков методов `IOService`, `OSObject`, `IOUserClient`, `IOMemoryDescriptor` и т.д.

Это не «ещё немного работы», а реимплементация IIG с риском ABI-несовместимости.
Ошибка проявится не при сборке, а при загрузке kext’а.

## Что уже сделано

- DriverKit `.iig.cpp` и `iokit/DriverKit` исключены из сборки
  (патчи 0002, 0003, 0008).
- Исключены DriverKit-зависимые IOKit-файлы:
  `iokit/Kernel/IODMACommand.cpp`,
  `iokit/Kernel/IOUserClient.cpp`,
  `iokit/Kernel/IOUserServer.cpp`,
  `iokit/Kernel/IOExtensiblePaniclog.cpp`.
- Для permissive-SDK добавлены только безопасные вещи:
  forward declaration `OSAction`, константы `IODMACommand`/`IOMemoryDirection`,
  include `IOService.h`, подавление `-Wno-unused-private-field`.
- `IODMACommand::CompleteDMA` **не** застаблен: сборка осознанно
  останавливается здесь.

## Следствие для линковки

Из-за исключения `IOUserClient.cpp`/`IOUserServer.cpp` линковка ядра
закономерно падает на символах вида:

```text
is_io_iterator_next
is_io_iterator_reset
is_io_service_get_matching_services
is_io_registry_entry_get_property
is_io_registry_create_iterator
...
```

Это **не новая ошибка**: мы сами убрали файлы, которые их реализуют.
Пока DriverKit/IOKit-часть отложена, полностью слинкованного ядра не
будет. Это принятое ограничение phase 1, а не регрессия.

## Последствия

- permissive-ядро не собирается полностью, пока DriverKit-часть не
  закрыта;
- DriverKit-kext’ы не поддерживаются;
- обычные kext’ы, не использующие DriverKit, тоже не проверены;
- в README/статусе это должно быть видно, а не выдаваться за «почти
  работает».

## Когда возвращаться

Критерий: phase 5 и реальный kext smoke-test, а не «стало интересно».
Тогда выбрать один путь:

1. **IIG-заголовки из SDK/KDK** — самый надёжный, но SDK-зависимость;
2. **Реимплементация IIG** — большой отдельный проект;
3. **Собственный минимальный IIG** для нужного подмножества классов —
   только если тесты покажут, что подмножество действительно мало.

До этого не добавлять `-Wno-unreachable-code`, фиктивные vtable-методы
и «заглушки, чтобы собралось».
