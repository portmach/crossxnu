/*
 * In-kernel HFS+ registration.
 *
 * The upstream HFS+ source normally ships as com.apple.filesystems.hfs.kext
 * and registers itself from hfs_iokit.cpp.  crossxnu builds the same core
 * into the kernel; this file performs the vfs_fsadd() step at boot instead
 * of matching an IOResources service.
 */
#include <sys/param.h>
#include <sys/systm.h>
#include <sys/mount.h>
#include <libkern/libkern.h>
#include "hfs_iokit.h"

extern struct vfsops hfs_vfsops;
extern struct vnodeopv_desc hfs_vnodeop_opv_desc;
extern struct vnodeopv_desc hfs_specop_opv_desc;
extern struct vnodeopv_desc hfs_fifoop_opv_desc;
extern void hfs_init_zones(void);

static vfstable_t hfs_vfs_handle;

void hfs_kernel_init(void);

void
hfs_kernel_init(void)
{
	struct vnodeopv_desc *op_descs[] = {
		&hfs_vnodeop_opv_desc,
		&hfs_specop_opv_desc,
		&hfs_fifoop_opv_desc,
	};

	if (hfs_vfs_handle != NULL) {
		return;
	}

	struct vfs_fsentry vfe = {
		.vfe_vfsops = &hfs_vfsops,
		.vfe_vopcnt = (int)(sizeof(op_descs) / sizeof(op_descs[0])),
		.vfe_opvdescs = op_descs,
		.vfe_fsname = "hfs",
		.vfe_flags = (VFS_TBLNOTYPENUM | VFS_TBLLOCALVOL |
		    VFS_TBLREADDIR_EXTENDED | VFS_TBL64BITREADY |
		    VFS_TBLVNOP_PAGEOUTV2 | VFS_TBLVNOP_PAGEINV2 |
		    VFS_TBLTHREADSAFE | VFS_TBLCANMOUNTROOT |
		    VFS_TBLVNOP_SECLUDE_RENAME | VFS_TBLNATIVEXATTR),
	};

	int ret = vfs_fsadd(&vfe, &hfs_vfs_handle);
	if (ret != 0) {
		printf("crossxnu: hfs vfs_fsadd failed: %d\n", ret);
		hfs_vfs_handle = NULL;
		return;
	}

	hfs_init_zones();
	printf("crossxnu: built-in HFS+ registered\n");
}


/* AppleKeyStore stubs: HFS+ protection is iOS-only. */
int hfs_is_ejectable(const char *cdev_name) { (void)cdev_name; return 0; }
void hfs_iterate_media_with_content(const char *uuid, int (*func)(const char *, const char *, void *), void *arg)
{ (void)uuid; (void)func; (void)arg; }
kern_return_t hfs_get_platform_serial_number(char *s, uint32_t len) { (void)s; (void)len; return KERN_FAILURE; }
int hfs_unwrap_key(aks_cred_t a, const aks_wrapped_key_t i, aks_raw_key_t o) { (void)a; (void)i; (void)o; return -1; }
int hfs_rewrap_key(aks_cred_t a, cp_key_class_t d, const aks_wrapped_key_t i, aks_wrapped_key_t o) { (void)a; (void)d; (void)i; (void)o; return -1; }
int hfs_new_key(aks_cred_t a, cp_key_class_t d, aks_raw_key_t k, aks_wrapped_key_t w) { (void)a; (void)d; (void)k; (void)w; return -1; }
int hfs_backup_key(aks_cred_t a, const aks_wrapped_key_t i, aks_wrapped_key_t o) { (void)a; (void)i; (void)o; return -1; }

/* No kext load tag for built-in HFS; bookkeeping is a no-op. */
bool panic_on_assert = false;
unsigned int OSKextGetCurrentLoadTag(void);
unsigned int OSKextGetCurrentLoadTag(void) { return 0; }
