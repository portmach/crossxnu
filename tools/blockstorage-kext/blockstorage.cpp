/*
 * com.crossxnu.driver.CrossXnuBlockStorage
 *
 * A block storage device for bring-up, so APFS gets an IOMedia to mount:
 * IOBlockStorageDevice -> IOBlockStorageDriver -> IOMedia -> AppleAPFS.
 *
 * Two backends, picked in start():
 *
 *   AHCI  A real (large) disk attached to QEMU's ich9 AHCI controller.  This
 *         is the interesting one: the volume lives in a host file, so it is
 *         not limited by the kernel collection's size.  There is no
 *         IOPCIFamily in this kernel, hence no IOPCIDevice nub, so the
 *         controller is found through PCI config space (ports 0xCF8/0xCFC)
 *         and its ABAR is mapped through IOMemoryDescriptor.
 *
 *   RAM   A region of the kernel's own memory: the __APFSIMG segment that
 *         scripts/kc-add-segment.py appends to the collection.  Fallback when
 *         no AHCI disk is attached; writes are lost on reboot, and the image
 *         cannot exceed the space left under bootinfo.
 *
 * Publishing is deferred: the media BSD clients (IOMediaBSDClient,
 * AppleAPFSMediaBSDClient) match on IOResourceMatch = IOBSD, which
 * IOKitBSDInit() publishes near the end of bsd_init().  A media registered
 * earlier never gets a /dev node, and without a node there is nothing to
 * mount.  So the kmod start() only builds the object; a timer on our own work
 * loop waits for the IOBSD property and then attaches, starts and registers.
 */

#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/IOTimerEventSource.h>
#include <IOKit/storage/IOBlockStorageDevice.h>
#include <libkern/kernel_mach_header.h>
#include <mach/kmod.h>
#include <string.h>

#define kBlockStorageBlockSize 4096
#define kBlockStorageImageSegment "__APFSIMG"
#define kBlockStorageImageMinimum 4096

/* Sector size every ATA disk reports, and the granularity of
 * doAsyncReadWrite() once reportBlockSize() has said so. */
#define kAHCIBlockSize 512
/* One command moves at most this much.  AHCI's PRDT has a 64K boundary rule:
 * a single entry must not describe memory that crosses a 64 KiB boundary, and
 * a 128 KiB transfer through one entry hangs the emulated controller.  The
 * bounce buffer is allocated 64 KiB aligned and transfers never exceed 64 KiB,
 * so the rule cannot be broken. */
#define kAHCIMaxTransfer (64 * 1024)
#define kAHCIBounceAlign (64 * 1024)

/* Kernel-side helper (bsd/kern/bsd_init.c) that mounts the volume once its
 * /dev node exists: mounting needs kernel_mount() and VFS internals, which a
 * kext cannot call. */
extern "C" void crossxnu_mount_apfs_volume(void);

/* Every kext needs a kmod_info with start/stop entry points. */
extern "C" kern_return_t crossxnu_blockstorage_start(kmod_info_t *ki, void *data);
extern "C" kern_return_t crossxnu_blockstorage_stop(kmod_info_t *ki, void *data);

/* ------------------------------------------------------------------ */
/* AHCI                                                                */
/* ------------------------------------------------------------------ */

/* PCI config space, mechanism #1.  With no IOPCIFamily there is no
 * IOPCIDevice to ask, and the ports are the only way to find the controller. */
static inline void
pciOut(UInt16 port, UInt32 value)
{
	__asm__ volatile ("outl %0, %1" : : "a"(value), "Nd"(port));
}

static inline UInt32
pciIn(UInt16 port)
{
	UInt32 value;

	__asm__ volatile ("inl %1, %0" : "=a"(value) : "Nd"(port));
	return value;
}

static UInt32
pciConfigRead(UInt8 bus, UInt8 slot, UInt8 func, UInt8 offset)
{
	UInt32 address = 0x80000000U | ((UInt32)bus << 16) |
	    ((UInt32)(slot & 0x1F) << 11) | ((UInt32)(func & 7) << 8) |
	    (offset & 0xFC);

	pciOut(0xCF8, address);
	return pciIn(0xCFC);
}

static void
pciConfigWrite(UInt8 bus, UInt8 slot, UInt8 func, UInt8 offset, UInt32 value)
{
	UInt32 address = 0x80000000U | ((UInt32)bus << 16) |
	    ((UInt32)(slot & 0x1F) << 11) | ((UInt32)(func & 7) << 8) |
	    (offset & 0xFC);

	pciOut(0xCF8, address);
	pciOut(0xCFC, value);
}

/* HBA registers, relative to the ABAR. */
#define AHCI_CAP         0x00
#define AHCI_GHC         0x04
#define AHCI_PI          0x0C
#define AHCI_PORTS       0x100
#define AHCI_PORT_STRIDE 0x80

