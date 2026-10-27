/* Does this kernel export GEM buffers over PRIME?
 *
 * Creates a dumb buffer, exports it to a dma-buf fd, imports it back on a
 * second open of the same card, and mmaps the dma-buf. Before the sprd_drm.c
 * fix, the export returned -ENOSYS and wlroots could not scan out.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <xf86drm.h>
#include <xf86drmMode.h>

int main(void)
{
	struct drm_mode_create_dumb creq;
	uint32_t handle2 = 0;
	int fd, fd2, dmabuf = -1, rc;
	void *map;

	fd = open("/dev/dri/card0", O_RDWR | O_CLOEXEC);
	fd2 = open("/dev/dri/card0", O_RDWR | O_CLOEXEC);
	if (fd < 0 || fd2 < 0) {
		printf("open failed errno=%d\n", errno);
		return 1;
	}

	memset(&creq, 0, sizeof(creq));
	creq.width = 256;
	creq.height = 256;
	creq.bpp = 32;
	rc = drmIoctl(fd, DRM_IOCTL_MODE_CREATE_DUMB, &creq);
	printf("CREATE_DUMB rc=%d handle=%u size=%llu\n", rc, creq.handle,
	       (unsigned long long)creq.size);
	if (rc)
		return 1;

	errno = 0;
	rc = drmPrimeHandleToFD(fd, creq.handle, DRM_CLOEXEC | DRM_RDWR, &dmabuf);
	printf("EXPORT   rc=%d errno=%d dmabuf=%d%s\n", rc, errno, dmabuf,
	       rc ? "  <-- PRIME export missing" : "");
	if (rc)
		return 1;

	errno = 0;
	rc = drmPrimeFDToHandle(fd2, dmabuf, &handle2);
	printf("IMPORT   rc=%d errno=%d handle=%u\n", rc, errno, handle2);

	map = mmap(NULL, creq.size, PROT_READ | PROT_WRITE, MAP_SHARED, dmabuf, 0);
	printf("DMABUF MMAP %s errno=%d\n", map == MAP_FAILED ? "FAILED" : "ok",
	       errno);
	if (map != MAP_FAILED) {
		memset(map, 0xAA, 4096);
		munmap(map, creq.size);
	}

	printf("RESULT %s\n", rc == 0 ? "PRIME_OK" : "PRIME_PARTIAL");
	return 0;
}
