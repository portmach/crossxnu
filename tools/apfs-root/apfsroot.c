/*
 * apfsroot: populate an APFS volume from the HFS+ root image and switch to it.
 *
 * A static Mach-O with no libSystem and no dyld, like the init stub
 * (userland/init.c): the guest userland is a patched recovery tree, and
 * everything we run before launchd has to work without the dynamic loader.
 *
 * The tree is not walked here: the host generates a manifest (scripts/
 * gen-apfs-manifest.py) from the same directory the ramdisk is built from, so
 * this tool only has to open paths that are known to exist.  That keeps it to
 * thirteen syscalls and avoids getdirentries() entirely.
 *
 * Commands:
 *   apfsroot fs                     print the filesystem type of /mnt1
 *   apfsroot ready                  exit 0 when /mnt1 is the mounted APFS volume
 *   apfsroot populate <manifest> [dest]
 *   apfsroot boot <manifest>        populate if needed, then chroot and exec
 *                                   /sbin/launchd.real from the APFS volume
 */

#define SYS_open      0x2000005L
#define SYS_close     0x2000006L
#define SYS_read      0x2000003L
#define SYS_write     0x2000004L
#define SYS_dup2      0x200005aL
#define SYS_mkdir     0x2000088L
#define SYS_symlink   0x2000039L
#define SYS_chmod     0x200000fL
#define SYS_chroot    0x200003dL
#define SYS_chdir     0x200000cL
#define SYS_execve    0x200003bL
#define SYS_statfs    0x200009dL
#define SYS_mount     0x20000a7L
#define SYS_unmount   0x200009fL

#define MNT_UPDATE    0x00010000

#define O_RDONLY    0
#define O_WRONLY    1
#define O_RDWR      2
#define O_CREAT     0x0200
#define O_TRUNC     0x0400

#define MANIFEST_MAX (8L << 20)
#define COPY_CHUNK   65536

struct apfs_statfs {
	char space[4096];   /* struct statfs is ~2 KB; we only scan for the name */
};

static char manifest[MANIFEST_MAX];
static char copybuf[COPY_CHUNK];

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

static long sys_open(const char *p, int flags, int mode) { return syscall3(SYS_open, (long)p, flags, mode); }
static long sys_close(int fd) { return syscall3(SYS_close, fd, 0, 0); }
static long sys_read(int fd, void *b, long n) { return syscall3(SYS_read, fd, (long)b, n); }
static long sys_write(int fd, const void *b, long n) { return syscall3(SYS_write, fd, (long)b, n); }
static long sys_dup2(int from, int to) { return syscall3(SYS_dup2, from, to, 0); }
static long sys_mkdir(const char *p, int mode) { return syscall3(SYS_mkdir, (long)p, mode, 0); }
static long sys_symlink(const char *target, const char *path) { return syscall3(SYS_symlink, (long)target, (long)path, 0); }
static long sys_chmod(const char *p, int mode) { return syscall3(SYS_chmod, (long)p, mode, 0); }
static long sys_chroot(const char *p) { return syscall3(SYS_chroot, (long)p, 0, 0); }
static long sys_chdir(const char *p) { return syscall3(SYS_chdir, (long)p, 0, 0); }
static long sys_execve(const char *p, const char *const *argv, const char *const *envp) { return syscall3(SYS_execve, (long)p, (long)argv, (long)envp); }

static long
sys_statfs(const char *path, void *buf, long size)
{
	return syscall3(SYS_statfs, (long)path, (long)buf, size);
}

static long
sys_mount(const char *type, const char *path, int flags)
{
	/* devfs takes no data argument, which is the only mount we do here. */
	return syscall3(SYS_mount, (long)type, (long)path, flags);
}

static long
sys_unmount(const char *path, int flags)
{
	return syscall3(SYS_unmount, (long)path, flags, 0);
}

static long
sys_getuid(void)
{
	return syscall3(0x2000018L, 0, 0, 0);
}

static long
sys_geteuid(void)
{
	return syscall3(0x2000019L, 0, 0, 0);
}

/* ------------------------------------------------------------------ */
/* Small string helpers (no libc)                                      */
/* ------------------------------------------------------------------ */