/* Port registers, relative to AHCI_PORTS + port * stride. */
#define AP_CLB  0x00
#define AP_CLBU 0x04
#define AP_FB   0x08
#define AP_FBU  0x0C
#define AP_IS   0x10
#define AP_CMD  0x18
#define AP_TFD  0x20
#define AP_SIG  0x24
#define AP_SSTS 0x28
#define AP_SERR 0x30
#define AP_CI   0x38

#define AP_CMD_ST  (1U << 0)
#define AP_CMD_FRE (1U << 4)
#define AP_CMD_FR  (1U << 14)
#define AP_CMD_CR  (1U << 15)

#define AP_IS_TFES (1U << 30)

#define AHCI_DEV_PRESENT 3U
#define AHCI_SIG_ATA     0x00000101U

#define FIS_TYPE_H2D 0x27
#define ATA_CMD_IDENTIFY      0xEC
#define ATA_CMD_READ_DMA_EXT  0x25
#define ATA_CMD_WRITE_DMA_EXT 0x35
#define ATA_CMD_FLUSH_CACHE_EXT 0xEA

struct crossxnu_ahci
{
	volatile UInt32 *   regs;        /* mapped ABAR */
	IOMemoryDescriptor *abarDesc;
	IOMemoryMap *       abarMap;
	UInt32              abarPhys;

	UInt32              cap;
	UInt32              pi;

	int                 port;        /* chosen port */
	UInt64              sectors;     /* 512-byte sectors on that port */

	UInt32 *            cl;          /* command list, 1 KB, 1 KB aligned */
	IOPhysicalAddress   clPhys;
	UInt8 *             ct;          /* command table, 4 KB, 128 B aligned */
	IOPhysicalAddress   ctPhys;
	UInt8 *             bounce;      /* staging buffer, kAHCIMaxTransfer */
	IOPhysicalAddress   bouncePhys;
};

class com_crossxnu_BlockStorage : public IOBlockStorageDevice
{
	OSDeclareDefaultStructors(com_crossxnu_BlockStorage);

	typedef IOBlockStorageDevice super;

private:
	enum { kBackendNone = 0, kBackendAHCI, kBackendRAM };

	int                  _backend;
	char *               _image;          /* RAM backend: kernel VA */
	UInt64               _imageSize;
	UInt64               _blockCount;     /* in _blockSize units */
	UInt32               _blockSize;
	struct crossxnu_ahci _ahci;

	IOWorkLoop *         _workLoop;
	IOTimerEventSource * _timer;
	int                  _waits;
	bool                 _loggedRead;
	bool                 _loggedWrite;

	static void publishTimer(OSObject *owner, IOTimerEventSource *sender);

	bool initAHCI(void);
	void freeAHCI(void);
	bool attachAHCI(int port);
	IOReturn ahciCommand(UInt8 command, UInt64 lba, UInt16 count,
	                     IOPhysicalAddress bufferPhys, UInt32 bytes,
	                     bool write);
	IOReturn ahciReadWrite(IOMemoryDescriptor *buffer, UInt64 block,
	                       UInt64 nblks, bool write, IOByteCount *done);
	bool initRAM(void);

public:
	virtual bool     init(OSDictionary *properties) APPLE_KEXT_OVERRIDE;
	virtual bool     start(IOService *provider) APPLE_KEXT_OVERRIDE;
	virtual void     free(void) APPLE_KEXT_OVERRIDE;

	bool publish(IOService *provider);
	void schedulePublish(void);

	virtual IOReturn doEjectMedia(void) APPLE_KEXT_OVERRIDE;
	virtual IOReturn doFormatMedia(UInt64 byteCapacity) APPLE_KEXT_OVERRIDE;
	virtual UInt32   doGetFormatCapacities(UInt64 *capacities,
	                                       UInt32 capacitiesMaxCount) const APPLE_KEXT_OVERRIDE;
	virtual char *   getVendorString(void) APPLE_KEXT_OVERRIDE;
	virtual char *   getProductString(void) APPLE_KEXT_OVERRIDE;
	virtual char *   getRevisionString(void) APPLE_KEXT_OVERRIDE;
	virtual char *   getAdditionalDeviceInfoString(void) APPLE_KEXT_OVERRIDE;
	virtual IOReturn reportBlockSize(UInt64 *blockSize) APPLE_KEXT_OVERRIDE;
	virtual IOReturn reportEjectability(bool *isEjectable) APPLE_KEXT_OVERRIDE;
	virtual IOReturn reportMaxValidBlock(UInt64 *maxBlock) APPLE_KEXT_OVERRIDE;
	virtual IOReturn reportMediaState(bool *mediaPresent,
	                                  bool *changedState = 0) APPLE_KEXT_OVERRIDE;
	virtual IOReturn reportRemovability(bool *isRemovable) APPLE_KEXT_OVERRIDE;
	virtual IOReturn reportWriteProtection(bool *isWriteProtected) APPLE_KEXT_OVERRIDE;
	virtual IOReturn doAsyncReadWrite(IOMemoryDescriptor *buffer, UInt64 block,
	                                  UInt64 nblks, IOStorageAttributes *attributes,
	                                  IOStorageCompletion *completion) APPLE_KEXT_OVERRIDE;
	virtual IOReturn doSynchronizeCache(void) APPLE_KEXT_OVERRIDE;
	virtual IOReturn doSynchronize(UInt64 block, UInt64 nblks,
	                               IOStorageSynchronizeOptions options = 0) APPLE_KEXT_OVERRIDE;
};

