#!/usr/bin/env bash
# Build Apple's MIG (mig + migcom) on Linux.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

SRC="${CROSSXNU_BOOTSTRAP}/migcom.tproj"
BUILD="${CROSSXNU_MIGDIR}"
H="${BUILD}/include"

if [[ ! -d "${SRC}" ]]; then
    echo "error: MIG sources not found at ${SRC}" >&2
    echo "       run: git submodule update --init --depth 1" >&2
    exit 1
fi

rm -rf "${BUILD}"
mkdir -p "${BUILD}/include/machine" "${BUILD}/include/linux"

cat > "${H}/stdio.h" <<'EOF'
#ifndef _MIG_HOST_STDIO_H_
#define _MIG_HOST_STDIO_H_
#include <stddef.h>
#include <stdarg.h>
typedef struct __sFILE FILE;
extern FILE *stdin;
extern FILE *stdout;
extern FILE *stderr;
int printf(const char *, ...);
int fprintf(FILE *, const char *, ...);
int sprintf(char *, const char *, ...);
int snprintf(char *, size_t, const char *, ...);
int vfprintf(FILE *, const char *, va_list);
int fputc(int, FILE *);
int fputs(const char *, FILE *);
FILE *fopen(const char *, const char *);
int fclose(FILE *);
int fflush(FILE *);
void perror(const char *);
int fileno(FILE *);
int getc(FILE *);
int ferror(FILE *);
void clearerr(FILE *);
size_t fread(void *, size_t, size_t, FILE *);
size_t fwrite(const void *, size_t, size_t, FILE *);
#define EOF (-1)
#endif
EOF

cat > "${H}/stdlib.h" <<'EOF'
#ifndef _MIG_HOST_STDLIB_H_
#define _MIG_HOST_STDLIB_H_
#include <stddef.h>
void *malloc(size_t);
void *calloc(size_t, size_t);
void *realloc(void *, size_t);
void free(void *);
void exit(int) __attribute__((__noreturn__));
void abort(void) __attribute__((__noreturn__));
int atoi(const char *);
long strtol(const char *, char **, int);
void qsort(void *, size_t, size_t, int (*)(const void *, const void *));
#endif
EOF

cat > "${H}/string.h" <<'EOF'
#ifndef _MIG_HOST_STRING_H_
#define _MIG_HOST_STRING_H_
#include <stddef.h>
void *memcpy(void *, const void *, size_t);
void *memmove(void *, const void *, size_t);
void *memset(void *, int, size_t);
int memcmp(const void *, const void *, size_t);
size_t strlen(const char *);
int strcmp(const char *, const char *);
int strncmp(const char *, const char *, size_t);
char *strcpy(char *, const char *);
char *strncpy(char *, const char *, size_t);
char *strcat(char *, const char *);
char *strchr(const char *, int);
char *strrchr(const char *, int);
char *strstr(const char *, const char *);
char *strdup(const char *);
char *strerror(int);
int strcasecmp(const char *, const char *);
int strncasecmp(const char *, const char *, size_t);
#endif
EOF

cat > "${H}/ctype.h" <<'EOF'
#ifndef _MIG_HOST_CTYPE_H_
#define _MIG_HOST_CTYPE_H_
int isalpha(int);
int isalnum(int);
int isdigit(int);
int isspace(int);
int isupper(int);
int islower(int);
int tolower(int);
int toupper(int);
#endif
EOF

cat > "${H}/time.h" <<'EOF'
#ifndef _MIG_HOST_TIME_H_
#define _MIG_HOST_TIME_H_
typedef long time_t;
time_t time(time_t *);
#endif
EOF

cat > "${H}/assert.h" <<'EOF'
#ifndef _MIG_HOST_ASSERT_H_
#define _MIG_HOST_ASSERT_H_
void abort(void) __attribute__((__noreturn__));
#define assert(x) ((x) ? (void)0 : abort())
#endif
EOF

cat > "${H}/errno.h" <<'EOF'
#ifndef _MIG_HOST_ERRNO_H_
#define _MIG_HOST_ERRNO_H_
int *__errno_location(void);
#define errno (*__errno_location())
#define EINTR 4
#endif
EOF

