/*
 * Headless check that the Mali blob can actually render on gta8wifi.
 *
 * eglinfo reports zero GBM configs, which can mean either that libmali never
 * opened a DRM device or that it opened one it cannot render on. This walks
 * the steps by hand and prints where it stops: GBM device, EGL display,
 * config count, context, then GL_RENDERER.
 *
 * Build on the tablet:
 *   gcc -O0 -o mali-probe mali-probe.c -lEGL -lGLESv2 -lgbm -ldrm
 * Run against the blob:
 *   LD_LIBRARY_PATH=/opt/mali ./mali-probe /dev/dri/card0
 */
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
#include <fcntl.h>
#include <gbm.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static void show_strings(void)
{
	printf("GL_VENDOR   : %s\n", glGetString(GL_VENDOR));
	printf("GL_RENDERER : %s\n", glGetString(GL_RENDERER));
	printf("GL_VERSION  : %s\n", glGetString(GL_VERSION));
}

int main(int argc, char **argv)
{
	const char *node = argc > 1 ? argv[1] : "/dev/dri/card0";
	EGLint major = 0, minor = 0, nconfig = 0;
	EGLDisplay dpy = EGL_NO_DISPLAY;
	struct gbm_device *gbm = NULL;
	int fd = -1;

	static const EGLint cfg_attr[] = {
		EGL_SURFACE_TYPE, EGL_WINDOW_BIT,
		EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT,
		EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8,
		EGL_NONE
	};
	static const EGLint ctx_attr[] = {
		EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE
	};

	fd = open(node, O_RDWR | O_CLOEXEC);
	if (fd < 0) {
		printf("FAIL open(%s)\n", node);
		return 1;
	}
	printf("OK   open %s fd=%d\n", node, fd);

	gbm = gbm_create_device(fd);
	if (!gbm) {
		printf("FAIL gbm_create_device\n");
		return 1;
	}
	printf("OK   gbm_create_device backend=%s\n", gbm_device_get_backend_name(gbm));

	/* The wayland-gbm build assumes a Wayland display in the legacy
	 * eglGetDisplay() path, so ask for the GBM platform explicitly the
	 * way wlroots does. */
	PFNEGLGETPLATFORMDISPLAYEXTPROC get_platform_display =
		(PFNEGLGETPLATFORMDISPLAYEXTPROC)
		eglGetProcAddress("eglGetPlatformDisplayEXT");

	if (get_platform_display) {
		dpy = get_platform_display(EGL_PLATFORM_GBM_KHR, gbm, NULL);
		printf("%s eglGetPlatformDisplayEXT(GBM)\n",
		       dpy == EGL_NO_DISPLAY ? "FAIL" : "OK  ");
	}
	if (dpy == EGL_NO_DISPLAY) {
		dpy = eglGetDisplay((EGLNativeDisplayType)gbm);
		printf("%s eglGetDisplay fallback\n",
		       dpy == EGL_NO_DISPLAY ? "FAIL" : "OK  ");
	}
	if (dpy == EGL_NO_DISPLAY)
		return 1;
	if (!eglInitialize(dpy, &major, &minor)) {
		printf("FAIL eglInitialize 0x%x\n", eglGetError());
		return 1;
	}
	printf("OK   eglInitialize %d.%d vendor=%s\n", major, minor,
	       eglQueryString(dpy, EGL_VENDOR));

	eglBindAPI(EGL_OPENGL_ES_API);

	EGLConfig cfg;
	if (!eglChooseConfig(dpy, cfg_attr, &cfg, 1, &nconfig) || nconfig < 1) {
		printf("FAIL eglChooseConfig window nconfig=%d err=0x%x\n",
		       nconfig, eglGetError());

		/* Retry without a surface type: enough for offscreen rendering. */
		static const EGLint pbuf_attr[] = {
			EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT, EGL_NONE
		};
		if (!eglChooseConfig(dpy, pbuf_attr, &cfg, 1, &nconfig) || nconfig < 1) {
			printf("FAIL eglChooseConfig any nconfig=%d err=0x%x\n",
			       nconfig, eglGetError());

			/* Last resort: no config at all (EGL_KHR_no_config_context). */
			EGLContext nc = eglCreateContext(dpy, EGL_NO_CONFIG_KHR,
							 EGL_NO_CONTEXT, ctx_attr);
			if (nc == EGL_NO_CONTEXT) {
				printf("FAIL eglCreateContext(no_config) 0x%x\n",
				       eglGetError());
				return 1;
			}
			if (!eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, nc)) {
				printf("FAIL eglMakeCurrent(no_config) 0x%x\n",
				       eglGetError());
				return 1;
			}
			printf("OK   context via EGL_KHR_no_config_context\n");
			show_strings();
			return 0;
		}
	}
	printf("OK   eglChooseConfig nconfig=%d\n", nconfig);

	EGLContext ctx = eglCreateContext(dpy, cfg, EGL_NO_CONTEXT, ctx_attr);
	if (ctx == EGL_NO_CONTEXT) {
		printf("FAIL eglCreateContext 0x%x\n", eglGetError());
		return 1;
	}
	if (!eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, ctx)) {
		printf("FAIL eglMakeCurrent 0x%x\n", eglGetError());
		return 1;
	}
	printf("OK   context current\n");
	show_strings();

	/* wlroots refuses to use a GLES2 renderer without these. */
	static const char *egl_need[] = {
		"EGL_KHR_image_base", "EGL_EXT_image_dma_buf_import",
		"EGL_EXT_image_dma_buf_import_modifiers",
		"EGL_KHR_surfaceless_context", "EGL_KHR_no_config_context",
		"EGL_MESA_configless_context", "EGL_WL_bind_wayland_display",
		"EGL_KHR_swap_buffers_with_damage",
		"EGL_EXT_swap_buffers_with_damage",
		"EGL_IMG_context_priority", NULL
	};
	static const char *gl_need[] = {
		"GL_OES_EGL_image", "GL_OES_EGL_image_external",
		"GL_EXT_texture_format_BGRA8888", "GL_OES_rgb8_rgba8",
		"GL_EXT_unpack_subimage", "GL_KHR_debug", NULL
	};

	const char *egl_ext = eglQueryString(dpy, EGL_EXTENSIONS);
	const char *gl_ext = (const char *)glGetString(GL_EXTENSIONS);

	printf("\nEGL display extensions wlroots looks for:\n");
	for (int i = 0; egl_need[i]; i++)
		printf("  %-42s %s\n", egl_need[i],
		       (egl_ext && strstr(egl_ext, egl_need[i])) ? "yes" : "NO");

	printf("GLES extensions wlroots looks for:\n");
	for (int i = 0; gl_need[i]; i++)
		printf("  %-42s %s\n", gl_need[i],
		       (gl_ext && strstr(gl_ext, gl_need[i])) ? "yes" : "NO");

	return 0;
}
