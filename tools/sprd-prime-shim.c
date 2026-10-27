/* PRIME bridge for the SPRD 4.14 DRM driver.
 *
 * wlroots allocates a dumb buffer on one DRM fd and then imports it into the
 * backend's fd with drmPrimeHandleToFD + drmPrimeFDToHandle.  This kernel has
 * no PRIME, so the import fails and the output is never enabled.  Both fds are
 * opens of the same device, so legacy GEM flink/open can carry the handle
 * across instead: export returns a placeholder fd that remembers the flink
 * name, and import turns that name back into a handle on the target fd.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <drm/drm.h>
#include <drm/drm_mode.h>

#define MAX_ENT 128

struct ent {
	int fake_fd;
	uint32_t name;
	uint64_t map_offset;
};

static struct ent ents[MAX_ENT];
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static void *(*real_mmap)(void *, size_t, int, int, int, off_t);
static int (*real_close)(int);

static void resolve(void)
{
	if (!real_mmap)
		real_mmap = dlsym(RTLD_NEXT, "mmap");
	if (!real_close)
		real_close = dlsym(RTLD_NEXT, "close");
}

int drmPrimeHandleToFD(int fd, uint32_t handle, uint32_t flags, int *prime_fd)
{
	struct drm_gem_flink flink;
	struct drm_mode_map_dumb map;
	int fake, i;

	(void)flags;
	if (!prime_fd) {
		errno = EINVAL;
		return -1;
	}

	memset(&flink, 0, sizeof(flink));
	flink.handle = handle;
	if (ioctl(fd, DRM_IOCTL_GEM_FLINK, &flink) != 0)
		return -1;

	/* Keep the dumb mapping offset so mmap() on the placeholder works. */
	memset(&map, 0, sizeof(map));
	map.handle = handle;
	if (ioctl(fd, DRM_IOCTL_MODE_MAP_DUMB, &map) != 0)
		map.offset = 0;

	fake = dup(fd);
	if (fake < 0)
		return -1;

	pthread_mutex_lock(&lock);
	for (i = 0; i < MAX_ENT; i++) {
		if (ents[i].fake_fd == 0) {
			ents[i].fake_fd = fake;
			ents[i].name = flink.name;
			ents[i].map_offset = map.offset;
			break;
		}
	}
	pthread_mutex_unlock(&lock);
	if (i == MAX_ENT) {
		close(fake);
		errno = ENOMEM;
		return -1;
	}

	*prime_fd = fake;
	return 0;
}

int drmPrimeFDToHandle(int fd, int prime_fd, uint32_t *handle)
{
	struct drm_gem_open op;
	uint32_t name = 0;
	int i;

	if (!handle) {
		errno = EINVAL;
		return -1;
	}

	pthread_mutex_lock(&lock);
	for (i = 0; i < MAX_ENT; i++) {
		if (ents[i].fake_fd == prime_fd) {
			name = ents[i].name;
			break;
		}
	}
	pthread_mutex_unlock(&lock);

	if (!name) {
		errno = EINVAL;
		return -1;
	}

	memset(&op, 0, sizeof(op));
	op.name = name;
	if (ioctl(fd, DRM_IOCTL_GEM_OPEN, &op) != 0)
		return -1;

	*handle = op.handle;
	return 0;
}

void *mmap(void *addr, size_t length, int prot, int flags, int fd, off_t offset)
{
	int i;

	resolve();
	pthread_mutex_lock(&lock);
	for (i = 0; i < MAX_ENT; i++) {
		if (ents[i].fake_fd == fd && ents[i].map_offset) {
			offset = (off_t)ents[i].map_offset;
			break;
		}
	}
	pthread_mutex_unlock(&lock);
	return real_mmap(addr, length, prot, flags, fd, offset);
}

int close(int fd)
{
	int i;

	resolve();
	pthread_mutex_lock(&lock);
	for (i = 0; i < MAX_ENT; i++) {
		if (ents[i].fake_fd == fd) {
			ents[i].fake_fd = 0;
			ents[i].name = 0;
			ents[i].map_offset = 0;
			break;
		}
	}
	pthread_mutex_unlock(&lock);
	return real_close(fd);
}
