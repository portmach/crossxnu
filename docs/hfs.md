# HFS+ root: план и первые результаты

## Почему это отдельный проект

В XNU **нет ни одной файловой системы**: `bsd/vfs` — только VFS-ядро.
HFS+, APFS, exFAT и msdos — это kext'ы. HFS+ — `com.apple.filesystems.hfs.kext`,
и его исходники **открыты**: [`apple-oss-distributions/hfs`](https://github.com/apple-oss-distributions/hfs)
(в репозитории — `upstream/hfs`, тег `hfs-715.100.10`).

APFS закрыт; `apfs-fuse`/`linux-apfs-rw` — userland/Linux, не XNU-kext.

## Что уже проверено

### Блочное устройство

В XNU есть готовый memory block device: [`bsd/dev/memdev.c`](../upstream/xnu/bsd/dev/memdev.c).
`mdevadd(devid, base, size, phys)` создаёт `/dev/mdN` (block + char), а
`mdevstrategy` умеет читать/писать область памяти. Этого достаточно для
ramdisk-root, без IOStorageFamily и без драйверов AHCI/NVMe.

### HFS+ образ без macOS

`xorrisofs` (libisofs) умеет `-hfsplus`:

```bash
xorrisofs -hfsplus -o root.iso rootdir/
```

Проверено на тестовом дереве: HFS+ volume header (`H+`) лежит по смещению
`0x10000` (128 секторов), а `dd if=root.iso of=root.hfs bs=512 skip=128`
даёт образ, который `7z -tHFS` читает как HFS+ (файлы, каталоги, symlink
видны). Значит, HFS+ можно собрать без macOS и без mount.

Ограничение: `xorrisofs` пишет hybrid ISO; нужно проверить, что HFS+-том
самодостаточен (extents не ссылаются на данные вне тома) и что
symlink/права сохраняются. Если нет — есть `hfsprogs` (`newfs_hfs`) и
`hfsplus` (`hpmount`/`hpcopy`), либо libguestfs.

### Recovery userland

В установщике есть `AssetData/usr/standalone/update/ramdisk/x86_64SURamDisk.dmg`
(260 MB, **APFS**, `ramdisk.apfs`) с `sbin/launchd`, `usr/lib/dyld` и
`System/Library/CoreServices`. Файлы можно вытащить `7z`, но монтировать
этот APFS нашим ядром пока нельзя — поэтому перепаковываем в HFS+.

## Этапы

1. **HFS+ в ядро.** Собрать `upstream/hfs/core` в состав ядра (не kext,
   чтобы не зависеть от KDK) и зарегистрировать `hfs_vfsops` через
   `vfs_fsadd()` на старте. HFS-kext использует `hfs_iokit.cpp`; для
   in-tree варианта достаточно `vfs_fsadd` + `hfs_init`.
2. **mdev-root.** Патч `setconf()`: найти сегмент `__ROOTIMG`,
   `mdevadd()` из него, выставить `rootdev`/`rootdevice="md0"` и не звать
   `IOFindBSDRoot`.
3. **Образ.** Собрать HFS+ из recovery-файлов (`xorrisofs -hfsplus`),
   вырезать том по offset 0x10000, проверить `fsck`/7z.
4. **Упаковка.** Добавить `__ROOTIMG,__root` в `kernel.kc` (post-processor
   или `ld -sectcreate`), чтобы загрузчик поднял образ в память.
5. **Boot.** HFS+ монтируется как root; запускается `launchd` из
   recovery-userland. Дальше — writable `/var`/`/tmp` (tmpfs/ramfs) и
   реальные storage-драйверы.

## Риски

- HFS+ core — большой C-код с приватными заголовками XNU; потребуется
  отдельная сборка/портирование (не «один патч»).
- Hybrid HFS+ из `xorrisofs` может не сохранять POSIX-метаданные;
  проверить symlink/uid/gid.
- Recovery-userland может требовать APFS-специфику; тогда HFS+ root
  подойдёт только для минимального shell/launchd-теста.

## Результат

HFS+ собран в ядро (38 `.c` из `upstream/hfs/core`), `vfs_fsadd()`
вызывается из `setconf()`. `__ROOTIMG` добавляется в `kernel.kc`
скриптом `scripts/kc-add-rootimg.py`, `mdevadd()` создаёт `/dev/md0`,
rootdev выставляется на него. Тестовый HFS+ образ монтируется:

```text
crossxnu: built-in HFS+ registered
Added memory device md0/rmd0 ...
crossxnu: root device md0 (331776 bytes)
hfs: mounted ISOIMAGE on device b(1, 0)
vm: initializing swap
```

Дальше создаётся pid 1 (`init`) и ядро падает в
`IOCurrentTaskHasEntitlement` — нужен настоящий recovery-root с
`/sbin/launchd` и разбор прав/entitlements.

## Recovery launchd

Полный recovery-root (`x86_64SURamDisk.dmg`, перепакованный в HFS+)
монтируется, `load_init_program` запускает `/sbin/launchd`, тот
печатает Darwin Ignition Sequence. Затем recovery сам завершает
работу: `ignition blob not available` — нужен ignition blob от
iBoot (или обычный, не-recovery root). Это не паника ядра.

## payloadv2 (обычный system root)

`payloadv2/payload.*` — это `pbzx` (xz-чанки), после распаковки получается
**Apple Archive** (`YAA1`), а не cpio. Раньше здесь было записано, что крупные
файлы «размазаны по сегментам»: это оказалось ошибкой усечённой распаковки
(лимит 8 MiB), а не формата. Полный разбор форматов, инструменты и результат
(19 GB, 179 712 файлов) — в [`rootfs.md`](rootfs.md).

Важно: корневой том из payload'ов **не самодостаточен** — `libSystem` и общий
dyld shared cache лежат в системном cryptex, а в asset'е есть только диффы к
нему. См. [`rootfs.md`](rootfs.md#чего-в-rootе-нет-cryptex).


## Запись на свежий том: `_FORTIFY_SOURCE_STRICT` и `cat_create`

Первый же `mount` тома, созданного `newfs_hfs` на `/dev/md1`, валил ядро:

```text
panic: Kernel trap at 0xffffff8000930c97, type = 6=invalid opcode
  cat_create +0x277   (инлайн buildrecord)
  hfs_privatedir_init
  hfs_MountHFSPlusVolume
  hfs_mountfs
  hfs_mount
```

Сообщения `hfs: …` перед паникой не было, `hfs_assert` не срабатывал — значит
это не assert, а `ud1/ud2`, который clang поставил сам.

### Причина

Ядро XNU собирается с `-DXNU_KERNEL_PRIVATE`, поэтому в
[`osfmk/string.h`](../upstream/xnu/osfmk/string.h) выбирается
`__XNU_FORTIFY_SOURCE == 2` (он же `_FORTIFY_SOURCE_STRICT`): `memmove()`,
`memcpy()` и `bcopy()` проверяют, что копия не выходит за **поле**, а не за
**структуру**.

HFS+ хранит 32 байта Finder Info как два поля по 16 байт — `userInfo` и
`finderInfo`, — и `buildrecord()` копирует их одной операцией:

```c
bcopy(attrp->ca_finderinfo, &crp->hfsPlusFolder.userInfo, 32);
```

clang 23 считает размер поля `userInfo` равным 16, сворачивает `16 < 32` в
константу `true` и оставляет от `bcopy` только заглушку `ud2` — остальные
записи каталога (`textEncoding`, `folderCount`, `bsdInfo`) при этом
объявляются недостижимыми и выбрасываются. Отсюда «invalid opcode» при
создании **любого** каталога: `hfs_privatedir_init()` вызывает `cat_create()`
для служебных каталогов, а на корневом томе они уже есть, поэтому корень
монтировался.

Доказательство — сборка того же файла с `-O0` (там проверка ещё не свёрнута):

```text
movq  $0x10, -0x70(%rbp)     ; размер поля userInfo = 16
movq  $0x20, -0x78(%rbp)     ; длина копии = 32
cmpq  -0x50(%rbp), %rax
jae   ...                    ; если 16 >= 32 — продолжаем
ud1l  (%rax), %eax           ; иначе trap
ud2
```

`-fno-strict-aliasing` (добавлен в [`scripts/build.sh`](../scripts/build.sh))
на это не влияет — trap оставался, менялся только адрес.

### Исправление

Четыре копии Finder Info в [`hfs_catalog.c`](../upstream/xnu/bsd/hfs/hfs_catalog.c)
(`buildrecord()` — каталог и файл, `catrec_update()` — каталог и файл)
переведены на `__nochk_bcopy()`. Это штатный escape hatch из `string.h` для
bytewise-копий, которые сознательно пересекают границы полей: проверка идёт по
размеру записи (от `userInfo` до конца `HFSPlusCatalogFolder` — 40 байт), что
для 32-байтовой копии корректно.

Проверка, что заглушек больше нет (в собранном ядре):

```bash
llvm-objdump --disassemble --no-show-raw-insn kernel | grep -A280 '<_cat_create>:'
```

Единственный оставшийся `ud2` в `cat_create` — законная проверка длины имени в
`buildthread()` (`nodeName.length >= 256`, для HFS+ недостижима).

### Результат

Свежий том монтируется, каталоги создаются, файлы пишутся и читаются:

```text
sh-3.2# newfs_hfs -v scratch /dev/md1
Initialized /dev/rmd1 as a 256 MB case-insensitive HFS Plus volume
sh-3.2# mount -t hfs /dev/md1 /private/var
hfs: mounted scratch on device md1
sh-3.2# mkdir -p /private/var/a/b/c
sh-3.2# echo hello-hfs > /private/var/hello
sh-3.2# cat /private/var/hello
hello-hfs
sh-3.2# ls -l /private/var
drwxr-xr-x  3 root  wheel  102 Jan  1 00:36 a
-rw-r--r--  1 root  wheel   10 Jan  1 00:31 hello
drwxr-xr-x  2 root  wheel   68 Jan  1 00:31 test
sh-3.2# df /private/var
/dev/md1       524288 12328    511960     3%       7 4294967272    0%   /private/var
sh-3.2# mount
/dev/md1 on /private/var (hfs, local)
```

Мелочи, которые видны в логе и не мешают:

- `mdevioctl: unsupported ioctl 0xc01864ca` + `hfs: _DKIOCCSMAP error: 25` —
  первая запись в файл просит content-sum map (`DKIOCCSMAP`), `memdev` его не
  умеет; HFS+ считает это некритичным (`bytes_mapped: 0`) и пишет дальше.
- `ifree 4294967272` в `df` — 32-битное переполнение в `statfs` для HFS+
  (не влияет на запись).