static long
str_len(const char *s)
{
	long n = 0;

	while (s[n] != '\0') {
		n++;
	}
	return n;
}

static void
puts_fd(int fd, const char *s)
{
	sys_write(fd, s, str_len(s));
}

static inline long
syscall4(long number, long a, long b, long c, long d)
{
	long ret;
	unsigned char failed;
	register long arg4 __asm__("r10") = d;

	/* The 4th syscall argument goes in %r10 (the syscall instruction clobbers
	 * %rcx and %r11); pinning it with a register variable keeps the operand
	 * numbering out of the picture. */
	__asm__ volatile ("syscall\n\tsetc %1"
	: "=a" (ret), "=qm" (failed)
	: "a" (number), "D" (a), "S" (b), "d" (c), "r" (arg4)
	: "rcx", "r11", "memory");
	return failed ? -ret : ret;
}

static long
sys_mount_data(const char *type, const char *path, int flags, void *data)
{
	return syscall4(SYS_mount, (long)type, (long)path, flags, (long)data);
}

/* One write per line: the kernel traces every syscall, so a line assembled out
 * of several writes gets shredded in the serial log. */
struct lbuf {
	char	b[512];
	long	n;
};

static void
lb_init(struct lbuf *l)
{
	l->n = 0;
}

static void
lb_puts(struct lbuf *l, const char *s)
{
	while (*s != '\0' && l->n < (long)sizeof(l->b) - 1) {
		l->b[l->n++] = *s++;
	}
}

static void
lb_dec(struct lbuf *l, unsigned long value)
{
	char tmp[24];
	int i = 0;

	if (value == 0) {
		lb_puts(l, "0");
		return;
	}
	while (value != 0 && i < (int)sizeof(tmp)) {
		tmp[i++] = (char)('0' + (value % 10));
		value /= 10;
	}
	while (i-- > 0) {
		if (l->n < (long)sizeof(l->b) - 1) {
			l->b[l->n++] = tmp[i];
		}
	}
}

static void
lb_flush(struct lbuf *l, int fd)
{
	sys_write(fd, l->b, l->n);
	l->n = 0;
}

static void
put_dec(int fd, unsigned long value)
{
	char tmp[24];
	int i = 0;

	if (value == 0) {
		sys_write(fd, "0", 1);
		return;
	}
	while (value != 0 && i < (int)sizeof(tmp)) {
		tmp[i++] = (char)('0' + (value % 10));
		value /= 10;
	}
	while (i-- > 0) {
		sys_write(fd, &tmp[i], 1);
	}
}

static int
parse_octal(const char *s)
{
	int value = 0;

	while (*s >= '0' && *s <= '7') {
		value = value * 8 + (*s - '0');
		s++;
	}
	return value;
}

/* Build "prefix" + "/" + "path" into out; return 0 on overflow. */
static int
join(char *out, long cap, const char *prefix, const char *path)
{
	long n = 0;

	while (*prefix != '\0') {
		if (n + 1 >= cap) {
			return 0;
		}
		out[n++] = *prefix++;
	}
	if (n + 1 < cap) {
		out[n++] = '/';
	} else {
		return 0;
	}
	while (*path != '\0') {
		if (n + 1 >= cap) {
			return 0;
		}
		out[n++] = *path++;
	}
	out[n] = '\0';
	return 1;
}

static long
slurp(const char *path, char *buf, long cap)
{
	long fd = sys_open(path, O_RDONLY, 0);
	long total = 0;

	if (fd < 0) {
		return fd;
	}
	for (;;) {
		long n = sys_read((int)fd, buf + total, cap - total - 1);

		if (n <= 0) {
			break;
		}
		total += n;
		if (total >= cap - 1) {
			break;
		}
	}
	sys_close((int)fd);
	buf[total] = '\0';
	return total;
}

/* ------------------------------------------------------------------ */
/* Filesystem detection                                                */
/* ------------------------------------------------------------------ */

