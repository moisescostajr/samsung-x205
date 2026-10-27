/*
 * Does the Mali blob render at all on gta8wifi, ignoring GBM?
 *
 * libmali's bundled gbm_create_device() rejects the sprd display driver, so
 * this skips the GBM platform and asks for EGL_DEFAULT_DISPLAY plus a
 * config-less context (EGL_KHR_no_config_context, which the blob advertises).
 * If GL_RENDERER comes back as a Mali string, kbase and the blob are fine and
 * only the window-system glue is missing.
 *
 *   gcc -O0 -o mali-probe2 mali-probe2.c -lEGL -lGLESv2
 *   LD_LIBRARY_PATH=/opt/mali ./mali-probe2
 */
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
#include <stdio.h>

int main(void)
{
	EGLint major = 0, minor = 0;
	EGLDisplay dpy;

	static const EGLint ctx_attr[] = {
		EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE
	};

	dpy = eglGetDisplay(EGL_DEFAULT_DISPLAY);
	if (dpy == EGL_NO_DISPLAY) {
		printf("FAIL eglGetDisplay(EGL_DEFAULT_DISPLAY)\n");
		return 1;
	}
	if (!eglInitialize(dpy, &major, &minor)) {
		printf("FAIL eglInitialize 0x%x\n", eglGetError());
		return 1;
	}
	printf("OK   eglInitialize %d.%d vendor=%s version=%s\n", major, minor,
	       eglQueryString(dpy, EGL_VENDOR), eglQueryString(dpy, EGL_VERSION));

	eglBindAPI(EGL_OPENGL_ES_API);

	EGLContext ctx = eglCreateContext(dpy, EGL_NO_CONFIG_KHR, EGL_NO_CONTEXT,
					  ctx_attr);
	if (ctx == EGL_NO_CONTEXT) {
		printf("FAIL eglCreateContext(no_config) 0x%x\n", eglGetError());
		return 1;
	}
	if (!eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, ctx)) {
		printf("FAIL eglMakeCurrent 0x%x\n", eglGetError());
		return 1;
	}
	printf("OK   context current\n");
	printf("GL_VENDOR   : %s\n", glGetString(GL_VENDOR));
	printf("GL_RENDERER : %s\n", glGetString(GL_RENDERER));
	printf("GL_VERSION  : %s\n", glGetString(GL_VERSION));

	/* Touch the GPU for real: clear a small FBO and read it back. */
	GLuint tex = 0, fbo = 0;
	glGenTextures(1, &tex);
	glBindTexture(GL_TEXTURE_2D, tex);
	glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 64, 64, 0, GL_RGBA,
		     GL_UNSIGNED_BYTE, NULL);
	glGenFramebuffers(1, &fbo);
	glBindFramebuffer(GL_FRAMEBUFFER, fbo);
	glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
			       GL_TEXTURE_2D, tex, 0);
	if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
		printf("FAIL fbo incomplete\n");
		return 1;
	}
	glViewport(0, 0, 64, 64);
	glClearColor(0.0f, 1.0f, 0.0f, 1.0f);
	glClear(GL_COLOR_BUFFER_BIT);
	glFinish();

	unsigned char px[4] = { 0, 0, 0, 0 };
	glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
	printf("render test pixel = %u,%u,%u,%u (want 0,255,0,255)\n",
	       px[0], px[1], px[2], px[3]);
	printf("%s\n", (px[1] > 200 && px[0] < 50) ? "GPU_RENDER_OK" : "GPU_RENDER_BAD");

	return 0;
}