OSDefineMetaClassAndStructors(com_crossxnu_BlockStorage, IOBlockStorageDevice);

bool com_crossxnu_BlockStorage::init(OSDictionary *properties)
{
	if (!super::init(properties))
		return false;

	_backend    = kBackendNone;
	_image      = NULL;
	_imageSize  = 0;
	_blockCount = 0;
	_blockSize  = kBlockStorageBlockSize;
	_workLoop   = NULL;
	_timer      = NULL;
	_waits      = 0;
	_loggedRead = false;
	_loggedWrite = false;

	memset(&_ahci, 0, sizeof(_ahci));

	return true;
}

static UInt32
ahciReg(struct crossxnu_ahci *a, UInt32 offset)
{
	return a->regs[offset / 4];
}

static void
ahciSetReg(struct crossxnu_ahci *a, UInt32 offset, UInt32 value)
{
	a->regs[offset / 4] = value;
}

/* Issue one ATA command through port slot 0 and wait for it to finish. */
IOReturn
com_crossxnu_BlockStorage::ahciCommand(UInt8 command, UInt64 lba, UInt16 count,
                                      IOPhysicalAddress bufferPhys, UInt32 bytes,
                                      bool write)
{
	struct crossxnu_ahci *a = &_ahci;
	UInt32 base = AHCI_PORTS + (UInt32)a->port * AHCI_PORT_STRIDE;
	UInt8 *fis = (UInt8 *)a->ct;
	UInt32 *prdt = (UInt32 *)((UInt8 *)a->ct + 128);
	UInt32 *hdr = a->cl;
	bool hasData = (bufferPhys != 0 && bytes != 0);
	int spin;

	/* Wait for the port to go idle: PxCI has no outstanding commands.  CR is
	 * not part of this test -- it stays set for as long as ST is up. */
	for (spin = 0; spin < 100000; spin++) {
		if (ahciReg(a, base + AP_CI) == 0) {
			break;
		}
		IODelay(10);
	}
	if (spin == 100000) {
		IOLog("CrossXnuBlockStorage: port %d never went idle\n", a->port);
		return kIOReturnTimeout;
	}

	/* Command table: one H2D FIS plus one PRDT entry. */
	memset(a->ct, 0, 256);
	fis[0]  = FIS_TYPE_H2D;
	fis[1]  = 0x80;                      /* C: update the command register */
	fis[2]  = command;
	fis[3]  = 0;                         /* features */
	fis[4]  = (UInt8)(lba);              /* LBA low */
	fis[5]  = (UInt8)(lba >> 8);         /* LBA mid */
	fis[6]  = (UInt8)(lba >> 16);        /* LBA high */
	fis[7]  = 0x40;                      /* device: LBA mode */
	fis[8]  = (UInt8)(lba >> 24);
	fis[9]  = (UInt8)(lba >> 32);
	fis[10] = (UInt8)(lba >> 40);
	fis[11] = 0;
	fis[12] = (UInt8)(count);
	fis[13] = (UInt8)(count >> 8);
	fis[14] = 0;
	fis[15] = 0;

	if (hasData) {
		prdt[0] = (UInt32)bufferPhys;
		prdt[1] = (UInt32)(bufferPhys >> 32);
		prdt[2] = 0;
		prdt[3] = (bytes - 1) & 0x3FFFFF;    /* DBC; I = 0 */
	}

	memset(a->cl, 0, 32);
	hdr[0] = (5U << 0) |                      /* CFL: 20-byte FIS */
	    (write ? (1U << 6) : 0) |             /* W */
	    (hasData ? (1U << 16) : 0);           /* PRDTL */
	hdr[1] = 0;
	hdr[2] = (UInt32)a->ctPhys;
	hdr[3] = (UInt32)(a->ctPhys >> 32);

	ahciSetReg(a, base + AP_SERR, 0xFFFFFFFF);
	ahciSetReg(a, base + AP_IS, 0xFFFFFFFF);
	ahciSetReg(a, base + AP_CI, 1);

	for (spin = 0; spin < 3000000; spin++) {
		if ((ahciReg(a, base + AP_CI) & 1) == 0) {
			break;
		}
		IODelay(10);
	}
	if (spin == 3000000) {
		IOLog("CrossXnuBlockStorage: port %d command %02x timed out\n",
		    a->port, command);
		/* Leave the port usable: drop the command and restart the engine. */
		ahciSetReg(a, base + AP_CI, 0);
		ahciSetReg(a, base + AP_CMD,
		    ahciReg(a, base + AP_CMD) & ~AP_CMD_ST);
		IODelay(1000);
		ahciSetReg(a, base + AP_CMD,
		    ahciReg(a, base + AP_CMD) | AP_CMD_ST);
		IODelay(1000);
		return kIOReturnTimeout;
	}

	UInt32 is = ahciReg(a, base + AP_IS);

	if (is & AP_IS_TFES) {
		IOLog("CrossXnuBlockStorage: port %d command %02x failed, "
		    "tfd=%08x is=%08x\n", a->port, command,
		    ahciReg(a, base + AP_TFD), is);
		return kIOReturnIOError;
	}

	return kIOReturnSuccess;
}

