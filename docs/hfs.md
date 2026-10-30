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
