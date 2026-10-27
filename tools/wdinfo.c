/*
 * Watchdog survey for gta8wifi: find every watchdog the kernel exposes, try to
 * disable it properly via ioctl, and keep a real keepalive on whatever refuses
 * to be disabled.  Everything is reported to ttyGS0 because the tablet may
 * reset before any filesystem write is flushed.
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/watchdog.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

#define MAX_WD 8

static int serial_fd = -1;

static void say(const char *fmt, ...)
{
    char buf[512];
    va_list ap;
    int n;

    va_start(ap, fmt);
    n = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    if (n < 0)
        return;
    if ((size_t)n >= sizeof(buf))
        n = sizeof(buf) - 1;
    (void)write(1, buf, n);
    if (serial_fd >= 0)
        (void)write(serial_fd, buf, n);
}

static void cat(const char *path, const char *label)
{
    char buf[256];
    int fd = open(path, O_RDONLY);
    ssize_t n;

    if (fd < 0) {
        say("%s: open errno=%d\n", label, errno);
        return;
    }
    n = read(fd, buf, sizeof(buf) - 1);
    close(fd);
    if (n <= 0) {
        say("%s: read errno=%d\n", label, errno);
        return;
    }
    buf[n] = 0;
    for (ssize_t i = 0; i < n; i++)
        if (buf[i] == '\n')
            buf[i] = ' ';
    say("%s: %s\n", label, buf);
}

static double uptime_now(void)
{
    char buf[64];
    int fd = open("/proc/uptime", O_RDONLY);
    ssize_t n;
    double up = -1;

    if (fd < 0)
        return -1;
    n = read(fd, buf, sizeof(buf) - 1);
    close(fd);
    if (n <= 0)
        return -1;
    buf[n] = 0;
    sscanf(buf, "%lf", &up);
    return up;
}

int main(void)
{
    int fds[MAX_WD];
    int nfd = 0;

    serial_fd = open("/dev/ttyGS0", O_WRONLY | O_NONBLOCK | O_CLOEXEC);
    say("wdinfo start uptime=%.1f\n", uptime_now());

    cat("/proc/cmdline", "cmdline");
    cat("/sys/bus/platform/drivers/sprd-wdt-fiq/uevent", "wdt-fiq-drv");

    DIR *d = opendir("/sys/class/watchdog");
    if (!d) {
        say("no /sys/class/watchdog errno=%d\n", errno);
    } else {
        struct dirent *e;
        while ((e = readdir(d)) != NULL) {
            char path[256], label[128];
            int major = 0, minor = 0;
            char devbuf[64];
            int fd;
            ssize_t n;

            if (e->d_name[0] == '.')
                continue;

            snprintf(label, sizeof(label), "wd %s state", e->d_name);
            snprintf(path, sizeof(path), "/sys/class/watchdog/%s/state", e->d_name);
            cat(path, label);

            snprintf(label, sizeof(label), "wd %s timeout", e->d_name);
            snprintf(path, sizeof(path), "/sys/class/watchdog/%s/timeout", e->d_name);
            cat(path, label);

            snprintf(path, sizeof(path), "/sys/class/watchdog/%s/dev", e->d_name);
            fd = open(path, O_RDONLY);
            if (fd < 0)
                continue;
            n = read(fd, devbuf, sizeof(devbuf) - 1);
            close(fd);
            if (n <= 0)
                continue;
            devbuf[n] = 0;
            if (sscanf(devbuf, "%d:%d", &major, &minor) != 2)
                continue;
            say("wd %s dev=%d:%d\n", e->d_name, major, minor);

            snprintf(path, sizeof(path), "/dev/%s", e->d_name);
            unlink(path);
            if (mknod(path, S_IFCHR | 0600, makedev(major, minor)) != 0 && errno != EEXIST) {
                say("mknod %s errno=%d\n", path, errno);
                continue;
            }

            fd = open(path, O_RDWR | O_CLOEXEC);
            if (fd < 0) {
                say("open %s errno=%d\n", path, errno);
                continue;
            }

            struct watchdog_info info;
            memset(&info, 0, sizeof(info));
            if (ioctl(fd, WDIOC_GETSUPPORT, &info) == 0)
                say("wd %s id=%.32s options=0x%x\n",
                    e->d_name, info.identity, info.options);
            else
                say("wd %s GETSUPPORT errno=%d\n", e->d_name, errno);

            int timeout = 0;
            if (ioctl(fd, WDIOC_GETTIMEOUT, &timeout) == 0)
                say("wd %s timeout_ioctl=%d\n", e->d_name, timeout);

            int opt = WDIOS_DISABLECARD;
            if (ioctl(fd, WDIOC_SETOPTIONS, &opt) == 0)
                say("wd %s DISABLECARD ok\n", e->d_name);
            else
                say("wd %s DISABLECARD errno=%d\n", e->d_name, errno);

            /* Hold the fd open: closing without magic-close can arm nowayout. */
            if (nfd < MAX_WD)
                fds[nfd++] = fd;
        }
        closedir(d);
    }

    say("wdinfo held=%d\n", nfd);

    for (unsigned int tick = 0;; tick++) {
        for (int i = 0; i < nfd; i++)
            (void)ioctl(fds[i], WDIOC_KEEPALIVE, 0);
        say("alive uptime=%.1f tick=%u\n", uptime_now(), tick);
        sleep(5);
    }
}