/* Bring up one port and read the disk's capacity. */
bool
com_crossxnu_BlockStorage::attachAHCI(int port)
{
	struct crossxnu_ahci *a = &_ahci;
	UInt32 base = AHCI_PORTS + (UInt32)port * AHCI_PORT_STRIDE;
	UInt32 cmd;
	IOReturn status;
	UInt16 *id = (UInt16 *)a->bounce;
	UInt64 maxLba;
	int spin;

	a->port = port;

	/* Stop the engine, then restart it with the list pointers we want. */
	cmd = ahciReg(a, base + AP_CMD);
	if (cmd & AP_CMD_ST) {
		ahciSetReg(a, base + AP_CMD, cmd & ~AP_CMD_ST);
		for (spin = 0; spin < 100000; spin++) {
			if ((ahciReg(a, base + AP_CMD) & AP_CMD_CR) == 0) {
				break;
			}
			IODelay(10);
		}
	}
	if ((ahciReg(a, base + AP_CMD) & AP_CMD_FRE) == 0) {
		ahciSetReg(a, base + AP_CMD,
		    ahciReg(a, base + AP_CMD) | AP_CMD_FRE);
		for (spin = 0; spin < 100000; spin++) {
			if (ahciReg(a, base + AP_CMD) & AP_CMD_FR) {
				break;
			}
			IODelay(10);
		}
	}

	/* The list pointers must be programmed while the engine is stopped (CR=0),
	 * that is before ST goes up. */
	ahciSetReg(a, base + AP_CLB, (UInt32)a->clPhys);
	ahciSetReg(a, base + AP_CLBU, (UInt32)(a->clPhys >> 32));
	ahciSetReg(a, base + AP_FB, (UInt32)a->ctPhys);
	ahciSetReg(a, base + AP_FBU, (UInt32)(a->ctPhys >> 32));
	ahciSetReg(a, base + AP_SERR, 0xFFFFFFFF);
	ahciSetReg(a, base + AP_IS, 0xFFFFFFFF);
	ahciSetReg(a, base + AP_CI, 0);

	ahciSetReg(a, base + AP_CMD, ahciReg(a, base + AP_CMD) | AP_CMD_ST);
	for (spin = 0; spin < 100000; spin++) {
		if (ahciReg(a, base + AP_CMD) & AP_CMD_CR) {
			break;
		}
		IODelay(10);
	}

	/* IDENTIFY DEVICE: 512 bytes into the bounce buffer. */
	memset(a->bounce, 0, 512);
	status = ahciCommand(ATA_CMD_IDENTIFY, 0, 0, a->bouncePhys, 512, false);
	if (status != kIOReturnSuccess) {
		IOLog("CrossXnuBlockStorage: port %d IDENTIFY failed (%d)\n",
		    port, status);
		return false;
	}

	maxLba = (UInt64)id[100] | ((UInt64)id[101] << 16) |
	    ((UInt64)id[102] << 32) | ((UInt64)id[103] << 48);
	if (maxLba == 0) {
		IOLog("CrossXnuBlockStorage: port %d reports no LBAs\n", port);
		return false;
	}

	a->sectors = maxLba + 1;

	/* The model string is byte-swapped in the identify data; it tells us which
	 * of the attached disks we are looking at (the ESP is on this controller
	 * too). */
	char model[41];
	for (int i = 0; i < 20; i++) {
		UInt16 w = id[27 + i];

		model[i * 2]     = (char)(w >> 8);
		model[i * 2 + 1] = (char)(w & 0xFF);
	}
	model[40] = '\0';
	for (int i = 39; i >= 0 && (model[i] == ' ' || model[i] == '\0'); i--) {
		model[i] = '\0';
	}

	IOLog("CrossXnuBlockStorage: port %d: %llu sectors (%llu MiB) \"%s\"\n",
	    port, (unsigned long long)a->sectors,
	    (unsigned long long)((a->sectors * kAHCIBlockSize) >> 20), model);

	return true;
}

