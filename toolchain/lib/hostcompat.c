/*
 * Small libc compatibility layer for XNU's host-side tools.
 *
 * XNU's SETUP tools are macOS programs: they assume getprogname(),
 * fcopyfile() and a handful of Darwin headers.  None of that affects the
 * target kernel; this file only makes the build-time helpers runnable on a
 * POSIX host.
 */

#define _GNU_SOURCE 1

#include <errno.h>
#include <fcntl.h>
#include <stddef.h>
#include <stdlib.h>
#include <sys/types.h>
#include <unistd.h>

#include "copyfile.h"
#include "libc.h"
#include <mach-o/arch.h>
#include <uuid/uuid.h>

extern char *program_invocation_short_name;

const char *
getprogname(void)
{
	return program_invocation_short_name;
}

void
setprogname(const char *name)
{
	(void)name;
}

void *
setmode(const char *mode_str)
{
	mode_t *mode = malloc(sizeof(*mode));
	char *end = NULL;
	unsigned long value;

	if (mode == NULL) {
		return NULL;
	}
	errno = 0;
	value = strtoul(mode_str, &end, 8);
	if (errno != 0 || end == mode_str || *end != '\0') {
		free(mode);
		errno = EINVAL;
		return NULL;
	}
	*mode = (mode_t)value;
	return mode;
}

mode_t
getmode(const void *set, mode_t mode)
{
	if (set == NULL) {
		return mode;
	}
	return *(const mode_t *)set | mode;
}

static const NXArchInfo crossxnu_host_arch = {
#if defined(__aarch64__) || defined(__arm64__)
	.name = "arm64",
	.cputype = CPU_TYPE_ARM64,
	.cpusubtype = CPU_SUBTYPE_ARM64_ALL,
#else
	.name = "x86_64",
	.cputype = CPU_TYPE_X86_64,
	.cpusubtype = CPU_SUBTYPE_X86_64_ALL,
#endif
	.byteorder = NX_LittleEndian,
	.description = "crossxnu build host",
};

const NXArchInfo *
NXGetLocalArchInfo(void)
{
	return &crossxnu_host_arch;
}

void
uuid_generate(uuid_t out)
{
	static int seeded;
	static uint64_t state[4];
	int fd;

	if (!seeded) {
		fd = open("/dev/urandom", O_RDONLY);
		if (fd >= 0) {
			(void)read(fd, state, sizeof(state));
			close(fd);
		}
		seeded = 1;
	}
	for (size_t i = 0; i < sizeof(uuid_t) / sizeof(uint64_t); i++) {
		state[i] ^= state[i] << 13;
		state[i] ^= state[i] >> 7;
		state[i] ^= state[i] << 17;
		((uint64_t *)out)[i] = state[i];
	}
	out[6] = (uint8_t)((out[6] & 0x0f) | 0x40);
	out[8] = (uint8_t)((out[8] & 0x3f) | 0x80);
}

int
fcopyfile(int from_fd, int to_fd, void *state, int flags)
{
	char buf[65536];
	ssize_t n;

	(void)state;
	(void)flags;

	for (;;) {
		n = read(from_fd, buf, sizeof(buf));
		if (n < 0) {
			if (errno == EINTR) {
				continue;
			}
			return -1;
		}
		if (n == 0) {
			return 0;
		}
		char *p = buf;
		while (n > 0) {
			ssize_t w = write(to_fd, p, (size_t)n);
			if (w < 0) {
				if (errno == EINTR) {
					continue;
				}
				return -1;
			}
			p += w;
			n -= w;
		}
	}
}
