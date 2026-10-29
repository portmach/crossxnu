#ifndef _CROSSXNU_MACH_MACHINE_H_
#define _CROSSXNU_MACH_MACHINE_H_

/* Host-side subset of <mach/machine.h> used by Mach-O tooling. */

#include <stdint.h>

typedef int cpu_type_t;
typedef int cpu_subtype_t;
typedef int cpu_threadtype_t;

#define CPU_ARCH_ABI64          0x01000000
#define CPU_ARCH_ABI64_32       0x02000000

#define CPU_TYPE_X86            7
#define CPU_TYPE_I386           7
#define CPU_TYPE_X86_64         ((cpu_type_t)(CPU_TYPE_X86 | CPU_ARCH_ABI64))
#define CPU_TYPE_ARM            12
#define CPU_TYPE_ARM64          ((cpu_type_t)(CPU_TYPE_ARM | CPU_ARCH_ABI64))

#define CPU_SUBTYPE_X86_64_ALL  3
#define CPU_SUBTYPE_X86_64_H    8
#define CPU_SUBTYPE_ARM64_ALL   0
#define CPU_SUBTYPE_ARM64E      2

#endif /* _CROSSXNU_MACH_MACHINE_H_ */
