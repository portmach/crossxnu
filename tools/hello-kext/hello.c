/*
 * crossxnu: minimal classic (KEXT 6 style) kext used to validate that the
 * kernel's kmod/OSKext loading path works at all in this port.
 *
 * It does nothing but print from start() and stop().
 *
 * Note on headers: we deliberately do NOT include <sys/systm.h> here.  In our
 * non-macOS build tree the exported BSD headers (EXPORT_HDRS/bsd) mix the
 * kernel and the userland flavours of <sys/types.h>, and pulling systm.h in
 * drags the kernel-internal Zalloc/kalloc headers in behind it, which then
 * collide on clock_t/int32_t with the already-exported userland typedefs.
 * <mach/kmod.h> + <kern/misc_protos.h> is the smallest combination that gives
 * us both the KMOD_EXPLICIT_DECL machinery and printf(), and it compiles
 * cleanly with the kernel's own flags (see build/dis/probe-kext-includes.py).
 */
#include <mach/kmod.h>
#include <kern/misc_protos.h>

kern_return_t crossxnu_hello_start(kmod_info_t *ki, void *data);
kern_return_t crossxnu_hello_stop(kmod_info_t *ki, void *data);

static int crossxnu_hello_loaded;

kern_return_t
crossxnu_hello_start(kmod_info_t *ki, void *data)
{
	printf("crossxnu: hello.kext start (kmod_info=%p data=%p)\n",
	    (void *)ki, data);
	crossxnu_hello_loaded = 1;
	return KERN_SUCCESS;
}

kern_return_t
crossxnu_hello_stop(kmod_info_t *ki, void *data)
{
	printf("crossxnu: hello.kext stop (kmod_info=%p data=%p)\n",
	    (void *)ki, data);
	crossxnu_hello_loaded = 0;
	return KERN_SUCCESS;
}

KMOD_EXPLICIT_DECL(com.crossxnu.hello, "1.0.0",
    crossxnu_hello_start, crossxnu_hello_stop);
