import subprocess
import re
import time
from dotenv import load_dotenv
import os
import requests
import sys

load_dotenv()

headers = {"Authorization": "Bearer " + os.getenv('STATION_TOKEN')}

if len(sys.argv) != 2:
    print "Usage %s monitor_interface" % sys.argv[0]
    sys.exit(1)

interface = sys.argv[1]

subprocess.Popen(['sudo hciconfig', interface, 'up'], stdout=subprocess.PIPE, shell=True)
subprocess.Popen('sudo btmgmt le on', stdout=subprocess.PIPE, shell=True)

while True:
    devices = []
    proc = subprocess.Popen('sudo btmgmt find', stdout=subprocess.PIPE, shell=True)
    output = proc.communicate()
    for line in str(output).split('\\n')[:-1]:
        if ' dev_found' in line:
            # Store the previous
            if 'device' in locals():
                devices.append(device);
            device = {}
            m = re.search('dev_found: (([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})) type (.*?) rssi (-\d+) flags', line)
            device['type_id'] = 1
            device['identifier'] = m.group(1)
            device['type'] = m.group(4)
            device['signal'] = m.group(5)
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
        try:
            requests.post(os.getenv('API_URL') + 'logs', data=device, headers=headers)
        except:
            print("Error reaching the API")
