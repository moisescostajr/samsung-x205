/*
 * Print the DRM capabilities libmali's gbm_create_device() cares about.
 *
 * It bails out immediately after DRM_IOCTL_GET_CAP on our sprd display node,
 * and the usual reason is PRIME: the v57 kernel patch added dma-buf export
 * but an allocator also needs import.
 *
 *   gcc -O0 -o drm-caps drm-caps.c -ldrm -I/usr/include/libdrm
 */
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <xf86drm.h>
#include <xf86drmMode.h>

static void cap(int fd, const char *name, uint64_t id)
{
	uint64_t value = 0;
	int ret = drmGetCap(fd, id, &value);

	if (ret)
		printf("  %-28s unsupported (%d)\n", name, ret);
	else
		printf("  %-28s %llu\n", name, (unsigned long long)value);
}

int main(int argc, char **argv)
{
	const char *node = argc > 1 ? argv[1] : "/dev/dri/card0";
	int fd = open(node, O_RDWR | O_CLOEXEC);

	if (fd < 0) {
		printf("cannot open %s\n", node);
		return 1;
	}

	drmVersionPtr v = drmGetVersion(fd);
	if (v) {
		printf("driver: %s %d.%d.%d  desc: %s\n", v->name, v->version_major,
		       v->version_minor, v->version_patchlevel, v->desc);
		drmFreeVersion(v);
	}

	printf("caps:\n");
	cap(fd, "DRM_CAP_DUMB_BUFFER", DRM_CAP_DUMB_BUFFER);
	cap(fd, "DRM_CAP_PRIME", DRM_CAP_PRIME);
	cap(fd, "DRM_CAP_ADDFB2_MODIFIERS", DRM_CAP_ADDFB2_MODIFIERS);
	cap(fd, "DRM_CAP_TIMESTAMP_MONOTONIC", DRM_CAP_TIMESTAMP_MONOTONIC);
	cap(fd, "DRM_CAP_ASYNC_PAGE_FLIP", DRM_CAP_ASYNC_PAGE_FLIP);
	printf("  (DRM_PRIME_CAP_IMPORT=1, DRM_PRIME_CAP_EXPORT=2, both=3)\n");

	/* Can we even make a dumb buffer and export it? */
	struct drm_mode_create_dumb creq;
	memset(&creq, 0, sizeof(creq));
	creq.width = 64;
	creq.height = 64;
	creq.bpp = 32;
	if (drmIoctl(fd, DRM_IOCTL_MODE_CREATE_DUMB, &creq)) {
		printf("create_dumb: FAILED\n");
		return 0;
	}
	printf("create_dumb: handle=%u pitch=%u size=%llu\n", creq.handle,
	       creq.pitch, (unsigned long long)creq.size);

	int dmafd = -1;
	if (drmPrimeHandleToFD(fd, creq.handle, DRM_CLOEXEC, &dmafd))
		printf("prime export: FAILED\n");
	else
		printf("prime export: OK fd=%d\n", dmafd);

	if (dmafd >= 0) {
		uint32_t handle = 0;
		if (drmPrimeFDToHandle(fd, dmafd, &handle))
			printf("prime import: FAILED\n");
		else
			printf("prime import: OK handle=%u\n", handle);
	}

	return 0;
}
