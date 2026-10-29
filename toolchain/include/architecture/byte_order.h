#ifndef _CROSSXNU_ARCHITECTURE_BYTE_ORDER_H_
#define _CROSSXNU_ARCHITECTURE_BYTE_ORDER_H_

#include <stdint.h>

enum NXByteOrder {
	NX_UnknownByteOrder = 0,
	NX_LittleEndian = 1,
	NX_BigEndian = 2,
};

#define OSSwapInt16(x) ((uint16_t)__builtin_bswap16((uint16_t)(x)))
#define OSSwapInt32(x) ((uint32_t)__builtin_bswap32((uint32_t)(x)))
#define OSSwapInt64(x) ((uint64_t)__builtin_bswap64((uint64_t)(x)))

#define NXSwapHostToLittleInt32(x) ((uint32_t)(x))
#define NXSwapHostToLittleInt64(x) ((uint64_t)(x))
#define NXSwapLittleToHostInt32(x) ((uint32_t)(x))
#define NXSwapLittleToHostInt64(x) ((uint64_t)(x))

#endif /* _CROSSXNU_ARCHITECTURE_BYTE_ORDER_H_ */