bool
com_crossxnu_BlockStorage::initAHCI(void)
{
	struct crossxnu_ahci *a = &_ahci;
	UInt8 ctrlSlot = 0, ctrlFunc = 0;
	UInt32 barPhys = 0;
	UInt32 abarOffset;
	vm_size_t mapSize;
	bool found = false;
	int best = -1;
	UInt64 bestSectors = 0;

	/* Find the controller: class code 0x010601 (SATA, AHCI 1.0). */
	for (UInt8 slot = 0; slot < 32 && !found; slot++) {
		for (UInt8 func = 0; func < 8; func++) {
			UInt32 id = pciConfigRead(0, slot, func, 0x00);
			UInt32 classCode;

			if (id == 0xFFFFFFFFU) {
				continue;
			}
			classCode = pciConfigRead(0, slot, func, 0x08);
			if ((classCode >> 8) != 0x010601U) {
				continue;
			}
			ctrlSlot = slot;
			ctrlFunc = func;
			found = true;
			IOLog("CrossXnuBlockStorage: AHCI at 00:%02x.%x "
			    "(vendor %04x device %04x)\n", slot, func,
			    (unsigned)(id & 0xFFFF), (unsigned)(id >> 16));
			break;
		}
	}
	if (!found) {
		IOLog("CrossXnuBlockStorage: no AHCI controller on bus 0\n");
		return false;
	}

	/* Enable memory space and bus mastering. */
	UInt32 pcicmd = pciConfigRead(0, ctrlSlot, ctrlFunc, 0x04);
	pciConfigWrite(0, ctrlSlot, ctrlFunc, 0x04,
	    pcicmd | 0x0002U | 0x0004U);

	/* BAR5 is the ABAR, a 32-bit memory BAR on this controller. */
	UInt32 bar = pciConfigRead(0, ctrlSlot, ctrlFunc, 0x24);

	if ((bar & 0x1) != 0) {
		IOLog("CrossXnuBlockStorage: ABAR is I/O space, unsupported\n");
		return false;
	}
	barPhys = (bar & 0x4) ? ((UInt32)pciConfigRead(0, ctrlSlot, ctrlFunc, 0x28))
	    : (bar & 0xFFFFFFF0U);
	if (barPhys == 0) {
		IOLog("CrossXnuBlockStorage: ABAR is not assigned\n");
		return false;
	}

	/* Map it; device memory must not be cached. */
	abarOffset = barPhys & (PAGE_SIZE - 1);
	mapSize = 0x2000 + abarOffset;
	a->abarPhys = barPhys & ~((UInt32)PAGE_SIZE - 1);
	a->abarDesc = IOMemoryDescriptor::withPhysicalAddress(
	    (IOPhysicalAddress)a->abarPhys, mapSize, kIODirectionNone);
	if (a->abarDesc == NULL) {
		IOLog("CrossXnuBlockStorage: cannot describe the ABAR\n");
		return false;
	}
	a->abarMap = a->abarDesc->map(kIOMapAnywhere | kIOMapInhibitCache);
	if (a->abarMap == NULL) {
		IOLog("CrossXnuBlockStorage: cannot map the ABAR\n");
		OSSafeReleaseNULL(a->abarDesc);
		return false;
	}
	a->regs = (volatile UInt32 *)((UInt8 *)a->abarMap->getVirtualAddress() +
	    abarOffset);

	a->cap = ahciReg(a, AHCI_CAP);
	a->pi  = ahciReg(a, AHCI_PI);
	IOLog("CrossXnuBlockStorage: ABAR %08x cap %08x pi %08x\n",
	    a->abarPhys, a->cap, a->pi);

	/* Enable AHCI (GHC.AE). */
	ahciSetReg(a, AHCI_GHC, ahciReg(a, AHCI_GHC) | (1U << 31));

	/* DMA structures and a bounce buffer, shared by all ports: only one
	 * command is ever in flight. */
	a->cl = (UInt32 *)IOMallocContiguous(1024, 1024, &a->clPhys);
	a->ct = (UInt8 *)IOMallocContiguous(4096, 128, &a->ctPhys);
	a->bounce = (UInt8 *)IOMallocContiguous(kAHCIMaxTransfer, kAHCIBounceAlign,
	    &a->bouncePhys);
	if (a->cl == NULL || a->ct == NULL || a->bounce == NULL) {
		IOLog("CrossXnuBlockStorage: no DMA memory\n");
		return false;
	}
	memset(a->cl, 0, 1024);
	memset(a->ct, 0, 4096);

	/* Choose the disk that actually holds an APFS container: read block 0 and
	 * look for the NXSB magic at offset 0x20.  The ESP is on this controller
	 * too (and is much larger than the test images), so its size says nothing.
	 * Fall back to the largest ATA disk if none of them look like APFS. */
	int apfsPort = -1;
	UInt64 apfsSectors = 0;
	int largestPort = -1;
	UInt64 largestSectors = 0;

	for (int port = 0; port < 32; port++) {
		UInt32 base, ssts, sig;
		bool looksApfs = false;

		if ((a->pi & (1U << port)) == 0) {
			continue;
		}
		base = AHCI_PORTS + (UInt32)port * AHCI_PORT_STRIDE;
		ssts = ahciReg(a, base + AP_SSTS);
		sig  = ahciReg(a, base + AP_SIG);
		if ((ssts & 0xF) != AHCI_DEV_PRESENT) {
			continue;
		}
		IOLog("CrossXnuBlockStorage: port %d attached, sig %08x\n",
		    port, sig);
		if (sig != AHCI_SIG_ATA) {
			continue;
		}
		if (!attachAHCI(port)) {
			continue;
		}

		if (ahciCommand(ATA_CMD_READ_DMA_EXT, 0, 1, a->bouncePhys, 512,
		    false) == kIOReturnSuccess) {
			looksApfs = (memcmp(a->bounce + 0x20, "NXSB", 4) == 0);
		}
		IOLog("CrossXnuBlockStorage: port %d: block 0 %s\n", port,
		    looksApfs ? "is APFS (NXSB)" : "is not APFS");

		if (looksApfs && apfsPort < 0) {
			apfsPort = port;
			apfsSectors = a->sectors;
		}
		/* Port 0 is where QEMU puts the ESP, which is much larger than the
		 * test images; never fall back to it, or a format command aimed at
		 * "the disk" would erase the boot partition. */
		if (port != 0 && a->sectors > largestSectors) {
			largestPort = port;
			largestSectors = a->sectors;
		}
	}

	if (apfsPort >= 0) {
		best = apfsPort;
		bestSectors = apfsSectors;
	} else if (largestPort >= 0) {
		best = largestPort;
		bestSectors = largestSectors;
	}

	if (best < 0) {
		IOLog("CrossXnuBlockStorage: no ATA disk on the controller\n");
		return false;
	}
	if (!attachAHCI(best)) {
		return false;
	}

	a->port    = best;
	a->sectors = bestSectors;
	_blockSize  = kAHCIBlockSize;
	_blockCount = bestSectors;

	IOLog("CrossXnuBlockStorage: using port %d, %llu sectors%s\n",
	    best, (unsigned long long)bestSectors,
	    (apfsPort >= 0) ? " (APFS)" : " (largest, no NXSB found)");

	return true;
}

