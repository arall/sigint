# Sigint
The idea is to build a small device (Raspberry Pi 3 in my case) that will scan WiFi probes, Bluetooth devices and IMSI numbers nearby, and log those in a remote C&C.

This have different purposes. My original idea is to use it as an (potential) intruder "alarm" system for offgrid properties.

## Requirements

### Software
This was tested on a Raspberry Pi 3 B+, using Kali linux 2020.

#### Packages
`sudo apt-get install -y bluez wireless-tools tcpdump`

Built with Python 2.7, Python 3 is untested.
`cd scripts; pip install -r requirements`

#### IMSI Catcher
https://github.com/Oros42/IMSI-catcher

For installing it under RPi3 follow this script / guide: https://gist.github.com/arall/370b5fe5277506026c078a7cf5cb97e3

#### Laravel Nova License
The admin panel works with [Laravel Nova](https://nova.laravel.com/) and requires a comercial license.
You can still use the project without an admin GUI by querying the MySQL DB or implementing any other Laravel Admin panel.

### Hardware

#### WiFi device with monitor mode
Any Alfa would work.

#### Bluetooth device
Built in Raspberry Pi bluetooth works out of the box.

#### SDR device
USB [DVB-T key (RTL2832U)](https://osmocom.org/projects/rtl-sdr/wiki/Rtl-sdr) with antenna (less than 15$) or a [OsmocomBB phone](https://osmocom.org/projects/baseband/wiki/Phones) or [HackRF](https://greatscottgadgets.com/hackrf/).

## Setup
For the C&C, install using [Composer](https://getcomposer.org/):
```
composer install
```

Set the `.env` variables. Make sure to generate a random `API_KEY`.

Set the C&C `API_URL` and the `API_KEY` in `scripts/.env`

## Running
Start monitor mode on your WiFi device: `airmon-ng start wlan1`

Run those two scripts in a background session (or as a daemons):
```
cd scripts; python bluetooth.py
```
```
cd scripts; python wifi.py wlan1mon
```

## Devices specs

https://www.raspberrypi.org/documentation/faqs/

```
Raspberry Pi 4 B
Power: 5V/3A
Consumption: 600mA
WiFi: 2.4 GHz and 5.0 GHz IEEE 802.11b/g/n/ac
BT: Bluetooth 5.0, BLE

Raspberry Pi 3 B+
Power: 5V/2.5A
Consumption: 500mA
WiFi: 2.4GHz and 5GHz IEEE 802.11.b/g/n/ac
BT: Bluetooth 4.2, BLE

Raspberry Pi Zero W
Power: 5V/1.2A
Consumption: 150mA
WiFi: 802.11 b/g/n wireless LAN
BT: Bluetooth 4.1, BLE
```

## Limitations
The randomized MAC addresses being used are locally administered MAC addresses.  
You can recognize a locally administered address by inspecting the 2nd least significant bit of the 2nd byte of the MAC address.
http://www.dfrc.com.sg/mac-randomization-crowd-analytics/