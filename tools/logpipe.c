/*
 * Forward a growing log file to ttyGS0 without ever blocking the writer.
 * The ACM gadget stalls under load, so writes are non-blocking and the read
 * offset only advances by bytes actually accepted by the port.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv)
{
    const char *path = argc > 1 ? argv[1] : "/root/hw-up.log";
    off_t off = 0;
    int tty = -1;

    while (tty < 0) {
        tty = open("/dev/ttyGS0", O_WRONLY | O_NONBLOCK | O_CLOEXEC);
        if (tty < 0)
            sleep(1);
    }

    for (;;) {
        int fd = open(path, O_RDONLY | O_CLOEXEC);

        if (fd >= 0) {
            char buf[256];
            ssize_t n;

            if (lseek(fd, off, SEEK_SET) == off) {
                while ((n = read(fd, buf, sizeof(buf))) > 0) {
                    ssize_t done = 0;

                    while (done < n) {
                        ssize_t w = write(tty, buf + done, n - done);

                        if (w > 0) {
                            done += w;
                            continue;
                        }
                        if (errno == EAGAIN || errno == EWOULDBLOCK) {
                            usleep(20000);
                            continue;
                        }
                        break;
                    }
                    off += done;
                    if (done < n)
                        break;
                }
            }
            close(fd);
        }
        usleep(400000);
    }
}
