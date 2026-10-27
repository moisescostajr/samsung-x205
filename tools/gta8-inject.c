/* Feed pointer and key events into phoc for the VNC server.
 *
 * The VNC side lives in Python, which cannot speak Wayland, so this is a
 * dumb executor: one text command per line on stdin, no replies.
 *
 *   m <x> <y>                 absolute motion, in the extents given in argv
 *   b <evdev-button> <0|1>    BTN_LEFT is 272
 *   a <axis> <value> <steps>  axis 0 is vertical, 1 horizontal
 *   k <evdev-key> <0|1>       keycode, i.e. the xkb keycode minus 8
 *   s <w> <h>                 new extents after a resolution change
 *   f                         end of event group; nothing is sent until this
 *
 * Absolute motion goes through zwlr_virtual_pointer, so the compositor maps
 * it onto the output itself and the panel's 270° rotation stays its problem.
 */
#define _POSIX_C_SOURCE 200809L

#include <fcntl.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include <wayland-client.h>

#include "virtual-keyboard-unstable-v1-client-protocol.h"
#include "wlr-virtual-pointer-unstable-v1-client-protocol.h"

#define WL_KEYBOARD_KEYMAP_FORMAT_XKB_V1 1
#define AXIS_SOURCE_WHEEL 0
/* Motion is sent as a fraction of this, so rotation math stays in doubles. */
#define UNIT 65535

static struct wl_seat *seat;
static struct wl_output *output;
static int32_t output_transform;
static struct zwlr_virtual_pointer_manager_v1 *pointer_manager;
static struct zwp_virtual_keyboard_manager_v1 *keyboard_manager;
static struct zwlr_virtual_pointer_v1 *pointer;
static struct zwp_virtual_keyboard_v1 *keyboard;

static uint32_t extent_w = 1920, extent_h = 1200;
static int pointer_dirty;

static uint32_t now_ms(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (uint32_t)(ts.tv_sec * 1000 + ts.tv_nsec / 1000000);
}

static void output_geometry(void *data, struct wl_output *wl_output, int32_t x, int32_t y,
			    int32_t pw, int32_t ph, int32_t subpixel, const char *make,
			    const char *model, int32_t transform)
{
	(void)data; (void)wl_output; (void)x; (void)y; (void)pw; (void)ph;
	(void)subpixel; (void)make; (void)model;
	output_transform = transform;
}

static void output_mode(void *data, struct wl_output *o, uint32_t f, int32_t w, int32_t h, int32_t r)
{
	(void)data; (void)o; (void)f; (void)w; (void)h; (void)r;
}

static void output_done(void *data, struct wl_output *o) { (void)data; (void)o; }

static void output_scale(void *data, struct wl_output *o, int32_t s)
{
	(void)data; (void)o; (void)s;
}

static void output_name(void *data, struct wl_output *o, const char *n)
{
	(void)data; (void)o; (void)n;
}

static void output_description(void *data, struct wl_output *o, const char *d)
{
	(void)data; (void)o; (void)d;
}

static const struct wl_output_listener output_listener = {
	.geometry = output_geometry,
	.mode = output_mode,
	.done = output_done,
	.scale = output_scale,
	.name = output_name,
	.description = output_description,
};

/* wlroots warps an absolute pointer with the *inverted* output transform, so
 * a 270° panel turns (x,y) into (y,1-x). Applying the forward transform here
 * cancels that out and the caller can keep thinking in screen pixels. */
static void pre_transform(double *x, double *y)
{
	double sx = *x, sy = *y;

	switch (output_transform) {
	case WL_OUTPUT_TRANSFORM_90:          *x = sy;       *y = 1.0 - sx; break;
	case WL_OUTPUT_TRANSFORM_180:         *x = 1.0 - sx; *y = 1.0 - sy; break;
	case WL_OUTPUT_TRANSFORM_270:         *x = 1.0 - sy; *y = sx;       break;
	case WL_OUTPUT_TRANSFORM_FLIPPED:     *x = 1.0 - sx; *y = sy;       break;
	case WL_OUTPUT_TRANSFORM_FLIPPED_90:  *x = sy;       *y = sx;       break;
	case WL_OUTPUT_TRANSFORM_FLIPPED_180: *x = sx;       *y = 1.0 - sy; break;
	case WL_OUTPUT_TRANSFORM_FLIPPED_270: *x = 1.0 - sy; *y = 1.0 - sx; break;
	default: break;
	}
}

static void handle_global(void *data, struct wl_registry *registry, uint32_t name,
			  const char *iface, uint32_t version)
{
	(void)data;
	if (!strcmp(iface, wl_seat_interface.name) && seat == NULL) {
		seat = wl_registry_bind(registry, name, &wl_seat_interface, 1);
	} else if (!strcmp(iface, wl_output_interface.name) && output == NULL) {
		output = wl_registry_bind(registry, name, &wl_output_interface,
					  version < 2 ? version : 2);
		wl_output_add_listener(output, &output_listener, NULL);
	} else if (!strcmp(iface, zwlr_virtual_pointer_manager_v1_interface.name)) {
		pointer_manager = wl_registry_bind(registry, name,
			&zwlr_virtual_pointer_manager_v1_interface, version < 2 ? version : 2);
	} else if (!strcmp(iface, zwp_virtual_keyboard_manager_v1_interface.name)) {
		keyboard_manager = wl_registry_bind(registry, name,
			&zwp_virtual_keyboard_manager_v1_interface, 1);
	}
}

static void handle_global_remove(void *data, struct wl_registry *registry, uint32_t name)
{
	(void)data; (void)registry; (void)name;
}

static const struct wl_registry_listener registry_listener = {
	.global = handle_global,
	.global_remove = handle_global_remove,
};

