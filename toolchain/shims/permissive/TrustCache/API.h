#ifndef _CROSSXNU_PERMISSIVE_TRUSTCACHE_API_H_
#define _CROSSXNU_PERMISSIVE_TRUSTCACHE_API_H_

/*
 * Permissive-mode TrustCache shim.
 *
 * This is NOT a copy of Apple's libTrustCache ABI.  It only exists for
 * CROSSXNU_SECURITY_PERMISSIVE builds, where the implementation in
 * kern_trustcache.c returns from every public entry point before touching
 * AMFI.  No object of these types is ever handed to Apple's AMFI kext.
 *
 * A strict build must use the real TrustCache headers from the matching
 * macOS SDK; see docs/security-flags.md.
 */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct _TrustCache {
	uint8_t opaque[256];
} TrustCache_t;

typedef struct _TrustCacheRuntime {
	uint8_t opaque[512];
} TrustCacheRuntime_t;

typedef struct _TrustCacheMutableRuntime {
	uint8_t opaque[512];
} TrustCacheMutableRuntime_t;

typedef struct _TrustCacheQueryToken {
	uint64_t opaque[8];
} TrustCacheQueryToken_t;

typedef uint64_t TCCapabilities_t;
typedef uint32_t TCType_t;
typedef uint32_t TCQueryType_t;

#define kUUIDSize 16
#define kTCEntryHashSize 20

/* Types used by kern_trustcache.c; values are not ABI-relevant in permissive. */
enum {
	kTCTypeInvalid = 0,
	kTCTypeLTRS,
	kTCTypeCryptex1BootOS,
	kTCTypeCryptex1BootApp,
	kTCTypeStatic,
	kTCTypeEngineering,
	kTCTypeLegacy,
	kTCTypeDTRS,
	kTCTypeTotal
};

enum {
	kTCQueryTypeAll = 0,
	kTCQueryTypeStatic,
	kTCQueryTypeLoadable,
	kTCQueryTypeTotal
};

typedef struct {
	uint8_t component;
	uint8_t error;
	uint32_t uniqueError;
} TCReturn_t;

#define kTCReturnSuccess 0
#define kTCReturnNotFound 1
#define kTCReturnDuplicate 2
#define kTCReturnError 3

#define kTCCapabilityNone 0

typedef struct {
	const char *entitlementValue;
} TCTypeConfigEntry_t;

/* Only compiled by permissive builds; never passed to AMFI. */
static const TCTypeConfigEntry_t TCTypeConfig[kTCTypeTotal] __attribute__((unused)) = { { 0 } };

static inline void
trustCacheInitializeRuntime(TrustCacheRuntime_t *runtime, ...)
{
	(void)runtime;
}

#endif /* _CROSSXNU_PERMISSIVE_TRUSTCACHE_API_H_ */