static const char *
fstype_of(const char *path)
{
	static struct apfs_statfs sfs;
	char *raw = sfs.space;
	long len = (long)sizeof(sfs.space);

	if (sys_statfs(path, &sfs, (long)sizeof(sfs)) != 0) {
		return 0;
	}
	for (long i = 0; i + 4 < len; i++) {
		if ((raw[i] == 'a' && raw[i + 1] == 'p' && raw[i + 2] == 'f' &&
		    raw[i + 3] == 's' && raw[i + 4] == '\0') ||
		    (raw[i] == 'h' && raw[i + 1] == 'f' && raw[i + 2] == 's' &&
		    raw[i + 3] == '\0')) {
			return &raw[i];
		}
	}
	return 0;
}

/* ------------------------------------------------------------------ */
/* Populate                                                            */
/* ------------------------------------------------------------------ */

/* The first few copy failures are reported with the errno the syscall
 * returned (syscalls yield -errno), so a broken manifest or a read-only target
 * is visible in the log instead of a bare count. */
#define FAIL_REPORT_MAX 32

static void
report_fail(const char *side, const char *path, long err, long *shown)
{
	struct lbuf l;

	if (*shown >= FAIL_REPORT_MAX) {
		return;
	}
	(*shown)++;

	lb_init(&l);
	lb_puts(&l, "apfsroot: fail ");
	lb_puts(&l, side);
	lb_puts(&l, "=");
	lb_puts(&l, path);
	lb_puts(&l, " errno ");
	lb_dec(&l, (unsigned long)(err < 0 ? -err : err));
	lb_puts(&l, "\n");
	lb_flush(&l, 1);
}

/* Print the errno of the operations the copy depends on, so one boot says
 * whether the target is writable, whether directories are really being made,
 * and whether the sources exist. */
static void
probe_target(const char *dest)
{
	char dir[512], file[512], src[512];
	long r;

	if (!join(dir, (long)sizeof(dir), dest, ".probe") ||
	    !join(file, (long)sizeof(file), dest, ".probe/x") ||
	    !join(src, (long)sizeof(src), "",
	    "System/Library/CoreServices/SystemVersion.plist")) {
		puts_fd(2, "apfsroot: probe paths too long\n");
		return;
	}

	struct lbuf l;

	r = sys_mkdir(dir, 0755);
	lb_init(&l);
	lb_puts(&l, "apfsroot: probe mkdir ");
	lb_puts(&l, dir);
	lb_puts(&l, " -> ");
	lb_dec(&l, (unsigned long)(r < 0 ? -r : 0));
	lb_puts(&l, "\n");
	lb_flush(&l, 1);

	long fd = sys_open(file, O_WRONLY | O_CREAT | O_TRUNC, 0644);

	lb_init(&l);
	lb_puts(&l, "apfsroot: probe create ");
	lb_puts(&l, file);
	lb_puts(&l, " -> ");
	lb_dec(&l, (unsigned long)(fd < 0 ? -fd : 0));
	lb_puts(&l, "\n");
	lb_flush(&l, 1);
	if (fd >= 0) {
		sys_close((int)fd);
	}

	fd = sys_open(src, O_RDONLY, 0);
	lb_init(&l);
	lb_puts(&l, "apfsroot: probe read ");
	lb_puts(&l, src);
	lb_puts(&l, " -> ");
	lb_dec(&l, (unsigned long)(fd < 0 ? -fd : 0));
	lb_puts(&l, "\n");
	lb_flush(&l, 1);
	if (fd >= 0) {
		sys_close((int)fd);
	}
}