cat > "${H}/unistd.h" <<'EOF'
#ifndef _MIG_HOST_UNISTD_H_
#define _MIG_HOST_UNISTD_H_
#include <stddef.h>
int isatty(int);
int close(int);
long read(int, void *, size_t);
long write(int, const void *, size_t);
#endif
EOF

cat > "${H}/limits.h" <<'EOF'
#ifndef _MIG_HOST_LIMITS_H_
#define _MIG_HOST_LIMITS_H_
#define CHAR_BIT 8
#define SCHAR_MIN (-128)
#define SCHAR_MAX 127
#define UCHAR_MAX 255
#define SHRT_MIN (-32768)
#define SHRT_MAX 32767
#define USHRT_MAX 65535
#define INT_MIN (-2147483647 - 1)
#define INT_MAX 2147483647
#define UINT_MAX 4294967295U
#define LONG_MIN (-9223372036854775807L - 1)
#define LONG_MAX 9223372036854775807L
#define ULONG_MAX 18446744073709551615UL
#define LLONG_MIN (-9223372036854775807LL - 1)
#define LLONG_MAX 9223372036854775807LL
#define ULLONG_MAX 18446744073709551615ULL
#endif
EOF

cat > "${H}/linux/types.h" <<'EOF'
#ifndef _MIG_HOST_LINUX_TYPES_H_
#define _MIG_HOST_LINUX_TYPES_H_
typedef unsigned int u_int;
#endif
EOF

cat > "${H}/machine/limits.h" <<'EOF'
#ifndef _MACHINE_LIMITS_H_
#define _MACHINE_LIMITS_H_
#include <limits.h>
#endif
EOF

cat > "${H}/linux_compat.h" <<'EOF'
#ifndef MIG_LINUX_COMPAT_H
#define MIG_LINUX_COMPAT_H
typedef unsigned int u_int;
#ifndef __private_extern__
#define __private_extern__ extern
#endif
#endif
EOF

bison -y -d -o "${BUILD}/parser.c" --defines="${BUILD}/y.tab.h" "${SRC}/parser.y"
flex --header-file="${BUILD}/lexer.yy.h" -o "${BUILD}/lexer.yy.c" "${SRC}/lexxer.l"

CFLAGS=(
    -std=gnu11 -O2 -nostdinc -DKERNEL
    -DMIG_VERSION=\"bootstrap_cmds-138\"
    -I"${SRC}" -I"${BUILD}" -I"${H}"
    -I"${CROSSXNU_XNU}/osfmk"
    -I"${CROSSXNU_XNU}/bsd"
    -I"${CROSSXNU_XNU}/libkern"
    -I"${CROSSXNU_XNU}/EXTERNAL_HEADERS"
    -include "${H}/linux_compat.h"
)

HOST_CLANG="${CROSSXNU_REAL_HOST_CLANG:-/usr/bin/clang}"
for f in error.c global.c header.c mig.c routine.c server.c statement.c \
         string.c type.c user.c utils.c; do
    "${HOST_CLANG}" "${CFLAGS[@]}" -c -o "${BUILD}/${f%.c}.o" "${SRC}/${f}"
done
"${HOST_CLANG}" "${CFLAGS[@]}" -c -o "${BUILD}/parser.o" "${BUILD}/parser.c"
"${HOST_CLANG}" "${CFLAGS[@]}" -c -o "${BUILD}/lexer.o" "${BUILD}/lexer.yy.c"
"${HOST_CLANG}" -o "${BUILD}/migcom" "${BUILD}"/*.o

# The Apple driver hardcodes /usr/bin/arch; map it to uname -m.
# Normalise CRLF from Windows checkouts before installing the driver.
sed -e 's/\r$//' \
    -e 's#^arch=`/usr/bin/arch`#arch=$(uname -m); case "$arch" in aarch64) arch=arm64 ;; esac#' \
    "${SRC}/mig.sh" > "${BUILD}/mig"
chmod +x "${BUILD}/mig"

# Default path used by mig.sh: ../libexec/migcom relative to the script.
mkdir -p "${CROSSXNU_BUILD}/libexec"
ln -sf "${BUILD}/migcom" "${CROSSXNU_BUILD}/libexec/migcom"

echo "built MIG: ${BUILD}/mig"
"${BUILD}/migcom" -version
