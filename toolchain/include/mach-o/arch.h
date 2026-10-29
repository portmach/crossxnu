#ifndef _CROSSXNU_MACH_O_ARCH_H_
#define _CROSSXNU_MACH_O_ARCH_H_

#include <stdint.h>
#include <mach/machine.h>
#include <architecture/byte_order.h>

typedef struct NXArchInfo {
	const char *name;
	cpu_type_t cputype;
	cpu_subtype_t cpusubtype;
	enum NXByteOrder byteorder;
	const char *description;
} NXArchInfo;

#ifdef __cplusplus
extern "C" {
#endif

const NXArchInfo *NXGetLocalArchInfo(void);

#ifdef __cplusplus
}
#endif

#endif /* _CROSSXNU_MACH_O_ARCH_H_ */
