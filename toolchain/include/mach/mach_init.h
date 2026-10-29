#ifndef _CROSSXNU_MACH_INIT_H_
#define _CROSSXNU_MACH_INIT_H_

/*
 * The only Mach runtime facility XNU's kextsymboltool needs is page rounding.
 * Keep this host shim free of the full Mach header stack, which is not
 * available (and not needed) outside macOS.
 */

#include <stdint.h>

#define mach_vm_round_page(x) \
	(((uint64_t)(x) + 0xfffULL) & ~0xfffULL)

#endif /* _CROSSXNU_MACH_INIT_H_ */
