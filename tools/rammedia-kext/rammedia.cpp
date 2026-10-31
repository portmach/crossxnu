/*
 * com.crossxnu.driver.CrossXnuRAMStorage
 *
 * A block storage device backed by a region of the kernel's own memory, so
 * APFS gets an IOMedia to mount without a PCI bus, ACPI or any real hardware
 * driver: IOBlockStorageDevice -> IOBlockStorageDriver -> IOMedia -> AppleAPFS.
 *
 * The backing store is the __APFSIMG segment that scripts/kc-add-segment.py
 * appends to the kernel collection.  getsegbyname() is the same lookup that
 * bsd_init.c uses for the embedded __ROOTIMG root image, so the image lives in
 * the kernel map and is directly addressable (no physical-memory dance).
 *
 * Writes go to that memory, so an APFS mount inside the collection stays
 * consistent for the lifetime of the boot; nothing is persisted.
 */

#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/IOTimerEventSource.h>
#include <IOKit/storage/IOBlockStorageDevice.h>
#include <libkern/kernel_mach_header.h>
#include <mach/kmod.h>

#define kRAMStorageClassName "CrossXnuRAMStorage"
#define kRAMStorageBlockSize 4096
#define kRAMStorageImageSegment "__APFSIMG"
#define kRAMStorageImageMinimum 4096

/* Kernel-side helper (bsd/kern/bsd_init.c) that mounts the volume once its
 * /dev node exists: mounting needs kernel_mount() and VFS internals, which a
 * kext cannot call. */
extern "C" void crossxnu_mount_apfs_volume(void);

/* Every kext needs a kmod_info with start/stop entry points. */
extern "C" kern_return_t crossxnu_ramstorage_start(kmod_info_t *ki, void *data);
extern "C" kern_return_t crossxnu_ramstorage_stop(kmod_info_t *ki, void *data);

class com_crossxnu_RAMStorage : public IOBlockStorageDevice
{
	OSDeclareDefaultStructors(com_crossxnu_RAMStorage);

	typedef IOBlockStorageDevice super;

private:
	char *          _image;                  /* kernel VA of the image */
	UInt64          _imageSize;
	UInt64          _blockCount;
	UInt32          _blockSize;
	IOWorkLoop *    _workLoop;
	IOTimerEventSource * _timer;
	int             _waits;

	static void publishTimer(OSObject *owner, IOTimerEventSource *sender);

public:
	virtual bool     init(OSDictionary *properties) APPLE_KEXT_OVERRIDE;
	virtual bool     start(IOService *provider) APPLE_KEXT_OVERRIDE;
	virtual void     free(void) APPLE_KEXT_OVERRIDE;

	/* Publishing is deferred until IOKitBSDInit() has published the IOBSD
	 * resource: the media BSD clients match on it, and a media that appears
	 * earlier never gets a /dev node. */
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
};

OSDefineMetaClassAndStructors(com_crossxnu_RAMStorage, IOBlockStorageDevice);

bool com_crossxnu_RAMStorage::init(OSDictionary *properties)
{
	if (!super::init(properties))
		return false;

	_image      = NULL;
	_imageSize  = 0;
	_blockCount = 0;
	_blockSize  = kRAMStorageBlockSize;
	_workLoop   = NULL;
	_timer      = NULL;
	_waits      = 0;

	return true;
}

/* Called by the timer: wait for IOBSD, then publish and ask the kernel to
 * mount the volume. */