void
com_crossxnu_BlockStorage::freeAHCI(void)
{
	struct crossxnu_ahci *a = &_ahci;

	OSSafeReleaseNULL(a->abarMap);
	OSSafeReleaseNULL(a->abarDesc);
	if (a->cl != NULL) {
		IOFreeContiguous(a->cl, 1024);
		a->cl = NULL;
	}
	if (a->ct != NULL) {
		IOFreeContiguous(a->ct, 4096);
		a->ct = NULL;
	}
	if (a->bounce != NULL) {
		IOFreeContiguous(a->bounce, kAHCIMaxTransfer);
		a->bounce = NULL;
	}
}

IOReturn
com_crossxnu_BlockStorage::ahciReadWrite(IOMemoryDescriptor *buffer,
                                        UInt64 block, UInt64 nblks, bool write,
                                        IOByteCount *done)
{
	struct crossxnu_ahci *a = &_ahci;
	UInt64 bytes = nblks * kAHCIBlockSize;
	UInt64 offset = 0;
	IOByteCount total = 0;

	*done = 0;

	while (offset < bytes) {
		UInt32 chunk = (bytes - offset > kAHCIMaxTransfer)
		    ? (UInt32)kAHCIMaxTransfer : (UInt32)(bytes - offset);
		UInt64 lba = block + (offset / kAHCIBlockSize);
		UInt16 count = (UInt16)(chunk / kAHCIBlockSize);
		IOByteCount moved;
		IOReturn status;

		if (write) {
			moved = buffer->readBytes((IOByteCount)offset, a->bounce,
			    chunk);
			if (moved != chunk) {
				IOLog("CrossXnuBlockStorage: write %llu+%u: source "
				    "read %u bytes\n", (unsigned long long)lba, chunk,
				    (unsigned)moved);
				return kIOReturnUnderrun;
			}
		}

		status = ahciCommand(write ? ATA_CMD_WRITE_DMA_EXT
		    : ATA_CMD_READ_DMA_EXT, lba, count, a->bouncePhys, chunk,
		    write);
		if (status != kIOReturnSuccess) {
			IOLog("CrossXnuBlockStorage: %s lba %llu count %u failed "
			    "(%08x)\n", write ? "write" : "read",
			    (unsigned long long)lba, count, status);
			return status;
		}

		if (!write) {
			moved = buffer->writeBytes((IOByteCount)offset, a->bounce,
			    chunk);
			if (moved != chunk) {
				return kIOReturnUnderrun;
			}
		}

		offset += chunk;
		total += chunk;
	}

	*done = total;
	return kIOReturnSuccess;
}

/* ------------------------------------------------------------------ */
/* RAM backend                                                         */
/* ------------------------------------------------------------------ */

bool
com_crossxnu_BlockStorage::initRAM(void)
{
	kernel_segment_command_t *seg;

	seg = getsegbyname(kBlockStorageImageSegment);
	if (seg == NULL || seg->filesize < kBlockStorageImageMinimum) {
		IOLog("CrossXnuBlockStorage: no %s segment and no AHCI disk\n",
		    kBlockStorageImageSegment);
		return false;
	}

	_image      = (char *)(uintptr_t)seg->vmaddr;
	_imageSize  = seg->filesize;
	_blockSize  = kBlockStorageBlockSize;
	_blockCount = _imageSize / _blockSize;

	if (_blockCount == 0) {
		return false;
	}

	IOLog("CrossXnuBlockStorage: %s: %llu bytes at %p, %llu blocks of %u\n",
	    kBlockStorageImageSegment, (unsigned long long)_imageSize, _image,
	    (unsigned long long)_blockCount, _blockSize);

	return true;
}

