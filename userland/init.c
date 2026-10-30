/*
 * crossxnu init: a static Mach-O (no libSystem, no dyld) that gives itself a
 * console and then runs /bin/sh on /etc/rc.local.
 *
 * pid 1 gets no stdio from the kernel, so an interpreted init (a #! script or
 * even /bin/sh itself) dies with EBADF before printing anything.  This stub
 * opens /dev/console, wires it to fd 0/1/2, and execs the shell with a script
 * argument, which never needs to read commands from stdin.
 */
static inline long
syscall3(long number, long a, long b, long c)
{
	long ret;
	unsigned char failed;
	__asm__ volatile ("syscall\n\tsetc %1"
	: "=a" (ret), "=qm" (failed)
	: "a" (number), "D" (a), "S" (b), "d" (c)
	: "rcx", "r11", "memory");
	return failed ? -ret : ret;
}

static inline long
sys_open(const char *path, int flags, int mode)
{
	return syscall3(0x2000005L, (long)path, (long)flags, (long)mode);
}

static inline long
sys_close(int fd)
{
	return syscall3(0x2000006L, (long)fd, 0, 0);
}

static inline long
sys_dup2(int from, int to)
{
	return syscall3(0x200005aL, (long)from, (long)to, 0);
}

static inline long
sys_write(int fd, const void *buf, unsigned long len)
{
	return syscall3(0x2000004L, (long)fd, (long)buf, (long)len);
}

static inline long
sys_execve(const char *path, const char *const *argv, const char *const *envp)
{
	return syscall3(0x200003bL, (long)path, (long)argv, (long)envp);
}

static inline __attribute__((noreturn)) void
sys_exit(int code)
{
	syscall3(0x2000001L, (long)code, 0, 0);
	__builtin_unreachable();
}

static const char console_path[] = "/dev/console";
static const char shell_path[] = "/bin/sh";
/*
 * Two boot scripts: /etc/rc.local drops to an interactive shell (bring-up),
 * /etc/rc.launchd prepares /private/var and execs the real launchd as pid 1.
 * The stub picks the launchd one when it is present, so the ramdisk decides.
 */
static const char rc_interactive_path[] = "/etc/rc.local";
static const char rc_launchd_path[] = "/etc/rc.launchd";
static const char fail_msg[] = "crossxnu-init: cannot exec /bin/sh /etc/rc.local\n";

static const char *const shell_argv[] = { shell_path, rc_interactive_path, 0 };
static const char *const shell_argv_launchd[] = { shell_path, rc_launchd_path, 0 };
static const char *const shell_envp[] = {
	"PATH=/usr/bin:/bin:/usr/sbin:/sbin",
	"HOME=/",
	"SHELL=/bin/sh",
	0
};

__attribute__((noreturn)) void
start(void)
{
	long fd = sys_open(console_path, 2 /* O_RDWR */, 0);
	if (fd >= 0) {
		sys_dup2((int)fd, 0);
		sys_dup2((int)fd, 1);
		sys_dup2((int)fd, 2);
		if (fd > 2) {
			sys_close((int)fd);
		}
	}

	long error;

	/* Prefer the launchd path when the ramdisk ships that script. */
	if (sys_open(rc_launchd_path, 0 /* O_RDONLY */, 0) >= 0) {
		error = sys_execve(shell_path, shell_argv_launchd, shell_envp);
	} else {
		error = sys_execve(shell_path, shell_argv, shell_envp);
	}
	sys_write(2, fail_msg, sizeof(fail_msg) - 1);
	sys_exit((int)(-error) & 0x7f);
}
