#ifndef _CROSSXNU_PERMISSIVE_COREENTITLEMENTS_V2_API_H_
#define _CROSSXNU_PERMISSIVE_COREENTITLEMENTS_V2_API_H_

/*
 * Minimal CoreEntitlements V2 surface for the permissive AMFI header.
 *
 * XNU's open-source tree ships CoreEntitlements v1 headers but not the V2
 * API; AMFI is optional in permissive mode, so reuse the v1 types and keep
 * only the V2-only kernel-API marker opaque.
 *
 * A strict build must use the real V2 headers from the matching SDK.
 */

#include <CoreEntitlements/CoreEntitlements.h>

typedef const struct CEContext *CEContext_t;
typedef struct _CEKernelAPI CEKernelAPI_t;

#endif /* _CROSSXNU_PERMISSIVE_COREENTITLEMENTS_V2_API_H_ */