void com_crossxnu_RAMStorage::publishTimer(OSObject *owner, IOTimerEventSource *sender)
{
	com_crossxnu_RAMStorage *self = OSDynamicCast(com_crossxnu_RAMStorage, owner);
	IOService *resources;

	(void)sender;

	if (self == NULL)
		return;

	resources = IOService::getResourceService();
	if (resources == NULL || resources->getProperty("IOBSD") == NULL) {
		/* IOKitBSDInit() has not run yet; try again shortly. */
		if (++self->_waits < 80)
			self->_timer->setTimeoutMS(250);
		else
			IOLog("CrossXnuRAMStorage: IOBSD never appeared\n");
		return;
	}

	if (!self->publish(IOService::getResourceService())) {
		IOLog("CrossXnuRAMStorage: publishing the device failed\n");
		return;
	}

	/* The media BSD clients run from here, so their /dev nodes exist by the
	 * time the kernel helper looks for them (it polls as well). */
	crossxnu_mount_apfs_volume();
}

void com_crossxnu_RAMStorage::schedulePublish(void)
{
	_workLoop = IOWorkLoop::workLoop();
	if (_workLoop == NULL) {
		IOLog("CrossXnuRAMStorage: no work loop, publishing now\n");
		publish(IOService::getResourceService());
		crossxnu_mount_apfs_volume();
		return;
	}

	_timer = IOTimerEventSource::timerEventSource(this,
	    &com_crossxnu_RAMStorage::publishTimer);
	if (_timer == NULL || _workLoop->addEventSource(_timer) != kIOReturnSuccess) {
		IOLog("CrossXnuRAMStorage: no timer, publishing now\n");
		publish(IOService::getResourceService());
		crossxnu_mount_apfs_volume();
		return;
	}

	_timer->setTimeoutMS(100);
}

bool com_crossxnu_RAMStorage::publish(IOService *provider)
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

bool com_crossxnu_RAMStorage::start(IOService *provider)
{
	kernel_segment_command_t *seg;

	if (!super::start(provider))
		return false;

	seg = getsegbyname(kRAMStorageImageSegment);
	if (seg == NULL || seg->filesize < kRAMStorageImageMinimum) {
		IOLog("CrossXnuRAMStorage: no %s segment (no image to mount)\n",
		      kRAMStorageImageSegment);
		return false;
	}

	_image      = (char *)(uintptr_t)seg->vmaddr;
	_imageSize  = seg->filesize;
	_blockSize  = kRAMStorageBlockSize;
	_blockCount = _imageSize / _blockSize;

	if (_blockCount == 0) {
		IOLog("CrossXnuRAMStorage: %s is smaller than one block\n",
		      kRAMStorageImageSegment);
		return false;
	}

	IOLog("CrossXnuRAMStorage: %llu bytes at %p, %llu blocks of %u\n",
	      (unsigned long long)_imageSize, _image,
	      (unsigned long long)_blockCount, _blockSize);

	return true;
}

void com_crossxnu_RAMStorage::free(void)
{
	if (_workLoop != NULL && _timer != NULL) {
		_workLoop->removeEventSource(_timer);
	}
	OSSafeReleaseNULL(_timer);
	OSSafeReleaseNULL(_workLoop);

	super::free();
}

IOReturn com_crossxnu_RAMStorage::doEjectMedia(void)
{
	return kIOReturnUnsupported;
}

IOReturn com_crossxnu_RAMStorage::doFormatMedia(UInt64 byteCapacity)
{
	return kIOReturnUnsupported;
}

UInt32 com_crossxnu_RAMStorage::doGetFormatCapacities(UInt64 *capacities,
                                                     UInt32 capacitiesMaxCount) const
{
	(void)capacities;

	/* One capacity (the current size); report the count when no buffer given. */
	if (capacities != NULL && capacitiesMaxCount >= 1)
		capacities[0] = _imageSize;

	return 1;
}

char * com_crossxnu_RAMStorage::getVendorString(void)
{
	return (char *)"crossxnu";
}

char * com_crossxnu_RAMStorage::getProductString(void)
{
	return (char *)"RAMStorage";
}

char * com_crossxnu_RAMStorage::getRevisionString(void)
{
	return (char *)"1.0";
}

char * com_crossxnu_RAMStorage::getAdditionalDeviceInfoString(void)
{
	return (char *)kRAMStorageImageSegment;
}