static int
populate(const char *manifest_path, const char *dest)
{
	long entries = 0, dirs = 0, files = 0, links = 0, failed = 0, shown = 0;
	unsigned long bytes = 0;
	char dst[1024], src[1024];
	long n = slurp(manifest_path, manifest, MANIFEST_MAX);

	if (n <= 0) {
		struct lbuf l;

		lb_init(&l);
		lb_puts(&l, "apfsroot: cannot read manifest ");
		lb_puts(&l, manifest_path);
		lb_puts(&l, "\n");
		lb_flush(&l, 2);
		return -1;
	}

	probe_target(dest);

	/* First few entries, verbatim, to see what the parser produced. */
	{
		char *p = manifest;
		int shown_entries = 0;

		while (*p != '\0' && shown_entries < 5) {
			char *end = p;

			while (*end != '\0' && *end != '\n') {
				end++;
			}
			char saved = *end;
			*end = '\0';
			struct lbuf l;

			lb_init(&l);
			lb_puts(&l, "apfsroot: entry ");
			lb_puts(&l, *p != '\0' ? p : "(empty)");
			lb_puts(&l, "\n");
			lb_flush(&l, 1);
			*end = saved;
			shown_entries++;
			p = (saved == '\0') ? end : end + 1;
		}
	}

	char *line = manifest;
	while (*line != '\0') {
		char *end = line;
		char *fields[4];
		int nf = 0;

		while (*end != '\0' && *end != '\n') {
			end++;
		}
		char saved = *end;
		*end = '\0';

		if (line[0] != '\0' && line[0] != '#') {
			fields[nf++] = line;
			for (char *p = line; *p != '\0' && nf < 4; p++) {
				if (*p == '\t') {
					*p = '\0';
					fields[nf++] = p + 1;
				}
			}
			if (nf >= 3) {
				char type = fields[0][0];
				int mode = parse_octal(fields[1]);
				const char *path = fields[2];

				entries++;
				if (join(dst, (long)sizeof(dst), dest, path) &&
				    join(src, (long)sizeof(src), "", path)) {
					long err = 0;

					if (type == 'D') {
						sys_mkdir(dst, mode);
						dirs++;
					} else if (type == 'L' && nf >= 4) {
						err = sys_symlink(fields[3], dst);
						if (err != 0) {
							failed++;
							report_fail("dst", dst, err, &shown);
						} else {
							links++;
						}
					} else if (type == 'F') {
						long sfd = sys_open(src, O_RDONLY, 0);
						long dfd = -1;

						if (sfd >= 0) {
							dfd = sys_open(dst,
							    O_WRONLY | O_CREAT | O_TRUNC, mode);
							err = dfd;
						} else {
							err = sfd;
						}
						if (sfd < 0 || dfd < 0) {
							failed++;
							report_fail(sfd < 0 ? "src" : "dst",
							    sfd < 0 ? src : dst, err, &shown);
							if (sfd >= 0) {
								sys_close((int)sfd);
							}
						} else {
							for (;;) {
								long r = sys_read((int)sfd,
								    copybuf, COPY_CHUNK);
								long w;

								if (r == 0) {
									break;
								}
								if (r < 0) {
									failed++;
									report_fail("read", src, r,
									    &shown);
									break;
								}
								w = sys_write((int)dfd, copybuf, r);
								if (w != r) {
									failed++;
									report_fail("write", dst,
									    w < 0 ? w : -5, &shown);
									break;
								}
								bytes += (unsigned long)r;
							}
							sys_close((int)sfd);
							sys_close((int)dfd);
							sys_chmod(dst, mode);
							files++;
						}
					}
				} else {
					failed++;
				}
			}
			if ((entries % 200) == 0) {
				struct lbuf l;

				lb_init(&l);
				lb_puts(&l, "apfsroot: ");
				lb_dec(&l, (unsigned long)entries);
				lb_puts(&l, " entries, ");
				lb_dec(&l, bytes >> 20);
				lb_puts(&l, " MiB\n");
				lb_flush(&l, 1);
			}
		}

		*end = saved;
		line = (saved == '\0') ? end : end + 1;
	}

	struct lbuf l;

	lb_init(&l);
	lb_puts(&l, "apfsroot: copied ");
	lb_dec(&l, (unsigned long)files);
	lb_puts(&l, " files (");
	lb_dec(&l, bytes >> 20);
	lb_puts(&l, " MiB), ");
	lb_dec(&l, (unsigned long)dirs);
	lb_puts(&l, " dirs, ");
	lb_dec(&l, (unsigned long)links);
	lb_puts(&l, " symlinks, ");
	lb_dec(&l, (unsigned long)failed);
	lb_puts(&l, " failures\n");
	lb_flush(&l, 1);

	return failed == 0 ? 0 : -1;
}

