#!/usr/bin/env python3
"""Neutralize and continuously feed the SC2730 PMIC watchdog directly in sprd_pmic_wdt.c.

The bootloader arms this watchdog. In Android, the proprietary modem/pm_sys services
feed it. In Linux userspace, nothing feeds it and the tablet resets ~265s after boot
with 'cm4_watchdog_timeout'.

This patch modifies sprd_pmic_wdt.c to:
1. Immediately unlock and disable the reset enable bit (WDT_RST_EN) in PMIC hardware.
2. Continuously reload the watchdog counter to 60s every 15s using a kernel workqueue.
3. Prevent sending 'watchdog on' over SIPC.
"""
import pathlib
import sys

TARGET = pathlib.Path("kernel/drivers/watchdog/sprd_pmic_wdt.c")
if not TARGET.is_file():
    TARGET = pathlib.Path("drivers/watchdog/sprd_pmic_wdt.c")

if not TARGET.is_file():
    print(f"Error: {TARGET} not found", file=sys.stderr)
    sys.exit(1)

src = TARGET.read_text(encoding="utf-8")

if "sprd_pmic_wdt_hw_feed" in src:
    print("sprd_pmic_wdt.c already patched")
    sys.exit(0)

# 1. Add required headers
src = "#include <linux/delay.h>\n#include <linux/workqueue.h>\n" + src

# 2. Add feed_work to struct sprd_pmic_wdt and define feeding functions
old_struct = """struct sprd_pmic_wdt {
\tstruct regmap\t\t*regmap;
\tstruct device\t\t*dev;
\tu32\t\t\tbase;
\tbool wdten;
\tstruct alarm wdt_timer;
\tstruct kthread_worker wdt_kworker;
\tstruct kthread_work wdt_kwork;
\tstruct task_struct *wdt_thread;

};"""

new_struct = """struct sprd_pmic_wdt {
\tstruct regmap\t\t*regmap;
\tstruct device\t\t*dev;
\tu32\t\t\tbase;
\tbool wdten;
\tstruct alarm wdt_timer;
\tstruct kthread_worker wdt_kworker;
\tstruct kthread_work wdt_kwork;
\tstruct task_struct *wdt_thread;
\tstruct delayed_work feed_work;
};

static void sprd_pmic_wdt_hw_feed(struct sprd_pmic_wdt *wdt)
{
\tu64 ticks = (u64)60 * SPRD_PMIC_WDT_CNT_STEP;
\tint i;
\tunsigned int val = 0;

\tif (!wdt || !wdt->regmap)
\t\treturn;

\t/* Unlock PMIC watchdog register access */
\tregmap_write(wdt->regmap, wdt->base + SPRD_PMIC_WDT_LOCK, SPRD_PMIC_WDT_UNLOCK_KEY);

\t/* Clear interrupt and reset status bits */
\tregmap_write(wdt->regmap, wdt->base + SPRD_PMIC_WDT_INT_CLR,
\t\t     SPRD_PMIC_WDT_INT_CLEAR_BIT | SPRD_PMIC_WDT_RST_CLEAR_BIT);

\t/* Clear reset enable bit so the watchdog cannot reset the SoC */
\tregmap_update_bits(wdt->regmap, wdt->base + SPRD_PMIC_WDT_CTRL,
\t\t\t   SPRD_PMIC_WDT_INT_EN_BIT | SPRD_PMIC_WDT_CNT_EN_BIT | SPRD_PMIC_WDT_RST_EN_BIT, 0);

\t/* Wait for load busy bit to clear */
\tfor (i = 0; i < 100; i++) {
\t\tregmap_read(wdt->regmap, wdt->base + SPRD_PMIC_WDT_INT_RAW, &val);
\t\tif (!(val & SPRD_PMIC_WDT_LD_BUSY_BIT))
\t\t\tbreak;
\t\tudelay(100);
\t}

\t/* Reload watchdog counter to 60s timeout */
\tregmap_write(wdt->regmap, wdt->base + SPRD_PMIC_WDT_LOAD_HIGH, (u32)(ticks >> 16) & 0xffff);
\tregmap_write(wdt->regmap, wdt->base + SPRD_PMIC_WDT_LOAD_LOW, (u32)ticks & 0xffff);

\t/* Relock registers */
\tregmap_write(wdt->regmap, wdt->base + SPRD_PMIC_WDT_LOCK, ~SPRD_PMIC_WDT_UNLOCK_KEY & 0xffff);
}

static void sprd_pmic_wdt_delayed_feed(struct work_struct *work)
{
\tstruct sprd_pmic_wdt *pmic_wdt = container_of(to_delayed_work(work),
\t\t\t\t\t\t      struct sprd_pmic_wdt,
\t\t\t\t\t\t      feed_work);
\tsprd_pmic_wdt_hw_feed(pmic_wdt);
\tschedule_delayed_work(&pmic_wdt->feed_work, 15 * HZ);
}"""

if old_struct not in src:
    print("Error: struct sprd_pmic_wdt anchor not found", file=sys.stderr)
    sys.exit(1)

src = src.replace(old_struct, new_struct, 1)

# 3. Start feeding work in sprd_pmic_wdt_probe
old_probe_end = "platform_set_drvdata(pdev, pmic_wdt);\n\n\treturn ret;"
new_probe_end = """platform_set_drvdata(pdev, pmic_wdt);

\t/* Neutralize SC2730 PMIC watchdog immediately and start 15s keepalive */
\tsprd_pmic_wdt_hw_feed(pmic_wdt);
\tINIT_DELAYED_WORK(&pmic_wdt->feed_work, sprd_pmic_wdt_delayed_feed);
\tschedule_delayed_work(&pmic_wdt->feed_work, 15 * HZ);
\tdev_info(&pdev->dev, "sprd_pmic_wdt: hardware watchdog neutralized & 15s feeder running\\n");

\treturn ret;"""

if old_probe_end not in src:
    print("Error: probe anchor not found", file=sys.stderr)
    sys.exit(1)

src = src.replace(old_probe_end, new_probe_end, 1)

# 4. In sprd_pimc_wdt_en, always return false
old_en = """static bool sprd_pimc_wdt_en(void)
{
\tstruct device_node *cmdline_node;"""

new_en = """static bool sprd_pimc_wdt_en(void)
{
\treturn false;
\tstruct device_node *cmdline_node;"""

if old_en not in src:
    print("Error: sprd_pimc_wdt_en anchor not found", file=sys.stderr)
    sys.exit(1)

src = src.replace(old_en, new_en, 1)

# 5. Clean up feeding work on remove
old_remove = """static int sprd_pmic_wdt_remove(struct platform_device *pdev)
{
\tstruct sprd_pmic_wdt *pmic_wdt = dev_get_drvdata(&pdev->dev);"""

new_remove = """static int sprd_pmic_wdt_remove(struct platform_device *pdev)
{
\tstruct sprd_pmic_wdt *pmic_wdt = dev_get_drvdata(&pdev->dev);
\tcancel_delayed_work_sync(&pmic_wdt->feed_work);"""

if old_remove in src:
    src = src.replace(old_remove, new_remove, 1)

TARGET.write_text(src, encoding="utf-8")
print(f"Successfully patched {TARGET} to neutralize PMIC watchdog!")
