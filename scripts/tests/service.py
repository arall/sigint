import subprocess
import re
import time


SLEEP = 15 * 60;
OUTPUT = 'output.log'
WIFI_INTERFACE = 'wlan0'
WIFI_MONITOR_INTERFACE = 'wlan0mon'
WIFI_SCAN_TIMEOUT = '120s'


def write_output(data):
    with open(OUTPUT, 'w') as out:
        out.write(data + '\n')


def prepare_bluetooth():
    subprocess.Popen('hciconfig hci0 up', stdout=subprocess.PIPE, shell=True)
    subprocess.Popen('btmgmt le on', stdout=subprocess.PIPE, shell=True)


def prepare_wifi():
    subprocess.Popen(['airmon-ng', WIFI_INTERFACE ,'start'], stdout=subprocess.PIPE, shell=True)


def scan_bluetooth():
    devices = []
    proc = subprocess.Popen('btmgmt find', stdout=subprocess.PIPE, shell=True)
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
        write_output(str(device))


def scan_wifi():
    proc = subprocess.Popen(['timeout', WIFI_SCAN_TIMEOUT, 'tcpdump', '-l', '-I', '-i', WIFI_MONITOR_INTERFACE, '-e', '-s', '256', 'type', 'mgt', 'subtype', 'probe-req'], stdout=subprocess.PIPE)
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
                write_output(str(probe))
        else:
            break


def send_logs():
    print 'Sending logs...'


prepare_bluetooth();
prepare_wifi();

# Every hour
while True:
    # 4 times, sleep every 15 minutes
    for x in range(0, 3):
        scan_wifi()
        scan_bluetooth()
        time.sleep(SLEEP)
    send_logs()