/* ------------------------------------------------------------------ */
/* Commands                                                            */
/* ------------------------------------------------------------------ */

static const char *const launchd_argv[] = { "/sbin/launchd.real", 0 };
static const char *const launchd_envp[] = {
	"PATH=/usr/bin:/bin:/usr/sbin:/sbin",
	"HOME=/var/root",
	"SHELL=/bin/sh",
	0
};

/* The old bring-up path: /bin/sh /etc/rc.launchd prepares /private/var and
 * execs the real launchd from the HFS+ root.  Used whenever the APFS root
 * cannot be prepared, so pid 1 never just dies (the kernel panics on that). */
static const char *const shell_argv[] = { "/bin/sh", "/etc/rc.launchd", 0 };

static void
fallback_to_hfs(void)
{
	puts_fd(2, "apfsroot: falling back to the HFS+ root\n");
	sys_execve("/bin/sh", shell_argv, launchd_envp);
	syscall3(0x2000001L, 1, 0, 0);   /* exit */
	__builtin_unreachable();
}

static int
apfs_ready(void)
{
	const char *type = fstype_of("/mnt1");

	return (type != 0 && type[0] == 'a' && type[1] == 'p');
}

static int
mark_done(const char *target)
{
	char path[256];
	long fd;

	if (!join(path, (long)sizeof(path), target, ".apfsroot-done")) {
		return -1;
	}
	fd = sys_open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
	if (fd < 0) {
		return -1;
	}
	sys_write((int)fd, "ok\n", 3);
	sys_close((int)fd);
	return 0;
}


/* ------------------------------------------------------------------ */
/* Target selection                                                    */
/* ------------------------------------------------------------------ */

/*
 * The kernel mounts the APFS volume at /mnt1 read-only (APFS refuses a
 * read-write container/root mount: ENOENT, see bsd_init.c).  The volume cannot
 * be mounted a second time either (mount(2) answers EPERM), so it is either
 * remounted read-write in place with MNT_UPDATE, or unmounted and mounted again
 * at /mnt2.  Both are tried here, and the first success becomes the target.
 *
 * The arguments are the shape imageboot.c uses: mount(2)'s data points at a
 * struct whose first field is the device path; mount_common() copies that
 * pointer out and hands the zeroed rest (the APFS args block) to the
 * filesystem.
 */
static struct {
	char *fspec;
	char  rest[336];
} args;

/*
 * APFS dispatches on a 16-bit mount_mode at offset 8 of its args block (0..8
 * are valid, and 0 is what a NULL block turns into).  Walk them and keep the
 * first that actually mounts the volume at /mnt2.
 */
static int
mode_sweep(const char *node)
{
	for (unsigned long mode = 0; mode <= 8; mode++) {
		struct lbuf l;
		long r;

		for (unsigned long k = 0; k < sizeof(args.rest); k++) {
			args.rest[k] = 0;
		}
		args.fspec = (char *)node;
		args.rest[0] = (char)(mode & 0xFF);
		args.rest[1] = 0;

		r = sys_mount_data("apfs", "/mnt2", 0x00100000 /* DONTBROWSE */,
		    &args);

		lb_init(&l);
		lb_puts(&l, "apfsroot: mode ");
		lb_dec(&l, mode);
		lb_puts(&l, " -> ");
		lb_dec(&l, (unsigned long)(r < 0 ? -r : 0));
		lb_puts(&l, "\n");
		lb_flush(&l, 1);

		if (r == 0) {
			return 0;
		}
	}
	return -1;
}

