/* Persistent SPRD DRM client: set a mode and sleep so the panel does not blank. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <xf86drm.h>
#include <xf86drmMode.h>

static void fill(void *map, uint32_t h, uint32_t pitch, uint32_t color)
{
    for (uint32_t y = 0; y < h; y++) {
        uint32_t *p = (uint32_t *)((uint8_t *)map + (size_t)y * pitch);
        uint32_t n = pitch / 4;
        for (uint32_t x = 0; x < n; x++)
            p[x] = color;
    }
}

static void backlight(void)
{
    int bl = open("/sys/class/backlight/sprd_backlight/brightness", O_WRONLY);
    if (bl >= 0) {
        (void)write(bl, "255\n", 4);
        close(bl);
    }
}

int main(void)
{
    int fd = -1;
    for (int i = 0; i < 40; i++) {
        fd = open("/dev/dri/card0", O_RDWR | O_CLOEXEC);
        if (fd >= 0)
            break;
        perror("open /dev/dri/card0");
        sleep(1);
    }
    if (fd < 0)
        return 1;

    (void)drmSetMaster(fd);

    drmModeRes *res = NULL;
    for (int i = 0; i < 20 && !res; i++) {
        res = drmModeGetResources(fd);
        if (!res) {
            perror("drmModeGetResources");
            sleep(1);
        }
    }
    if (!res)
        return 1;

    drmModeConnector *conn = NULL;
    uint32_t conn_id = 0;
    for (int i = 0; i < res->count_connectors; i++) {
        drmModeConnector *c = drmModeGetConnector(fd, res->connectors[i]);
        if (!c)
            continue;
        fprintf(stderr, "connector %u conn=%d modes=%d\n",
                c->connector_id, c->connection, c->count_modes);
        if (!conn && c->connection == DRM_MODE_CONNECTED && c->count_modes > 0) {
            conn = c;
            conn_id = c->connector_id;
        } else {
            drmModeFreeConnector(c);
        }
    }
    if (!conn) {
        conn = drmModeGetConnector(fd, 85);
        conn_id = 85;
    }
    if (!conn || conn->count_modes <= 0) {
        fprintf(stderr, "no connector modes\n");
        return 1;
    }

    drmModeModeInfo mode = conn->modes[0];
    for (int i = 0; i < conn->count_modes; i++) {
        fprintf(stderr, "mode %dx%d\n", conn->modes[i].hdisplay, conn->modes[i].vdisplay);
        if (conn->modes[i].hdisplay == 1200 && conn->modes[i].vdisplay == 1920)
            mode = conn->modes[i];
    }

    uint32_t crtc_id = 0;
    if (conn->encoder_id) {
        drmModeEncoder *enc = drmModeGetEncoder(fd, conn->encoder_id);
        if (enc) {
            crtc_id = enc->crtc_id;
            drmModeFreeEncoder(enc);
        }
    }
    if (!crtc_id && res->count_crtcs)
        crtc_id = res->crtcs[0];

    struct drm_mode_create_dumb creq;
    memset(&creq, 0, sizeof(creq));
    creq.width = mode.hdisplay;
    creq.height = mode.vdisplay;
    creq.bpp = 32;
    if (drmIoctl(fd, DRM_IOCTL_MODE_CREATE_DUMB, &creq) != 0) {
        perror("CREATE_DUMB");
        return 1;
    }

    uint32_t fb = 0;
    if (drmModeAddFB(fd, mode.hdisplay, mode.vdisplay, 24, 32, creq.pitch, creq.handle, &fb) != 0) {
        perror("AddFB");
        return 1;
    }

    struct drm_mode_map_dumb mreq;
    memset(&mreq, 0, sizeof(mreq));
    mreq.handle = creq.handle;
    if (drmIoctl(fd, DRM_IOCTL_MODE_MAP_DUMB, &mreq) != 0) {
        perror("MAP_DUMB");
        return 1;
    }
    void *map = mmap(NULL, creq.size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, mreq.offset);
    if (map == MAP_FAILED) {
        perror("mmap");
        return 1;
    }
    fill(map, mode.vdisplay, creq.pitch, 0xFF00AA00);

    int rc = -1;
    for (int t = 0; t < 30; t++) {
        backlight();
        rc = drmModeSetCrtc(fd, crtc_id, fb, 0, 0, &conn_id, 1, &mode);
        if (rc == 0)
            break;
        fprintf(stderr, "SetCrtc try %d: %s\n", t, strerror(errno));
        sleep(1);
    }
    fprintf(stderr, "HOLD crtc=%u conn=%u %dx%d rc=%d\n",
            crtc_id, conn_id, mode.hdisplay, mode.vdisplay, rc);
    if (rc != 0)
        return 1;

    for (;;) {
        backlight();
        sleep(8);
    }
}
