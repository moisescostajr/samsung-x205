/*
 * Dump the start of the AGCP DSP load region so we can tell whether the
 * firmware written through /sys/devices/platform/audiocp_boot/agdsp actually
 * landed in DDR (the sysfs store tracks ppos, so a second attempt silently
 * writes nothing).
 */
#include <linux/io.h>
#include <linux/module.h>

static unsigned long addr = 0x89000000;
module_param(addr, ulong, 0444);
MODULE_PARM_DESC(addr, "physical address to dump");

static unsigned int len = 64;
module_param(len, uint, 0444);
MODULE_PARM_DESC(len, "bytes to dump");

static int __init agdsp_peek_init(void)
{
	void *p = memremap(addr, len, MEMREMAP_WB);

	if (!p) {
		pr_err("agdsp_peek: memremap(%#lx) failed\n", addr);
		return -ENOMEM;
	}
	print_hex_dump(KERN_INFO, "agdsp_peek: ", DUMP_PREFIX_OFFSET,
		       16, 1, p, len, true);
	memunmap(p);

	return -EAGAIN; /* nothing to keep loaded */
}

static void __exit agdsp_peek_exit(void) { }

module_init(agdsp_peek_init);
module_exit(agdsp_peek_exit);
MODULE_LICENSE("GPL v2");
MODULE_DESCRIPTION("Dump gta8wifi AGCP DSP load region");