IOReturn com_crossxnu_RAMStorage::reportBlockSize(UInt64 *blockSize)
{
	if (blockSize == NULL)
		return kIOReturnBadArgument;

	*blockSize = _blockSize;
	return kIOReturnSuccess;
}

IOReturn com_crossxnu_RAMStorage::reportEjectability(bool *isEjectable)
{
	if (isEjectable == NULL)
		return kIOReturnBadArgument;

	*isEjectable = false;
	return kIOReturnSuccess;
}

IOReturn com_crossxnu_RAMStorage::reportMaxValidBlock(UInt64 *maxBlock)
{
	if (maxBlock == NULL)
		return kIOReturnBadArgument;

	*maxBlock = _blockCount - 1;
	return kIOReturnSuccess;
}

IOReturn com_crossxnu_RAMStorage::reportMediaState(bool *mediaPresent,
                                                   bool *changedState)
{
	if (mediaPresent == NULL)
		return kIOReturnBadArgument;

	*mediaPresent = (_image != NULL && _blockCount != 0);
	if (changedState != NULL)
		*changedState = false;

	return kIOReturnSuccess;
}

IOReturn com_crossxnu_RAMStorage::reportRemovability(bool *isRemovable)
{
	if (isRemovable == NULL)
		return kIOReturnBadArgument;

	*isRemovable = false;
	return kIOReturnSuccess;
}

IOReturn com_crossxnu_RAMStorage::reportWriteProtection(bool *isWriteProtected)
{
	if (isWriteProtected == NULL)
		return kIOReturnBadArgument;

	/* Writable: APFS needs to write its superblock state; the change lives in
	 * the segment, so it is lost on the next boot. */
	*isWriteProtected = false;
	return kIOReturnSuccess;
}

IOReturn com_crossxnu_RAMStorage::doAsyncReadWrite(IOMemoryDescriptor *buffer,
                                                   UInt64 block, UInt64 nblks,
                                                   IOStorageAttributes *attributes,
                                                   IOStorageCompletion *completion)
{
	IOReturn status;
	UInt64   offset;
	UInt64   length;
	IOByteCount done = 0;

	(void)attributes;

	if (buffer == NULL || completion == NULL)
		return kIOReturnBadArgument;

	if (block >= _blockCount || nblks == 0 ||
	    nblks > (_blockCount - block)) {
		IOStorage::complete(completion, kIOReturnBadArgument, 0);
		return kIOReturnBadArgument;
	}

	offset = block * _blockSize;
	length = nblks * _blockSize;

	if (buffer->getDirection() == kIODirectionIn) {
		/* device -> memory (a read from the caller's point of view) */
		done = buffer->writeBytes(0, _image + offset, (IOByteCount)length);
		status = (done == length) ? kIOReturnSuccess : kIOReturnUnderrun;
	} else {
		/* memory -> device */
		done = buffer->readBytes(0, _image + offset, (IOByteCount)length);
		status = (done == length) ? kIOReturnSuccess : kIOReturnUnderrun;
	}

	IOStorage::complete(completion, status, done);

	return status;
}

/*
 * kmod entry points.  OSKext calls start() while loading the kext, and that is
 * where the device is published: doing it here instead of through a matching
 * personality keeps the bring-up deterministic (bsd_init.c asks for this kext
 * by identifier right before it asks for APFS).
 */
extern "C" kern_return_t
crossxnu_ramstorage_start(kmod_info_t *ki, void *data)
{
	com_crossxnu_RAMStorage *dev;

	(void)ki;
	(void)data;

	dev = new com_crossxnu_RAMStorage;
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
crossxnu_ramstorage_stop(kmod_info_t *ki, void *data)
{
	(void)ki;
	(void)data;
	return KERN_SUCCESS;
}

KMOD_EXPLICIT_DECL(com.crossxnu.driver.CrossXnuRAMStorage, "1.0.0",
    crossxnu_ramstorage_start, crossxnu_ramstorage_stop);
