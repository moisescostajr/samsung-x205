/*
 * Stop (or failing that, feed) the SC2730 PMIC watchdog on gta8wifi.
 *
 * The bootloader arms this watchdog and Android's sprd_pmic_wdt driver hands
 * servicing to the PM co-processor by writing the string "watchdog on" over
 * SIPC.  Under a plain Linux userspace that channel never comes up -- the
 * driver logs "failed to set pmic wdt 1!" -- so nothing feeds the timer and
 * the tablet resets about 265 s after boot.
 *
 * The register block base is not fixed: sprd_pmic_wdt reads it from the "reg"
 * property of the sc27xx-wdt node, so take it from there instead of guessing.
 * If clearing the enable bits does not stick, fall back to reloading the
 * counter periodically, which is what the PM co-processor would have done.
 */
#include <linux/bitops.h>
#include <linux/device.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>
#include <linux/workqueue.h>

#define WDT_LOAD_LOW		0x00
#define WDT_LOAD_HIGH		0x04
#define WDT_CTRL		0x08
#define WDT_INT_CLR		0x0c
#define WDT_INT_RAW		0x10
#define WDT_CNT_LOW		0x18
#define WDT_CNT_HIGH		0x1c
#define WDT_LOCK		0x20

#define WDT_INT_EN		BIT(0)
#define WDT_CNT_EN		BIT(1)
#define WDT_NEW_VER_EN		BIT(2)
#define WDT_RST_EN		BIT(3)

#define WDT_INT_CLEAR		BIT(0)
#define WDT_RST_CLEAR		BIT(3)
#define WDT_LD_BUSY		BIT(4)

#define WDT_UNLOCK_KEY		0xe551
#define WDT_CNT_STEP		32768	/* counter ticks per second */

/* Reload well inside the window the bootloader programmed. */
#define FEED_TIMEOUT_SEC	60
#define FEED_INTERVAL_SEC	20

static struct regmap *wdt_regmap;
static u32 wdt_base;
static bool feeding;
static struct delayed_work feed_work;

static unsigned int rd(u32 off)
{
	unsigned int val = 0;

	regmap_read(wdt_regmap, wdt_base + off, &val);
	return val;
}

static void dump(const char *when)
{
	pr_info("pmicwdt: %s base 0x%x ctrl 0x%x load 0x%04x%04x cnt 0x%04x%04x raw 0x%x\n",
		when, wdt_base, rd(WDT_CTRL), rd(WDT_LOAD_HIGH), rd(WDT_LOAD_LOW),
		rd(WDT_CNT_HIGH), rd(WDT_CNT_LOW), rd(WDT_INT_RAW));
}

static void wdt_unlock(void)
{
	regmap_write(wdt_regmap, wdt_base + WDT_LOCK, WDT_UNLOCK_KEY);
}

static void wdt_lock(void)
{
	regmap_write(wdt_regmap, wdt_base + WDT_LOCK, ~WDT_UNLOCK_KEY & 0xffff);
}

static void wdt_load(u32 seconds)
{
	u64 ticks = (u64)seconds * WDT_CNT_STEP;
	int i;

	for (i = 0; i < 100; i++) {
		if (!(rd(WDT_INT_RAW) & WDT_LD_BUSY))
			break;
		udelay(100);
	}
	regmap_write(wdt_regmap, wdt_base + WDT_LOAD_HIGH,
		     (u32)(ticks >> 16) & 0xffff);
	regmap_write(wdt_regmap, wdt_base + WDT_LOAD_LOW, (u32)ticks & 0xffff);
}

static void feed_fn(struct work_struct *work)
{
	wdt_unlock();
	wdt_load(FEED_TIMEOUT_SEC);
	wdt_lock();
	schedule_delayed_work(&feed_work, FEED_INTERVAL_SEC * HZ);
}

static int __init pmicwdt_off_init(void)
{
	struct device *dev;
	unsigned int ctrl;
	int ret;

	dev = bus_find_device_by_name(&platform_bus_type, NULL, "sc27xx-wdt");
	if (!dev) {
		pr_err("pmicwdt: sc27xx-wdt device not found\n");
		return -ENODEV;
	}
	if (!dev->parent) {
		pr_err("pmicwdt: no parent for sc27xx-wdt\n");
		put_device(dev);
		return -ENODEV;
	}

	wdt_regmap = dev_get_regmap(dev->parent, NULL);
	if (!wdt_regmap) {
		pr_err("pmicwdt: no regmap on %s\n", dev_name(dev->parent));
		put_device(dev);
		return -ENODEV;
	}

	ret = of_property_read_u32(dev->of_node, "reg", &wdt_base);
	if (ret) {
		pr_err("pmicwdt: no reg property (%d), falling back to 0x4000\n",
		       ret);
		wdt_base = 0x4000;
	}
	put_device(dev);

	dump("before");

	wdt_unlock();
	regmap_write(wdt_regmap, wdt_base + WDT_INT_CLR,
		     WDT_INT_CLEAR | WDT_RST_CLEAR);
	regmap_update_bits(wdt_regmap, wdt_base + WDT_CTRL,
			   WDT_INT_EN | WDT_CNT_EN | WDT_RST_EN, 0);
	ctrl = rd(WDT_CTRL);
	wdt_lock();

	dump("after");

	/*
	 * Clearing the enable bits is not always honoured: on some SC2730
	 * builds the counter keeps running under the PM co-processor's
	 * ownership.  Reloading it on a timer is then the only thing that
	 * keeps the reset away.
	 */
	if (ctrl & (WDT_CNT_EN | WDT_RST_EN)) {
		pr_info("pmicwdt: still enabled (ctrl 0x%x), feeding instead\n",
			ctrl);
		feeding = true;
	} else {
		pr_info("pmicwdt: disabled, feeding anyway as insurance\n");
		feeding = true;
	}

	INIT_DELAYED_WORK(&feed_work, feed_fn);
	schedule_delayed_work(&feed_work, 0);

	return 0;
}

static void __exit pmicwdt_off_exit(void)
{
	if (feeding)
		cancel_delayed_work_sync(&feed_work);
}

module_init(pmicwdt_off_init);
module_exit(pmicwdt_off_exit);

MODULE_DESCRIPTION("Disable or feed the SC2730 PMIC watchdog on gta8wifi");
MODULE_LICENSE("GPL v2");
