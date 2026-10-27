/*
 * Why does Mali's Wayland client EGL refuse to initialize on phoc?
 *
 * eglinfo only prints "eglInitialize failed", which hides the error code.
 * This connects to the compositor and tries both the legacy and the platform
 * entry points, printing eglGetError() for each.
 *
 *   gcc -O0 -o mali-probe3 mali-probe3.c -lEGL -lwayland-client
 *   LD_LIBRARY_PATH=/opt/mali13 ./mali-probe3
 */
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <stdio.h>
#include <wayland-client.h>

static const char *egl_err(EGLint e)
{
	switch (e) {
	case EGL_SUCCESS: return "EGL_SUCCESS";
	case EGL_NOT_INITIALIZED: return "EGL_NOT_INITIALIZED";
	case EGL_BAD_ACCESS: return "EGL_BAD_ACCESS";
	case EGL_BAD_ALLOC: return "EGL_BAD_ALLOC";
	case EGL_BAD_ATTRIBUTE: return "EGL_BAD_ATTRIBUTE";
	case EGL_BAD_DISPLAY: return "EGL_BAD_DISPLAY";
	case EGL_BAD_PARAMETER: return "EGL_BAD_PARAMETER";
	case EGL_BAD_NATIVE_WINDOW: return "EGL_BAD_NATIVE_WINDOW";
	case EGL_BAD_NATIVE_PIXMAP: return "EGL_BAD_NATIVE_PIXMAP";
	default: return "?";
	}
}

static void try_init(const char *what, EGLDisplay dpy)
{
	EGLint major = 0, minor = 0;

	if (dpy == EGL_NO_DISPLAY) {
		printf("%-18s no display (0x%x %s)\n", what, eglGetError(),
		       egl_err(eglGetError()));
		return;
	}
	if (!eglInitialize(dpy, &major, &minor)) {
		EGLint e = eglGetError();

		printf("%-18s eglInitialize failed 0x%x %s\n", what, e,
		       egl_err(e));
		return;
	}
	printf("%-18s OK %d.%d vendor=%s\n", what, major, minor,
	       eglQueryString(dpy, EGL_VENDOR));
}

int main(void)
{
	struct wl_display *wl = wl_display_connect(NULL);

	if (!wl) {
		printf("cannot connect to compositor\n");
		return 1;
	}
	printf("connected to compositor\n");

	try_init("legacy", eglGetDisplay((EGLNativeDisplayType)wl));

	PFNEGLGETPLATFORMDISPLAYEXTPROC get_platform =
		(PFNEGLGETPLATFORMDISPLAYEXTPROC)
		eglGetProcAddress("eglGetPlatformDisplayEXT");

	if (get_platform) {
		try_init("platform_wayland",
			 get_platform(EGL_PLATFORM_WAYLAND_EXT, wl, NULL));
	} else {
		printf("platform_wayland   no eglGetPlatformDisplayEXT\n");
	}

	return 0;
}