/* ------------------------------------------------------------------ */
/* Publishing                                                          */
/* ------------------------------------------------------------------ */

void com_crossxnu_BlockStorage::publishTimer(OSObject *owner,
                                            IOTimerEventSource *sender)
{
	com_crossxnu_BlockStorage *self =
	    OSDynamicCast(com_crossxnu_BlockStorage, owner);
	IOService *resources;

	(void)sender;

	if (self == NULL)
		return;

	resources = IOService::getResourceService();
	if (resources == NULL || resources->getProperty("IOBSD") == NULL) {
		if (++self->_waits < 80)
			self->_timer->setTimeoutMS(250);
		else
			IOLog("CrossXnuBlockStorage: IOBSD never appeared\n");
		return;
	}

	if (!self->publish(IOService::getResourceService())) {
		IOLog("CrossXnuBlockStorage: publishing the device failed\n");
		return;
	}

	crossxnu_mount_apfs_volume();
}

void com_crossxnu_BlockStorage::schedulePublish(void)
{
	_workLoop = IOWorkLoop::workLoop();
	if (_workLoop == NULL) {
		IOLog("CrossXnuBlockStorage: no work loop, publishing now\n");
		publish(IOService::getResourceService());
		crossxnu_mount_apfs_volume();
		return;
	}

	_timer = IOTimerEventSource::timerEventSource(this,
	    &com_crossxnu_BlockStorage::publishTimer);
	if (_timer == NULL || _workLoop->addEventSource(_timer) != kIOReturnSuccess) {
		IOLog("CrossXnuBlockStorage: no timer, publishing now\n");
		publish(IOService::getResourceService());
		crossxnu_mount_apfs_volume();
		return;
	}

	_timer->setTimeoutMS(100);
}

bool com_crossxnu_BlockStorage::publish(IOService *provider)
{
	/* IOBlockStorageDriver matches on device-type, which IOBlockStorageDevice's
	 * own init() sets to "Generic"; make the media look like a whole disk. */
	setProperty(kIOBlockStorageDeviceTypeKey, kIOBlockStorageDeviceTypeGeneric);

	if (!attach(provider) || !start(provider)) {
		return false;
	}
	registerService();

	return true;
}

bool com_crossxnu_BlockStorage::start(IOService *provider)
{
	if (!super::start(provider))
		return false;

	if (initAHCI()) {
		_backend = kBackendAHCI;
	} else if (initRAM()) {
		_backend = kBackendRAM;
	} else {
		return false;
	}

	return true;
}

void com_crossxnu_BlockStorage::free(void)
{
	if (_workLoop != NULL && _timer != NULL) {
		_workLoop->removeEventSource(_timer);
	}
	OSSafeReleaseNULL(_timer);
	OSSafeReleaseNULL(_workLoop);

	freeAHCI();

	super::free();
}

IOReturn com_crossxnu_BlockStorage::doEjectMedia(void)
{
	return kIOReturnUnsupported;
}

IOReturn com_crossxnu_BlockStorage::doFormatMedia(UInt64 byteCapacity)
{
	(void)byteCapacity;
	return kIOReturnUnsupported;
}

UInt32 com_crossxnu_BlockStorage::doGetFormatCapacities(UInt64 *capacities,
                                                      UInt32 capacitiesMaxCount) const
{
	if (capacities != NULL && capacitiesMaxCount >= 1)
		capacities[0] = _blockCount * _blockSize;

	return 1;
}

char * com_crossxnu_BlockStorage::getVendorString(void)
{
	return (char *)"crossxnu";
}

char * com_crossxnu_BlockStorage::getProductString(void)
{
	return (char *)(_backend == kBackendAHCI ? "AHCIDisk" : "RAMStorage");
}

char * com_crossxnu_BlockStorage::getRevisionString(void)
{
	return (char *)"1.0";
}

char * com_crossxnu_BlockStorage::getAdditionalDeviceInfoString(void)
{
	if (_backend == kBackendAHCI) {
		return (char *)"ahci";
	}
	return (char *)kBlockStorageImageSegment;
}

IOReturn com_crossxnu_BlockStorage::reportBlockSize(UInt64 *blockSize)
{
	if (blockSize == NULL)
		return kIOReturnBadArgument;

	*blockSize = _blockSize;
	return kIOReturnSuccess;
}

IOReturn com_crossxnu_BlockStorage::reportEjectability(bool *isEjectable)
{
	if (isEjectable == NULL)
		return kIOReturnBadArgument;

	*isEjectable = false;
	return kIOReturnSuccess;
}

IOReturn com_crossxnu_BlockStorage::reportMaxValidBlock(UInt64 *maxBlock)
{
	if (maxBlock == NULL)
		return kIOReturnBadArgument;

	*maxBlock = _blockCount - 1;
	return kIOReturnSuccess;
}

