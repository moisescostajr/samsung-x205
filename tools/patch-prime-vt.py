#!/usr/bin/env python3
"""Wire real DRM PRIME export into the SPRD 4.14 display driver.

The driver advertises DRIVER_PRIME and ships sprd_gem_cma_prime_get_sg_table()
and sprd_gem_cma_prime_mmap(), but drm_driver only assigns the import half, so
DRM_IOCTL_PRIME_HANDLE_TO_FD returns -ENOSYS and wlroots cannot scan out.
"""
import pathlib
import sys

SRC = pathlib.Path("drivers/gpu/drm/sprd/sprd_drm.c")

HELPERS = """/*
 * drm_gem_prime_export() reaches the dma-buf vmap hooks unconditionally, and
 * the CMA path keeps the kernel mapping in sprd_gem_obj.vaddr.
 */
static void *sprd_gem_prime_vmap(struct drm_gem_object *obj)
{
\tstruct sprd_gem_obj *sprd_gem = to_sprd_gem_obj(obj);

\treturn sprd_gem->vaddr;
}

static void sprd_gem_prime_vunmap(struct drm_gem_object *obj, void *vaddr)
{
}

static struct drm_driver sprd_drm_drv = {"""

OLD_ANCHOR = "static struct drm_driver sprd_drm_drv = {"

OLD_BLOCK = """\t.prime_fd_to_handle\t= drm_gem_prime_fd_to_handle,
\t.gem_prime_import\t= drm_gem_prime_import,
\t.gem_prime_import_sg_table = sprd_gem_prime_import_sg_table,
"""

NEW_BLOCK = """\t.prime_handle_to_fd\t= drm_gem_prime_handle_to_fd,
\t.prime_fd_to_handle\t= drm_gem_prime_fd_to_handle,
\t.gem_prime_export\t= drm_gem_prime_export,
\t.gem_prime_import\t= drm_gem_prime_import,
\t.gem_prime_get_sg_table\t= sprd_gem_cma_prime_get_sg_table,
\t.gem_prime_import_sg_table = sprd_gem_prime_import_sg_table,
\t.gem_prime_vmap\t\t= sprd_gem_prime_vmap,
\t.gem_prime_vunmap\t= sprd_gem_prime_vunmap,
\t.gem_prime_mmap\t\t= sprd_gem_cma_prime_mmap,
"""


def main():
    text = SRC.read_text()

    if ".prime_handle_to_fd" in text:
        print("already patched")
        return 0

    if text.count(OLD_BLOCK) != 1:
        print("FAIL: prime block not found exactly once", file=sys.stderr)
        return 1
    if text.count(OLD_ANCHOR) != 1:
        print("FAIL: drm_driver anchor not unique", file=sys.stderr)
        return 1

    text = text.replace(OLD_BLOCK, NEW_BLOCK)
    text = text.replace(OLD_ANCHOR, HELPERS)
    SRC.write_text(text)

    for needle in (".prime_handle_to_fd", ".gem_prime_export",
                   ".gem_prime_get_sg_table", "sprd_gem_prime_vmap"):
        assert needle in SRC.read_text(), needle
    print("patched", SRC)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
