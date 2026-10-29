#ifndef _CROSSXNU_LIBC_H_
#define _CROSSXNU_LIBC_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

#ifndef TRUE
#define TRUE 1
#define FALSE 0
#endif

typedef int boolean_t;
typedef unsigned long vm_offset_t;
typedef unsigned long vm_size_t;


#ifdef __cplusplus
extern "C" {
#endif

const char *getprogname(void);
void setprogname(const char *);
void *setmode(const char *mode_str);
mode_t getmode(const void *set, mode_t mode);

#ifdef __cplusplus
}
#endif

#endif /* _CROSSXNU_LIBC_H_ */
