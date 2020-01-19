import subprocess
import re

import time
devices = []

subprocess.Popen('hciconfig hci0 up', stdout=subprocess.PIPE, shell=True)
subprocess.Popen('btmgmt le on', stdout=subprocess.PIPE, shell=True)

proc = subprocess.Popen('sudo btmgmt find', stdout=subprocess.PIPE, shell=True)
output = proc.communicate()
for line in str(output).split('\\n')[:-1]:
    if 'hci0 dev_found' in line:
        # Store the previous
        if 'device' in locals():
            devices.append(device);
        device = {}
        m = re.search('dev_found: (([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})) type (.*?) rssi (-\d+) flags', line)
        device['mac'] = m.group(1)
        device['type'] = m.group(4)
        device['rssi'] = m.group(5)
        device['time'] = int(time.time())
    elif 'AD flags ' in line:
        m = re.search('AD flags (.*)', line)
        device['flags'] = m.group(1).rstrip()
    elif 'name ' in line:
        m = re.search('^name (.*)', line)
        if m:
            device['name'] = m.group(1).rstrip()

for device in devices:
    print device
