#!/usr/bin/env python2.7
# Based on :https://gist.github.com/LoranKloeze/6b713022619c2b32b32c6400a55a8433

import subprocess
import re
import time
import sys

interface = sys.argv[1]

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