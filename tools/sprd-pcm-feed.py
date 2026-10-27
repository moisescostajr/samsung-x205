#!/usr/bin/python3
"""Feed the Unisoc PCM continuously from PulseAudio's pipe sink.

module-pipe-sink stops writing once no client is playing. The SPRD DMA keeps
cycling its ring buffer regardless, so the last fragment repeats forever.
Reading the FIFO non-blocking and padding short reads with silence keeps the
stream coherent: audio when a client plays, silence when idle.

Output goes to stdout, meant to be piped into:
    aplay -D hw:0,0 --period-size=8192 --buffer-size=16384 -f S16_LE -c 2 \
          -r 48000 -t raw -N
"""
import array
import os
import sys
import time

FIFO = "/run/sprd.pcm"
RATE = 48000
FRAME = 4          # S16_LE stereo
CHUNK_FRAMES = 2048
CHUNK = CHUNK_FRAMES * FRAME
SILENCE = bytes(CHUNK)
# VBC digital gain is not in the IIS/HIFI path (DAC_OUT_FROM_IIS). Quiet
# DVB sits around -13 dBFS even at VLC 100%; this is a hard +12 dB with clip.
GAIN = 4.0


def main() -> int:
    fifo = os.open(FIFO, os.O_RDWR | os.O_NONBLOCK)
    out = sys.stdout.buffer
    pending = bytearray()
    # Pace on the wall clock; aplay's blocking write would otherwise let us
    # spin whenever the FIFO is empty.
    period = CHUNK_FRAMES / RATE
    next_due = time.monotonic()

    while True:
        while len(pending) < CHUNK:
            try:
                data = os.read(fifo, CHUNK - len(pending))
            except BlockingIOError:
                break
            except OSError:
                break
            if not data:
                break
            pending += data

        if len(pending) >= CHUNK:
            block = bytes(pending[:CHUNK])
            del pending[:CHUNK]
        elif pending:
            block = bytes(pending) + SILENCE[len(pending):]
            pending.clear()
        else:
            block = SILENCE

        if GAIN != 1.0:
            samples = array.array("h")
            samples.frombytes(block)
            for i, s in enumerate(samples):
                v = int(s * GAIN)
                if v > 32767:
                    v = 32767
                elif v < -32768:
                    v = -32768
                samples[i] = v
            block = samples.tobytes()

        try:
            out.write(block)
            out.flush()
        except BrokenPipeError:
            return 0

        next_due += period
        delay = next_due - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            next_due = time.monotonic()


if __name__ == "__main__":
    raise SystemExit(main())
