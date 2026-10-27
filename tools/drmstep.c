/* Step-logged SPRD DRM bring-up. fsync after every ioctl so a hang still leaves a log. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/dma-buf.h>
#include <drm_fourcc.h>
#include <xf86drm.h>
#include <xf86drmMode.h>

static volatile int timed_out;
static volatile int flip_done;
static int serial_fd = -1;

static void on_alrm(int sig)
{
    (void)sig;
    timed_out = 1;
}

static void on_page_flip(int fd, unsigned int frame, unsigned int sec,
                         unsigned int usec, void *data)
{
    (void)fd;
    (void)frame;
    (void)sec;
    (void)usec;
    (void)data;
    flip_done = 1;
}

static void log_msg(const char *fmt, ...)
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
    (void)fsync(1);
    if (serial_fd >= 0)
        (void)write(serial_fd, buf, n);
}

#define LOG(...) log_msg(__VA_ARGS__)

static void backlight(void)
{
    int bl = open("/sys/class/backlight/sprd_backlight/brightness", O_WRONLY);
    if (bl >= 0) {
        (void)write(bl, "80\n", 3);
        close(bl);
    }
}

static void read_sysfs(const char *path, char *out, size_t outsz)
{
    int fd = open(path, O_RDONLY);
    ssize_t n;

    out[0] = '?';
    out[1] = 0;
    if (fd < 0)
        return;
    n = read(fd, out, outsz - 1);
    close(fd);
    if (n <= 0) {
        out[0] = '?';
        out[1] = 0;
        return;
    }
    out[n] = 0;
    for (ssize_t i = 0; i < n; i++)
        if (out[i] == '\n')
            out[i] = 0;
}

static void flush_dcache(void *p, size_t n)
{
    uintptr_t start = (uintptr_t)p & ~(uintptr_t)63;
    uintptr_t end = ((uintptr_t)p + n + 63) & ~(uintptr_t)63;
    for (uintptr_t a = start; a < end; a += 64)
        asm volatile("dc civac, %0" :: "r"(a) : "memory");
    asm volatile("dsb sy" ::: "memory");
}

static void fill32(void *map, uint32_t h, uint32_t pitch, uint32_t color)
{
    for (uint32_t y = 0; y < h; y++) {
        uint32_t *p = (uint32_t *)((uint8_t *)map + (size_t)y * pitch);
        uint32_t n = pitch / 4;
        for (uint32_t x = 0; x < n; x++)
            p[x] = color;
    }
}

/* Optional packed splash: le32 width, le32 height, then w*h BGRA pixels.
 * Centered on a Droidian dark-emerald fill if the file is a different size. */
#define SPLASH_BG 0xFF0B1A14

static void blit_splash(void *map, uint32_t h, uint32_t pitch)
{
    static unsigned char *file;
    static uint32_t sw, sh;
    const char *paths[] = {
        "/opt/kmsbin/splash.bgra",
        "/tmp/splash.bgra",
        NULL,
    };
    uint32_t y, x, dx, dy, src_pitch;
    int i;

    if (!file) {
        for (i = 0; paths[i]; i++) {
            int fd = open(paths[i], O_RDONLY | O_CLOEXEC);
            unsigned char hdr[8];
            size_t need;

            if (fd < 0)
                continue;
            if (read(fd, hdr, 8) != 8) {
                close(fd);
                continue;
            }
            sw = (uint32_t)hdr[0] | ((uint32_t)hdr[1] << 8) |
                 ((uint32_t)hdr[2] << 16) | ((uint32_t)hdr[3] << 24);
            sh = (uint32_t)hdr[4] | ((uint32_t)hdr[5] << 8) |
                 ((uint32_t)hdr[6] << 16) | ((uint32_t)hdr[7] << 24);
            if (!sw || !sh || sw > 4096 || sh > 4096) {
                close(fd);
                continue;
            }
            need = (size_t)sw * sh * 4;
            file = mmap(NULL, 8 + need, PROT_READ, MAP_PRIVATE, fd, 0);
            close(fd);
            if (file == MAP_FAILED) {
                file = NULL;
                continue;
            }
            LOG("splash %s %ux%u\n", paths[i], sw, sh);
            break;
        }
    }

    fill32(map, h, pitch, SPLASH_BG);
    if (!file)
        return;

    dx = sw <= (pitch / 4) ? ((pitch / 4) - sw) / 2 : 0;
    dy = sh <= h ? (h - sh) / 2 : 0;
    src_pitch = sw * 4;
    for (y = 0; y < sh && (y + dy) < h; y++) {
        uint32_t *dst = (uint32_t *)((uint8_t *)map + (size_t)(y + dy) * pitch) + dx;
        uint32_t *src = (uint32_t *)(file + 8 + (size_t)y * src_pitch);
        uint32_t maxx = sw;
        if (dx + maxx > pitch / 4)
            maxx = pitch / 4 - dx;
        for (x = 0; x < maxx; x++)
            dst[x] = src[x];
    }
}

