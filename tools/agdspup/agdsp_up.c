/*
 * Power up the AGCP audio subsystem on gta8wifi so the audio DSP can boot.
 *
 * Android's audio HAL keeps the AGCP awake through the kernel's
 * agdsp_access_enable(), which sets AUDACCESS_APB_AGCP_ACCESS_EN, mails the
 * DSP and waits for the PMU power-up state.  Nothing in a plain Linux
 * userspace does that, so /sys/devices/platform/audiocp_boot/status keeps
 * reporting 7 (power off) and every VBC scene dies in
 * "aud_send_cmd: failed to get command(5)".
 *
 * Keeping this module loaded holds the enable count, which is what the HAL
 * does for the lifetime of a stream.
 */
#include <linux/delay.h>
#include <linux/module.h>

extern int agdsp_access_enable(void);
extern int agdsp_access_disable(void);

static int __init agdsp_up_init(void)
{
	int ret;

	ret = agdsp_access_enable();
	pr_info("agdsp_up: agdsp_access_enable() = %d\n", ret);
	if (ret)
		return ret;

	msleep(20);

	return 0;
}

static void __exit agdsp_up_exit(void)
{
	int ret = agdsp_access_disable();

	pr_info("agdsp_up: agdsp_access_disable() = %d\n", ret);
}

module_init(agdsp_up_init);
module_exit(agdsp_up_exit);
MODULE_LICENSE("GPL v2");
MODULE_DESCRIPTION("Hold the gta8wifi AGCP audio subsystem powered up");
