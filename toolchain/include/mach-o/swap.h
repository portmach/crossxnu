#ifndef _CROSSXNU_MACH_O_SWAP_H_
#define _CROSSXNU_MACH_O_SWAP_H_

/*
 * Host-side subset of <mach-o/swap.h>.
 *
 * XNU's SETUP tools only use the swap_* entry points to normalise Mach-O
 * structures to the host byte order.  x86_64 stores little-endian objects, so
 * the build host (also little-endian) can treat the operation as a no-op.
 * Big-endian hosts are not a supported build environment.
 */

#include <stdint.h>
#include <mach-o/loader.h>
#include <mach-o/nlist.h>
#include <architecture/byte_order.h>

#ifdef __cplusplus
extern "C" {
#endif

static inline void
swap_mach_header(struct mach_header *mh, enum NXByteOrder order)
{
	(void)mh;
	(void)order;
}

static inline void
swap_mach_header_64(struct mach_header_64 *mh, enum NXByteOrder order)
{
	(void)mh;
	(void)order;
}

static inline void
swap_segment_command(struct segment_command *sg, enum NXByteOrder order)
{
	(void)sg;
	(void)order;
}

static inline void
swap_segment_command_64(struct segment_command_64 *sg, enum NXByteOrder order)
{
	(void)sg;
	(void)order;
}

static inline void
swap_symtab_command(struct symtab_command *st, enum NXByteOrder order)
{
	(void)st;
	(void)order;
}

static inline void
swap_uuid_command(struct uuid_command *uc, enum NXByteOrder order)
{
	(void)uc;
	(void)order;
}

static inline void
swap_nlist(struct nlist *nl, uint32_t n, enum NXByteOrder order)
{
	(void)nl;
	(void)n;
	(void)order;
}

static inline void
swap_nlist_64(struct nlist_64 *nl, uint32_t n, enum NXByteOrder order)
{
	(void)nl;
	(void)n;
	(void)order;
}

#ifdef __cplusplus
}
#endif

#endif /* _CROSSXNU_MACH_O_SWAP_H_ */