IOReturn com_crossxnu_BlockStorage::reportMediaState(bool *mediaPresent,
                                                    bool *changedState)
{
	if (mediaPresent == NULL)
		return kIOReturnBadArgument;

	*mediaPresent = (_backend != kBackendNone && _blockCount != 0);
	if (changedState != NULL)
		*changedState = false;

	return kIOReturnSuccess;
}

IOReturn com_crossxnu_BlockStorage::reportRemovability(bool *isRemovable)
{
	if (isRemovable == NULL)
		return kIOReturnBadArgument;

	*isRemovable = false;
	return kIOReturnSuccess;
}

IOReturn com_crossxnu_BlockStorage::reportWriteProtection(bool *isWriteProtected)
{
	if (isWriteProtected == NULL)
		return kIOReturnBadArgument;

	*isWriteProtected = false;
	return kIOReturnSuccess;
}

IOReturn com_crossxnu_BlockStorage::doAsyncReadWrite(IOMemoryDescriptor *buffer,
                                                    UInt64 block, UInt64 nblks,
                                                    IOStorageAttributes *attributes,
                                                    IOStorageCompletion *completion)
{
	IOReturn status;
	IOByteCount done = 0;
	UInt64 offset;
	UInt64 length;

	(void)attributes;

	if (buffer == NULL || completion == NULL)
		return kIOReturnBadArgument;

	if (block >= _blockCount || nblks == 0 ||
	    nblks > (_blockCount - block)) {
		IOStorage::complete(completion, kIOReturnBadArgument, 0);
		return kIOReturnBadArgument;
	}

	if (_backend == kBackendAHCI) {
		bool isWrite = (buffer->getDirection() != kIODirectionIn);

		/* One line per direction on the first transfer: tells apart "APFS
		 * never issued a write" from "the write failed in the driver". */
		if (!isWrite && !_loggedRead) {
			_loggedRead = true;
			IOLog("CrossXnuBlockStorage: first read lba %llu count %llu\n",
			    (unsigned long long)block, (unsigned long long)nblks);
		} else if (isWrite && !_loggedWrite) {
			_loggedWrite = true;
			IOLog("CrossXnuBlockStorage: first write lba %llu count %llu\n",
			    (unsigned long long)block, (unsigned long long)nblks);
		}
		status = ahciReadWrite(buffer, block, nblks, isWrite, &done);
		IOStorage::complete(completion, status, done);
		return status;
	}

	offset = block * _blockSize;
	length = nblks * _blockSize;

	if (buffer->getDirection() == kIODirectionIn) {
		/* device -> memory (a read from the caller's point of view) */
		done = buffer->writeBytes(0, _image + offset, (IOByteCount)length);
	} else {
		/* memory -> device */
		done = buffer->readBytes(0, _image + offset, (IOByteCount)length);
	}
	status = (done == length) ? kIOReturnSuccess : kIOReturnUnderrun;

	IOStorage::complete(completion, status, done);

	return status;
}

IOReturn com_crossxnu_BlockStorage::doSynchronizeCache(void)
{
	if (_backend == kBackendAHCI) {
		return ahciCommand(ATA_CMD_FLUSH_CACHE_EXT, 0, 0, 0, 0, false);
	}
	return kIOReturnSuccess;
}

IOReturn com_crossxnu_BlockStorage::doSynchronize(UInt64 block, UInt64 nblks,
                                                IOStorageSynchronizeOptions options)
{
	(void)block;
	(void)nblks;
	(void)options;
	return doSynchronizeCache();
}

/*
 * kmod entry points.  OSKext calls start() while loading the kext, and that is
 * where the device is built: doing it here instead of through a matching
 * personality keeps the bring-up deterministic (bsd_init.c asks for this kext
 * by identifier right before it asks for APFS).
 */
extern "C" kern_return_t
crossxnu_blockstorage_start(kmod_info_t *ki, void *data)
{
	com_crossxnu_BlockStorage *dev;

	(void)ki;
	(void)data;

	dev = new com_crossxnu_BlockStorage;
	if (dev == NULL)
		return KERN_NO_SPACE;

	if (!dev->init(NULL)) {
		dev->release();
		return KERN_FAILURE;
	}

	/*
	 * Do not attach yet: the media BSD clients match on the IOBSD resource,
	 * which IOKitBSDInit() publishes near the end of bsd_init().  A media
	 * registered before that never gets a /dev node (and without a node there
	 * is nothing to mount), so publish from a timer once IOBSD is there.
	 */
	dev->schedulePublish();

	return KERN_SUCCESS;
}

extern "C" kern_return_t
crossxnu_blockstorage_stop(kmod_info_t *ki, void *data)
{
	(void)ki;
	(void)data;
	return KERN_SUCCESS;
}

KMOD_EXPLICIT_DECL(com.crossxnu.driver.CrossXnuBlockStorage, "1.0.0",
    crossxnu_blockstorage_start, crossxnu_blockstorage_stop);
