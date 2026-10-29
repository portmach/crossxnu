#ifndef _CROSSXNU_COPYFILE_H_
#define _CROSSXNU_COPYFILE_H_

#include <sys/types.h>

#define COPYFILE_DATA 0x00000008

#ifdef __cplusplus
extern "C" {
#endif

int fcopyfile(int from_fd, int to_fd, void *state, int flags);

#ifdef __cplusplus
}
#endif

#endif /* _CROSSXNU_COPYFILE_H_ */