static const char *
prepare_target(void)
{
	static const char *const nodes[] = {
		"/dev/disk0s1", "/dev/disk0s2", "/dev/disk0s3",
		"/dev/disk1s1", "/dev/disk1s2", "/dev/disk1s3",
		"/dev/disk2s1", "/dev/disk2s2", "/dev/disk2s3",
		0
	};

	sys_mkdir("/mnt2", 0755);

	/* The kernel mounts the volume itself now (bsd_init.c tries /dev/disk1s1
	 * read-write first); if that worked, /mnt1 is writable and we are done. */
	if (apfs_ready()) {
		char probe[256];

		if (join(probe, (long)sizeof(probe), "/mnt1", ".wtest")) {
			long fd = sys_open(probe, O_WRONLY | O_CREAT | O_TRUNC, 0644);
			struct lbuf l;

			lb_init(&l);
			lb_puts(&l, "apfsroot: /mnt1 writable test -> ");
			lb_dec(&l, (unsigned long)(fd < 0 ? -fd : 0));
			lb_puts(&l, "\n");
			lb_flush(&l, 1);

			if (fd >= 0) {
				sys_close((int)fd);
				return "/mnt1";
			}
		}
	}

	/* Baseline: mount(2) needs root, and devfs needs no APFS involvement at
	 * all.  Both numbers say whether an EPERM below is about permissions or
	 * about the filesystem. */
	{
		struct lbuf l;

		lb_init(&l);
		lb_puts(&l, "apfsroot: uid ");
		lb_dec(&l, (unsigned long)sys_getuid());
		lb_puts(&l, " euid ");
		lb_dec(&l, (unsigned long)sys_geteuid());
		lb_puts(&l, "\n");
		lb_flush(&l, 1);

		long d = sys_mount("devfs", "/mnt2", 0);

		lb_init(&l);
		lb_puts(&l, "apfsroot: probe devfs mount -> ");
		lb_dec(&l, (unsigned long)(d < 0 ? -d : 0));
		lb_puts(&l, "\n");
		lb_flush(&l, 1);
		if (d == 0) {
			sys_unmount("/mnt2", 0);
		}
	}

	for (int i = 0; nodes[i] != 0; i++) {
		struct lbuf l;
		long fd = sys_open(nodes[i], O_RDONLY, 0);

		lb_init(&l);
		lb_puts(&l, "apfsroot: node ");
		lb_puts(&l, nodes[i]);
		lb_puts(&l, " -> ");
		lb_dec(&l, (unsigned long)(fd < 0 ? -fd : 0));
		lb_puts(&l, "\n");
		lb_flush(&l, 1);

		if (fd < 0) {
			continue;
		}
		sys_close((int)fd);

		/* First while the kernel's read-only mount still holds the volume:
		 * if APFS allows a second, writable mount, this is the cheap path. */
		puts_fd(1, "apfsroot: sweep with /mnt1 mounted\n");
		if (mode_sweep(nodes[i]) == 0) {
			return "/mnt2";
		}

		/* Otherwise drop the read-only mount and try again. */
		long u = sys_unmount("/mnt1", 0);

		lb_init(&l);
		lb_puts(&l, "apfsroot: unmount /mnt1 -> ");
		lb_dec(&l, (unsigned long)(u < 0 ? -u : 0));
		lb_puts(&l, "\n");
		lb_flush(&l, 1);

		puts_fd(1, "apfsroot: sweep after unmount\n");
		if (mode_sweep(nodes[i]) == 0) {
			return "/mnt2";
		}
	}

	return 0;
}

