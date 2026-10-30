#pragma once
#include <stdint.h>
#include <uuid/uuid.h>
struct aks_cred_s {
	uint64_t inode;
	uint32_t key_revision;
	int32_t  pid;
	uint32_t uid;
	uuid_t   volume_uuid;
};
struct aks_raw_key_s {
	void     *key;
	uint32_t  key_len;
	uint32_t  dp_class;
	uint32_t  flags;
	void     *iv_key;
	uint32_t  iv_key_len;
};
struct aks_wrapped_key_s {
	void     *key;
	uint32_t  key_len;
	uint32_t  dp_class;
	uint32_t  flags;
};
typedef struct aks_cred_s *aks_cred_t;
typedef struct aks_wrapped_key_s *aks_wrapped_key_t;
typedef struct aks_raw_key_s *aks_raw_key_t;
typedef uint32_t cp_key_class_t;
#define AKS_RAW_KEY_WRAPPEDKEY 0x1
