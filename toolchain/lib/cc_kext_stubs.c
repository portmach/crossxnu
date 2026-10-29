/*
 * Minimal libcc_kext shims for the crossxnu kernel link.
 *
 * The real libcc_kext comes from Apple's toolchain and contains the C++
 * runtime plus compiler-rt.  This phase-1 shim provides only the symbols the
 * XNU link currently needs.  It is build-only, not an ABI-compatible kext C++
 * runtime.
 */

#include <stdint.h>

int
__cxa_atexit(void (*func)(void *), void *arg, void *dso_handle)
{
	(void)func;
	(void)arg;
	(void)dso_handle;
	return 0;
}

uint64_t
__llvm_profile_get_size_for_buffer_internal(
	const char *DataBegin,
	const char *DataEnd,
	const char *CountersBegin,
	const char *CountersEnd,
	const char *BitmapBegin,
	const char *BitmapEnd,
	const char *NamesBegin,
	const char *NamesEnd,
	const char *VTableBegin,
	const char *VTableEnd,
	const char *VNamesBegin,
	const char *VNamesEnd)
{
	(void)DataBegin;
	(void)DataEnd;
	(void)CountersBegin;
	(void)CountersEnd;
	(void)BitmapBegin;
	(void)BitmapEnd;
	(void)NamesBegin;
	(void)NamesEnd;
	(void)VTableBegin;
	(void)VTableEnd;
	(void)VNamesBegin;
	(void)VNamesEnd;
	return 0;
}

int
__llvm_profile_write_buffer_internal(
	char *Buffer,
	const char *DataBegin,
	const char *DataEnd,
	const char *CountersBegin,
	const char *CountersEnd,
	const char *BitmapBegin,
	const char *BitmapEnd,
	const char *NamesBegin,
	const char *NamesEnd)
{
	(void)Buffer;
	(void)DataBegin;
	(void)DataEnd;
	(void)CountersBegin;
	(void)CountersEnd;
	(void)BitmapBegin;
	(void)BitmapEnd;
	(void)NamesBegin;
	(void)NamesEnd;
	return -1;
}