static void dma_sync(int drm_fd, uint32_t handle)
{
    int pfd = -1;
    if (drmPrimeHandleToFD(drm_fd, handle, DRM_CLOEXEC | DRM_RDWR, &pfd) != 0) {
        LOG("PrimeToFD errno=%d\n", errno);
        return;
    }
#ifdef DMA_BUF_IOCTL_SYNC
    struct dma_buf_sync sync;
    memset(&sync, 0, sizeof(sync));
    sync.flags = DMA_BUF_SYNC_START | DMA_BUF_SYNC_RW;
    (void)ioctl(pfd, DMA_BUF_IOCTL_SYNC, &sync);
    sync.flags = DMA_BUF_SYNC_END | DMA_BUF_SYNC_RW;
    int rc = ioctl(pfd, DMA_BUF_IOCTL_SYNC, &sync);
    LOG("dma_sync rc=%d errno=%d pfd=%d\n", rc, errno, pfd);
#else
    LOG("no DMA_BUF_IOCTL_SYNC pfd=%d\n", pfd);
#endif
    close(pfd);
}

int main(void)
{
    signal(SIGALRM, on_alrm);
    serial_fd = open("/dev/ttyGS0", O_WRONLY | O_NONBLOCK | O_CLOEXEC);

    LOG("step open\n");
    int fd = open("/dev/dri/card0", O_RDWR | O_CLOEXEC);
    LOG("open fd=%d errno=%d\n", fd, errno);
    if (fd < 0)
        return 1;

    LOG("step SetMaster\n");
    timed_out = 0;
    alarm(3);
    int sm = drmSetMaster(fd);
    alarm(0);
    LOG("SetMaster rc=%d errno=%d timeout=%d\n", sm, errno, timed_out);

    LOG("step GetResources\n");
    timed_out = 0;
    alarm(5);
    drmModeRes *res = drmModeGetResources(fd);
    alarm(0);
    LOG("GetResources %p errno=%d timeout=%d\n", (void *)res, errno, timed_out);
    if (!res)
        return 1;
    LOG("crtcs=%d conns=%d encs=%d\n",
        res->count_crtcs, res->count_connectors, res->count_encoders);

    for (int i = 0; i < res->count_crtcs; i++) {
        drmModeCrtc *cr = drmModeGetCrtc(fd, res->crtcs[i]);
        if (!cr)
            continue;
        LOG("crtc %u buf=%u %dx%d valid=%d\n",
            cr->crtc_id, cr->buffer_id, cr->width, cr->height, cr->mode_valid);
        drmModeFreeCrtc(cr);
    }

    LOG("step GetConnectorCurrent 85\n");
    drmModeConnector *conn = drmModeGetConnectorCurrent(fd, 85);
    LOG("current conn=%p modes=%d\n", (void *)conn, conn ? conn->count_modes : -1);
    if (!conn || conn->count_modes <= 0) {
        if (conn)
            drmModeFreeConnector(conn);
        LOG("step GetConnector probe 85\n");
        conn = drmModeGetConnector(fd, 85);
    }
    if (!conn || conn->count_modes <= 0) {
        LOG("no modes conn=%p\n", (void *)conn);
        return 1;
    }
    uint32_t conn_id = conn->connector_id;
    LOG("conn %u connection=%d modes=%d enc=%u nenc=%d\n",
        conn_id, conn->connection, conn->count_modes, conn->encoder_id,
        conn->count_encoders);
    for (int i = 0; i < conn->count_encoders; i++)
        LOG("possible enc %u\n", conn->encoders[i]);

    drmModeModeInfo mode = conn->modes[0];
    for (int i = 0; i < conn->count_modes; i++) {
        LOG("mode %dx%d\n", conn->modes[i].hdisplay, conn->modes[i].vdisplay);
        if (conn->modes[i].hdisplay == 1200 && conn->modes[i].vdisplay == 1920)
            mode = conn->modes[i];
    }

    uint32_t crtc_id = 0;
    uint32_t enc_id = conn->encoder_id;
    if (!enc_id && conn->count_encoders)
        enc_id = conn->encoders[0];
    if (enc_id) {
        drmModeEncoder *enc = drmModeGetEncoder(fd, enc_id);
        if (enc) {
            LOG("encoder %u crtc=%u possible_crtcs=0x%x\n",
                enc->encoder_id, enc->crtc_id, enc->possible_crtcs);
            crtc_id = enc->crtc_id;
            if (!crtc_id) {
                for (int i = 0; i < res->count_crtcs; i++) {
                    if (enc->possible_crtcs & (1u << i)) {
                        crtc_id = res->crtcs[i];
                        break;
                    }
                }
            }
            drmModeFreeEncoder(enc);
        }
    }
    if (!crtc_id && res->count_crtcs)
        crtc_id = res->crtcs[0];
    LOG("using crtc=%u conn=%u enc=%u %dx%d\n",
        crtc_id, conn_id, enc_id, mode.hdisplay, mode.vdisplay);

    struct drm_mode_create_dumb creq;
    memset(&creq, 0, sizeof(creq));
    creq.width = mode.hdisplay;
    creq.height = mode.vdisplay;
    creq.bpp = 32;
    LOG("step CREATE_DUMB 32\n");
    int rc = drmIoctl(fd, DRM_IOCTL_MODE_CREATE_DUMB, &creq);
    LOG("CREATE_DUMB rc=%d errno=%d handle=%u pitch=%u size=%llu\n",
        rc, errno, creq.handle, creq.pitch, (unsigned long long)creq.size);
    if (rc != 0)
        return 1;

    uint32_t fb = 0;
    uint32_t handles[4] = { creq.handle, 0, 0, 0 };
    uint32_t pitches[4] = { creq.pitch, 0, 0, 0 };
    uint32_t offsets[4] = { 0, 0, 0, 0 };
    LOG("step AddFB2 AR24\n");
    rc = drmModeAddFB2(fd, mode.hdisplay, mode.vdisplay, DRM_FORMAT_ARGB8888,
                       handles, pitches, offsets, &fb, 0);
    LOG("AddFB2 rc=%d errno=%d fb=%u\n", rc, errno, fb);
    if (rc != 0) {
        rc = drmModeAddFB(fd, mode.hdisplay, mode.vdisplay, 24, 32, creq.pitch, creq.handle, &fb);
        LOG("AddFB rc=%d errno=%d fb=%u\n", rc, errno, fb);
        if (rc != 0)
            return 1;
    }

    struct drm_mode_map_dumb mreq;
    memset(&mreq, 0, sizeof(mreq));
    mreq.handle = creq.handle;
    LOG("step MAP_DUMB\n");
    rc = drmIoctl(fd, DRM_IOCTL_MODE_MAP_DUMB, &mreq);
    LOG("MAP_DUMB rc=%d errno=%d\n", rc, errno);
    if (rc != 0)
        return 1;
    void *map = mmap(NULL, creq.size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, mreq.offset);
    LOG("mmap %p errno=%d\n", map, errno);
    if (map == MAP_FAILED)
        return 1;
    /* Dim still frame. EDPI still needs two FBs, but the same pixels. */
    blit_splash(map, mode.vdisplay, creq.pitch);
    msync(map, creq.size, MS_SYNC);
    flush_dcache(map, creq.size);
    LOG("dcache flushed %u\n", (unsigned)creq.size);
    dma_sync(fd, creq.handle);
    rc = drmModeDirtyFB(fd, fb, NULL, 0);
    LOG("DirtyFB rc=%d errno=%d\n", rc, errno);
    backlight();

    errno = 0;
    LOG("step SetCrtc\n");
    timed_out = 0;
    alarm(5);
    rc = drmModeSetCrtc(fd, crtc_id, fb, 0, 0, &conn_id, 1, &mode);
    alarm(0);
    LOG("SetCrtc rc=%d errno=%d timeout=%d\n", rc, errno, timed_out);
    /* Dim still frame. EDPI still needs two FBs, but the same pixels. */
    blit_splash(map, mode.vdisplay, creq.pitch);
    msync(map, creq.size, MS_SYNC);
    flush_dcache(map, creq.size);
    LOG("dcache flushed %u\n", (unsigned)creq.size);
    dma_sync(fd, creq.handle);
    backlight();
    if (rc != 0)
        return 1;

    /*
     * sprd_plane_atomic_update() intentionally returns without programming a
     * layer when CRTC active_changed is true.  The initial SetCrtc therefore
     * enables the DPU but scans black.  Flip to a distinct FB now that the
     * CRTC is active so atomic_update reaches dpu->core->flip().
     */
    struct drm_mode_create_dumb creq2;
    memset(&creq2, 0, sizeof(creq2));
    creq2.width = mode.hdisplay;
    creq2.height = mode.vdisplay;
    creq2.bpp = 32;
    LOG("step CREATE_DUMB 32 FB2\n");
    rc = drmIoctl(fd, DRM_IOCTL_MODE_CREATE_DUMB, &creq2);
    LOG("CREATE_DUMB2 rc=%d errno=%d handle=%u pitch=%u size=%llu\n",
        rc, errno, creq2.handle, creq2.pitch,
        (unsigned long long)creq2.size);
    if (rc != 0)
        return 1;

    uint32_t fb2 = 0;
    uint32_t handles2[4] = { creq2.handle, 0, 0, 0 };
    uint32_t pitches2[4] = { creq2.pitch, 0, 0, 0 };
    uint32_t offsets2[4] = { 0, 0, 0, 0 };
    rc = drmModeAddFB2(fd, mode.hdisplay, mode.vdisplay,
                       DRM_FORMAT_ARGB8888, handles2, pitches2, offsets2,
                       &fb2, 0);
    LOG("AddFB2 FB2 rc=%d errno=%d fb=%u\n", rc, errno, fb2);
    if (rc != 0)
        return 1;

    struct drm_mode_map_dumb mreq2;
    memset(&mreq2, 0, sizeof(mreq2));
    mreq2.handle = creq2.handle;
    rc = drmIoctl(fd, DRM_IOCTL_MODE_MAP_DUMB, &mreq2);
    LOG("MAP_DUMB2 rc=%d errno=%d\n", rc, errno);
    if (rc != 0)
        return 1;
    void *map2 = mmap(NULL, creq2.size, PROT_READ | PROT_WRITE,
                      MAP_SHARED, fd, mreq2.offset);
    LOG("mmap2 %p errno=%d\n", map2, errno);
    if (map2 == MAP_FAILED)
        return 1;
    blit_splash(map2, mode.vdisplay, creq2.pitch);
    msync(map2, creq2.size, MS_SYNC);
    flush_dcache(map2, creq2.size);
    LOG("dcache flushed FB2 %u\n", (unsigned)creq2.size);

    errno = 0;
    LOG("step PageFlip FB2\n");
    rc = drmModePageFlip(fd, crtc_id, fb2, 0, NULL);
    LOG("PageFlip FB2 rc=%d errno=%d\n", rc, errno);
    if (rc != 0) {
        LOG("fallback SetCrtc FB2\n");
        rc = drmModeSetCrtc(fd, crtc_id, fb2, 0, 0,
                            &conn_id, 1, &mode);
        LOG("SetCrtc FB2 rc=%d errno=%d\n", rc, errno);
    }
    backlight();
    sleep(1);

    drmModeCrtc *after = drmModeGetCrtc(fd, crtc_id);
    if (after) {
        LOG("after crtc buf=%u %dx%d valid=%d\n",
            after->buffer_id, after->width, after->height, after->mode_valid);
        drmModeFreeCrtc(after);
    }
    drmEventContext ev;
    memset(&ev, 0, sizeof(ev));
    ev.version = DRM_EVENT_CONTEXT_VERSION;
    ev.page_flip_handler = on_page_flip;

    LOG("EVENT_REFRESH_LOOP\n");
    unsigned int frame = 0;
    for (;;) {
        uint32_t next_fb = (frame & 1) ? fb2 : fb;
        struct pollfd pfd = { .fd = fd, .events = POLLIN };
        int poll_rc = 0;

        flip_done = 0;
        errno = 0;
        rc = drmModePageFlip(fd, crtc_id, next_fb,
                             DRM_MODE_PAGE_FLIP_EVENT, NULL);
        if (rc == 0) {
            poll_rc = poll(&pfd, 1, 1500);
            if (poll_rc > 0 && (pfd.revents & POLLIN))
                (void)drmHandleEvent(fd, &ev);
        }
        if (frame < 16 || rc != 0 || poll_rc <= 0 || !flip_done) {
            LOG("refresh %u fb=%u rc=%d errno=%d poll=%d done=%d\n",
                frame, next_fb, rc, errno, poll_rc, flip_done);
        } else if (frame % 50 == 0) {
            /* Proves whether flips continue while the panel looks dark. */
            char bright[32], power[32];

            read_sysfs("/sys/class/backlight/sprd_backlight/brightness",
                       bright, sizeof(bright));
            read_sysfs("/sys/class/backlight/sprd_backlight/bl_power",
                       power, sizeof(power));
            LOG("alive frame=%u fb=%u bright=%s bl_power=%s\n",
                frame, next_fb, bright, power);
        }
        if (rc != 0 || poll_rc <= 0 || !flip_done) {
            errno = 0;
            rc = drmModeSetCrtc(fd, crtc_id, next_fb, 0, 0,
                                &conn_id, 1, &mode);
            LOG("refresh fallback fb=%u rc=%d errno=%d\n",
                next_fb, rc, errno);
        }
        frame++;
    }
}