static int send_keymap(const char *path)
{
	int fd = open(path, O_RDONLY);
	if (fd < 0) {
		perror("open keymap");
		return -1;
	}
	struct stat st;
	if (fstat(fd, &st) < 0) {
		perror("stat keymap");
		close(fd);
		return -1;
	}
	zwp_virtual_keyboard_v1_keymap(keyboard, WL_KEYBOARD_KEYMAP_FORMAT_XKB_V1,
				       fd, (uint32_t)st.st_size);
	close(fd);
	return 0;
}

static void run_command(char *line)
{
	char verb = line[0];
	long a = 0, b = 0, c = 0;
	double v = 0;

	switch (verb) {
	case 'm': {
		if (sscanf(line + 1, "%ld %ld", &a, &b) != 2)
			return;
		if (a < 0) a = 0;
		if (b < 0) b = 0;
		double nx = (double)a / extent_w, ny = (double)b / extent_h;
		pre_transform(&nx, &ny);
		zwlr_virtual_pointer_v1_motion_absolute(pointer, now_ms(),
			(uint32_t)(nx * UNIT + 0.5), (uint32_t)(ny * UNIT + 0.5), UNIT, UNIT);
		pointer_dirty = 1;
		break;
	}
	case 'b':
		if (sscanf(line + 1, "%ld %ld", &a, &b) != 2)
			return;
		zwlr_virtual_pointer_v1_button(pointer, now_ms(), (uint32_t)a, (uint32_t)b);
		pointer_dirty = 1;
		break;
	case 'a':
		if (sscanf(line + 1, "%ld %lf %ld", &a, &v, &c) != 3)
			return;
		zwlr_virtual_pointer_v1_axis_source(pointer, AXIS_SOURCE_WHEEL);
		zwlr_virtual_pointer_v1_axis_discrete(pointer, now_ms(), (uint32_t)a,
			wl_fixed_from_double(v), (int32_t)c);
		pointer_dirty = 1;
		break;
	case 'k':
		if (sscanf(line + 1, "%ld %ld", &a, &b) != 2)
			return;
		zwp_virtual_keyboard_v1_key(keyboard, now_ms(), (uint32_t)a, (uint32_t)b);
		break;
	case 's':
		if (sscanf(line + 1, "%ld %ld", &a, &b) != 2 || a <= 0 || b <= 0)
			return;
		extent_w = (uint32_t)a;
		extent_h = (uint32_t)b;
		break;
	case 'f':
		if (pointer_dirty) {
			zwlr_virtual_pointer_v1_frame(pointer);
			pointer_dirty = 0;
		}
		break;
	default:
		break;
	}
}

int main(int argc, char **argv)
{
	if (argc < 2) {
		fprintf(stderr, "usage: %s <keymap-file> [width height]\n", argv[0]);
		return 2;
	}
	if (argc >= 4) {
		extent_w = (uint32_t)atoi(argv[2]);
		extent_h = (uint32_t)atoi(argv[3]);
	}

	struct wl_display *display = wl_display_connect(NULL);
	if (display == NULL) {
		fprintf(stderr, "cannot connect to WAYLAND_DISPLAY\n");
		return 1;
	}
	struct wl_registry *registry = wl_display_get_registry(display);
	wl_registry_add_listener(registry, &registry_listener, NULL);
	wl_display_roundtrip(display);
	wl_display_roundtrip(display);  /* second pass collects the output geometry */

	if (seat == NULL || pointer_manager == NULL || keyboard_manager == NULL) {
		fprintf(stderr, "compositor lacks seat/virtual-pointer/virtual-keyboard\n");
		return 1;
	}

	if (wl_proxy_get_version((struct wl_proxy *)pointer_manager) >= 2)
		pointer = zwlr_virtual_pointer_manager_v1_create_virtual_pointer_with_output(
			pointer_manager, seat, output);
	else
		pointer = zwlr_virtual_pointer_manager_v1_create_virtual_pointer(
			pointer_manager, seat);
	keyboard = zwp_virtual_keyboard_manager_v1_create_virtual_keyboard(
		keyboard_manager, seat);
	if (send_keymap(argv[1]) < 0)
		return 1;
	if (wl_display_roundtrip(display) < 0) {
		fprintf(stderr, "compositor rejected the virtual devices\n");
		return 1;
	}
	fprintf(stderr, "gta8-inject ready %ux%u transform=%d\n",
		extent_w, extent_h, output_transform);

	struct pollfd fds[2] = {
		{ .fd = STDIN_FILENO, .events = POLLIN },
		{ .fd = wl_display_get_fd(display), .events = POLLIN },
	};
	char buf[4096];
	size_t used = 0;

	for (;;) {
		wl_display_flush(display);
		if (poll(fds, 2, -1) < 0)
			break;
		if (fds[1].revents & POLLIN) {
			if (wl_display_dispatch(display) < 0) {
				fprintf(stderr, "wayland connection lost\n");
				break;
			}
		}
		if (fds[0].revents & (POLLIN | POLLHUP)) {
			ssize_t n = read(STDIN_FILENO, buf + used, sizeof(buf) - used - 1);
			if (n <= 0)
				break;
			used += (size_t)n;
			buf[used] = '\0';
			char *start = buf, *nl;
			while ((nl = strchr(start, '\n')) != NULL) {
				*nl = '\0';
				run_command(start);
				start = nl + 1;
			}
			used = strlen(start);
			memmove(buf, start, used + 1);
			if (used == sizeof(buf) - 1)
				used = 0;  /* oversized garbage line, drop it */
		}
	}

	wl_display_flush(display);
	wl_display_disconnect(display);
	return 0;
}
