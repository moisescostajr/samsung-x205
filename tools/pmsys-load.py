#!/usr/bin/env python3
"""Load Unisoc AON firmware. Kernel cproc only accepts process name modem_control."""
import ctypes
import os
import time

PR_SET_NAME = 15
ctypes.CDLL(None).prctl(PR_SET_NAME, b"modem_control", 0, 0, 0)


def wr(srcpath, dstpath):
    with open(srcpath, "rb") as src, open(dstpath, "wb", buffering=0) as dst:
        total = 0
        while True:
            chunk = src.read(4096)
            if not chunk:
                break
            total += dst.write(chunk)
    print("wrote", srcpath, "->", dstpath, total)


print("comm", open("/proc/self/comm").read().strip())
print("status0", open("/proc/pmic/status").read().strip())
# Never write /proc/pmic/stop: taking a running AON down hard-resets this board.
wr("/dev/mmcblk0p20", "/proc/pmic/pm_sys")
cali = "/vendor/firmware/EXEC_CALIBRATE_mmc5603"
if os.path.exists(cali):
    wr(cali, "/proc/pmic/cali_lib")
else:
    print("skip cali_lib (no", cali, ")")
open("/proc/pmic/start", "w").write("start\n")
time.sleep(2)
print("status1", open("/proc/pmic/status").read().strip())
