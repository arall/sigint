#!/usr/bin/env python2.7
# Based on :https://gist.github.com/LoranKloeze/6b713022619c2b32b32c6400a55a8433

import subprocess
import re
import time
import sys
import os
import signal
import random
from multiprocessing import Process


def channel_hopper():
    while True:
        try:
            channel = random.randrange(1,15) # 2.5 GHz
            subprocess.Popen("sudo iwconfig %s channel %d" % (interface, channel), shell=True).wait()
            #os.system("sudo iwconfig %s channel %d" % (interface, channel))
            time.sleep(1)
        except KeyboardInterrupt:
            break


def tpcdump():
    while True:
        proc = subprocess.Popen(['tcpdump', '-l', '-I', '-i', interface, '-e', '-s', '256', 'type', 'mgt', 'subtype', 'probe-req'], stdout=subprocess.PIPE)
        patt = '(-\d+)dBm signal antenna 0.+SA:([0-9a-f]+:[0-9a-f]+:[0-9a-f]+:[0-9a-f]+:[0-9a-f]+:[0-9a-f]+) .+(Probe Request) \((.+)\)'
        while True:
            line = proc.stdout.readline()
            if line != '':
                m = re.search(patt, line)
                if m is not None and len(m.groups()) == 4:
                    probe = {
                        'signal': m.group(1).rstrip(),
                        'mac': m.group(2).rstrip(),
                        'ssid': m.group(4).rstrip(),
                        'time': int(time.time()),
                    }
                    print probe
            else:
                break


def signal_handler(signal, frame):
    p.terminate()
    p.join()

    p2.terminate()
    p2.join()

    sys.exit(0)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print "Usage %s monitor_interface" % sys.argv[0]
        sys.exit(1)

    interface = sys.argv[1]

    p = Process(target = channel_hopper)
    p.start()

    p2 = Process(target = tpcdump)
    p2.start()

    # Capture CTRL-C
    signal.signal(signal.SIGINT, signal_handler)