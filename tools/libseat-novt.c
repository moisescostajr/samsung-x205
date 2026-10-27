/* libseat stub for kernels with CONFIG_VT=n (Samsung Android 4.14).
 * wlroots/phoc wait for a seat "enable" event that seatd cannot emit
 * without /dev/tty0.  This backend opens DRM/input nodes directly. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

struct libseat;

struct libseat_seat_listener {
	void (*enable_seat)(struct libseat *seat, void *userdata);
	void (*disable_seat)(struct libseat *seat, void *userdata);
};

struct libseat {
	const struct libseat_seat_listener *listener;
	void *userdata;
	int dummy_fd;
	int next_id;
};

struct libseat *libseat_open_seat(const struct libseat_seat_listener *listener,
				  void *userdata)
{
	struct libseat *s = calloc(1, sizeof(*s));
	int fds[2];

	if (!s)
		return NULL;
	s->listener = listener;
	s->userdata = userdata;
	s->next_id = 1;
	if (pipe(fds) == 0) {
		s->dummy_fd = fds[0];
		close(fds[1]);
	} else {
		s->dummy_fd = dup(0);
	}
	if (listener && listener->enable_seat)
		listener->enable_seat(s, userdata);
	return s;
}

int libseat_close_seat(struct libseat *seat)
{
	if (!seat)
		return 0;
	if (seat->dummy_fd >= 0)
		close(seat->dummy_fd);
	free(seat);
	return 0;
}

int libseat_disable_seat(struct libseat *seat)
{
	(void)seat;
	return 0;
}

const char *libseat_seat_name(struct libseat *seat)
{
	(void)seat;
	return "seat0";
}

int libseat_open_device(struct libseat *seat, const char *path, int *fd)
{
	int f;

	if (!path || !fd)
		return -1;
	/* libinput assumes the seat hands back a non-blocking fd; without
	 * O_NONBLOCK its first evdev read never returns. */
	f = open(path, O_RDWR | O_NOCTTY | O_CLOEXEC | O_NONBLOCK);
	if (f < 0)
		f = open(path, O_RDONLY | O_NOCTTY | O_CLOEXEC | O_NONBLOCK);
	if (f < 0)
		return -1;
	*fd = f;
	return seat ? seat->next_id++ : 1;
}

int libseat_close_device(struct libseat *seat, int device_id)
{
	(void)seat;
	(void)device_id;
	return 0;
}

int libseat_get_fd(struct libseat *seat)
{
	return seat ? seat->dummy_fd : -1;
}

int libseat_dispatch(struct libseat *seat, int timeout)
{
	(void)seat;
	(void)timeout;
	return 0;
}

int libseat_switch_session(struct libseat *seat, int session)
{
	(void)seat;
	(void)session;
	errno = ENOSYS;
	return -1;
}

void libseat_set_log_handler(void *handler)
{
	(void)handler;
}

void libseat_set_log_level(int level)
{
	(void)level;
}