static int
do_boot(const char *manifest_path)
{
	char nul_dev[] = "/dev/null";
	const char *target = prepare_target();

	if (target == 0) {
		puts_fd(2, "apfsroot: cannot get a writable APFS volume\n");
		return 2;
	}
	{
		struct lbuf l;

		lb_init(&l);
		lb_puts(&l, "apfsroot: target is ");
		lb_puts(&l, target);
		lb_puts(&l, "\n");
		lb_flush(&l, 1);
	}

	/* A completed copy leaves a marker; otherwise the volume is either empty
	 * or holds a half-written tree from an interrupted boot, and copying
	 * again is harmless (files are truncated and rewritten). */
	{
		char marker[256];
		int done = 0;

		if (join(marker, (long)sizeof(marker), target,
		    ".apfsroot-done")) {
			done = (sys_open(marker, O_RDONLY, 0) >= 0);
		}

		if (!done) {
			puts_fd(1, "apfsroot: populating the APFS volume\n");
			if (populate(manifest_path, target) != 0) {
				/* Do not chroot into a tree we know is incomplete: the
				 * exec would fail and the kernel panics on pid 1
				 * exiting. */
				puts_fd(2, "apfsroot: populate incomplete, "
				    "keeping the HFS root\n");
				return 3;
			}
			mark_done(target);
		} else {
			puts_fd(1, "apfsroot: volume already populated\n");
		}
	}

	/* devfs lives on the old root's /dev; give the APFS root its own. */
	{
		char devdir[256];

		if (join(devdir, (long)sizeof(devdir), target, "dev")) {
			sys_mkdir(devdir, 0755);
			long devfs = sys_mount("devfs", devdir, 0);

			if (devfs != 0) {
				struct lbuf l;

				lb_init(&l);
				lb_puts(&l, "apfsroot: devfs inside the volume "
				    "failed (");
				lb_dec(&l, (unsigned long)(devfs < 0 ? -devfs : devfs));
				lb_puts(&l, ")\n");
				lb_flush(&l, 2);
			}
		}
	}

	if (sys_chroot(target) != 0) {
		puts_fd(2, "apfsroot: chroot failed\n");
		return 4;
	}
	if (sys_chdir("/") != 0) {
		puts_fd(2, "apfsroot: chdir failed\n");
		return 5;
	}

	puts_fd(2, "apfsroot: exec /sbin/launchd.real from APFS\n");

	/* launchd refuses to run when stdout is a terminal (see rc.launchd). */
	long nul = sys_open(nul_dev, O_RDWR, 0);

	if (nul >= 0) {
		sys_dup2((int)nul, 0);
		sys_dup2((int)nul, 1);
		if (nul > 2) {
			sys_close((int)nul);
		}
	}

	long error = sys_execve("/sbin/launchd.real", launchd_argv, launchd_envp);

	puts_fd(2, "apfsroot: cannot exec launchd\n");
	return (int)(-error) & 0x7f;
}

static int
str_eq(const char *a, const char *b)
{
	while (*a != '\0' && *a == *b) {
		a++;
		b++;
	}
	return *a == *b;
}

/*
 * The kernel jumps to _start with the usual process stack: [argc][argv...]
 * [NULL][envp...].  argc/argv have to be taken there, before any prologue
 * moves %rsp, so the entry is assembly and the C part takes them as arguments.
 */
int apfsroot_main(long argc, char **argv) __attribute__((used));

__asm__(
	".globl _start\n"
	"_start:\n"
	"\tmovq (%rsp), %rdi\n"        /* argc */
	"\tleaq 8(%rsp), %rsi\n"       /* argv */
	"\txorl %ebp, %ebp\n"
	"\tandq $-16, %rsp\n"
	"\tcall _apfsroot_main\n"
	"\tud2\n");

int
apfsroot_main(long argc, char **argv)
{
	int status = 1;

	if (argc >= 2 && str_eq(argv[1], "fs")) {
		const char *type = fstype_of("/mnt1");

		puts_fd(1, "apfsroot: /mnt1 type ");
		puts_fd(1, type != 0 ? type : "unknown");
		puts_fd(1, "\n");
		status = 0;
	} else if (argc >= 2 && str_eq(argv[1], "ready")) {
		status = apfs_ready() ? 0 : 1;
	} else if (argc >= 4 && str_eq(argv[1], "populate")) {
		status = populate(argv[2], argv[3]) == 0 ? 0 : 1;
	} else if (argc >= 3 && str_eq(argv[1], "boot")) {
		status = do_boot(argv[2]);
		if (status != 0) {
			/* We are pid 1 here (rc.apfs execs us): hand the boot back to
			 * the HFS+ path instead of exiting, which would panic. */
			fallback_to_hfs();
		}
	} else if (argc >= 1) {
		puts_fd(2, "usage: apfsroot {fs|ready|populate <manifest> <dest>|"
		    "boot <manifest>}\n");
		puts_fd(2, "apfsroot: argc=");
		put_dec(2, (unsigned long)argc);
		puts_fd(2, " argv1=");
		puts_fd(2, (argc >= 2 && argv[1] != 0) ? argv[1] : "(none)");
		puts_fd(2, "\n");
		status = 64;
	}

	syscall3(0x2000001L, status, 0, 0);   /* exit */
	__builtin_unreachable();
}
