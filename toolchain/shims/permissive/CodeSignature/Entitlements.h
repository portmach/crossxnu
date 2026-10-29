#ifndef _CROSSXNU_PERMISSIVE_CODESIGNATURE_ENTITLEMENTS_H_
#define _CROSSXNU_PERMISSIVE_CODESIGNATURE_ENTITLEMENTS_H_

/*
 * Permissive-mode CodeSignature entitlement constants.
 *
 * These are the four browser-related entitlements referenced by XNU's
 * kern_exec.c and necp_client.c.  They are string constants only; the
 * actual entitlement enforcement is disabled by the permissive profile.
 *
 * A strict build must use the real CodeSignature/Entitlements.h from the
 * matching macOS SDK.  Verify the strings before relying on browser
 * hardware-required-entitlement behavior.
 */

#define kCSWebBrowserHostEntitlement \
	"com.apple.private.web-browser-host"
#define kCSWebBrowserGPUEntitlement \
	"com.apple.private.web-browser-gpu"
#define kCSWebBrowserNetworkEntitlement \
	"com.apple.private.web-browser-network"
#define kCSWebBrowserWebContentEntitlement \
	"com.apple.private.web-browser-web-content"

#endif /* _CROSSXNU_PERMISSIVE_CODESIGNATURE_ENTITLEMENTS_H_ */
