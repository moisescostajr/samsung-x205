/* LD_PRELOAD: ignore EVIOCGRAB so RetroArch cannot steal the pad. No libc. */
#define EVIOCGRAB 0x40044590u
#define SYS_ioctl 29

int ioctl(int fd, unsigned long request, void *arg)
{
    if (request == EVIOCGRAB)
        return 0;
    register long x8 __asm__("x8") = SYS_ioctl;
    register long x0 __asm__("x0") = fd;
    register long x1 __asm__("x1") = (long)request;
    register long x2 __asm__("x2") = (long)arg;
    __asm__ volatile("svc #0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2) : "memory", "cc");
    return (int)x0;
}
