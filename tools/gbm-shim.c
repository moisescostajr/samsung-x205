/*
 * Glue that lets wlroots drive the Mali r13p0 blob on gta8wifi.
 *
 * Two gaps, both preloaded into phoc only:
 *
 * 1. gbm_bo_get_fd_for_plane(). The blob exports the Mesa ~19 era GBM ABI;
 *    wlroots 0.16 also links this (Mesa 21.1+). Everything scanned out here
 *    is single plane, so plane 0 is just gbm_bo_get_fd().
 *
 * 2. EGL_EXT_device_query. wlroots asks EGL which DRM device the renderer
 *    uses, and without an answer it disables linux-dmabuf entirely:
 *      "Failed to get DRM FD from renderer"
 *    Clients then cannot hand GPU buffers to the compositor, so every app is
 *    stuck on wl_shm. The blob has no device query, but there is only one
 *    DRM device on this tablet, so report it.
 *
 *   gcc -shared -fPIC -o libgbm-shim.so gbm-shim.c -L/opt/mali13 -lgbm -lEGL -ldl
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>

#include <EGL/egl.h>
#include <EGL/eglext.h>

#ifndef EGL_DRM_DEVICE_FILE_EXT
#define EGL_DRM_DEVICE_FILE_EXT 0x3233
#endif
#ifndef EGL_DRM_RENDER_NODE_FILE_EXT
#define EGL_DRM_RENDER_NODE_FILE_EXT 0x3377
#endif
#ifndef EGL_DEVICE_EXT
#define EGL_DEVICE_EXT 0x322C
#endif

#define DRM_NODE "/dev/dri/card0"

/* The blob has no EGLDeviceEXT; wlroots only passes it back to us. */
static int fake_device;

struct gbm_bo;
extern int gbm_bo_get_fd(struct gbm_bo *bo);

int gbm_bo_get_fd_for_plane(struct gbm_bo *bo, int plane)
{
	if (plane != 0)
		return -EINVAL;

	return gbm_bo_get_fd(bo);
}

static EGLBoolean query_display_attrib(EGLDisplay dpy, EGLint attribute,
				       EGLAttrib *value)
{
	(void)dpy;
	if (attribute != EGL_DEVICE_EXT)
		return EGL_FALSE;

	*value = (EGLAttrib)(intptr_t)&fake_device;

	return EGL_TRUE;
}

static const char *query_device_string(EGLDeviceEXT device, EGLint name)
{
	(void)device;
	switch (name) {
	case EGL_DRM_DEVICE_FILE_EXT:
	/*
	 * sprd is display-only and has no render node, but wlroots only
	 * advertises a device to clients over wl_drm when it can name one,
	 * and Mali's Wayland EGL gives up without it. Hand out the primary
	 * node for both.
	 */
	case EGL_DRM_RENDER_NODE_FILE_EXT:
		return DRM_NODE;
	case EGL_EXTENSIONS:
		return "EGL_EXT_device_drm EGL_EXT_device_drm_render_node";
	default:
		return NULL;
	}
}

static EGLBoolean query_devices(EGLint max, EGLDeviceEXT *devices,
				EGLint *num_devices)
{
	if (num_devices)
		*num_devices = 1;
	if (devices && max >= 1)
		devices[0] = (EGLDeviceEXT)&fake_device;

	return EGL_TRUE;
}

/* Advertise the device extensions alongside whatever the blob reports. */
const char *eglQueryString(EGLDisplay dpy, EGLint name)
{
	static const char *(*real)(EGLDisplay, EGLint);
	static char *patched;

	if (!real)
		real = dlsym(RTLD_NEXT, "eglQueryString");

	const char *base = real ? real(dpy, name) : NULL;

	if (dpy != EGL_NO_DISPLAY || name != EGL_EXTENSIONS || !base)
		return base;

	if (!patched) {
		static const char *add =
			" EGL_EXT_device_base EGL_EXT_device_query"
			" EGL_EXT_device_enumeration EGL_EXT_device_drm"
			" EGL_EXT_device_drm_render_node";
		size_t len = strlen(base) + strlen(add) + 1;

		patched = malloc(len);
		if (!patched)
			return base;
		strcpy(patched, base);
		strcat(patched, add);
	}

	return patched;
}

void (*eglGetProcAddress(const char *name))(void)
{
	static void (*(*real)(const char *))(void);

	if (!real)
		real = dlsym(RTLD_NEXT, "eglGetProcAddress");

	if (name) {
		if (!strcmp(name, "eglQueryDisplayAttribEXT") ||
		    !strcmp(name, "eglQueryDisplayAttribKHR"))
			return (void (*)(void))query_display_attrib;
		if (!strcmp(name, "eglQueryDeviceStringEXT"))
			return (void (*)(void))query_device_string;
		if (!strcmp(name, "eglQueryDevicesEXT"))
			return (void (*)(void))query_devices;
	}

	return real ? real(name) : NULL;
}

/* Some callers link these directly rather than going through eglGetProcAddress. */
EGLBoolean eglQueryDisplayAttribEXT(EGLDisplay dpy, EGLint attribute,
				    EGLAttrib *value)
{
	return query_display_attrib(dpy, attribute, value);
}

const char *eglQueryDeviceStringEXT(EGLDeviceEXT device, EGLint name)
{
	return query_device_string(device, name);
}

EGLBoolean eglQueryDevicesEXT(EGLint max, EGLDeviceEXT *devices,
			      EGLint *num_devices)
{
	return query_devices(max, devices, num_devices);
}
