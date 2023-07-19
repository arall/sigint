# Sigint
The idea is to build a small device (Raspberry Pi 3 in my case) that will scan **WiFi probes**, **Bluetooth devices** and **IMSI numbers** (still work in progress) nearby, and log those into a server.

This have different purposes. My original idea is to use it as an (potential) intruder monitoring system for off-grid properties.

## How it works

Server & Stations.


## Requirements

This project was tested on:
* Raspberry Pi 3 B+ with Kali linux 2020
* Raspberry Pi 4 B with Raspberry Pi OS

### Software

#### Linux Packages
`sudo apt-get install -y bluez wireless-tools tcpdump`

#### Python dependencies
`cd scripts; pip install -r requirements.txt`

#### IMSI Catcher
https://github.com/Oros42/IMSI-catcher

For installing it under Raspberry Pi follow this script / guide: https://gist.github.com/arall/370b5fe5277506026c078a7cf5cb97e3

Get your device info with: `*#*#4636#*#*`

#### Laravel Nova License
The admin panel works with [Laravel Nova](https://nova.laravel.com/) and requires a commercial license.
You can still use the project without an admin GUI by querying the MySQL DB or by implementing any other Laravel Admin panel.

If you want to remove Laravel Nova, remove it from `composer.json` before the setup.

### Hardware

#### WiFi device with monitor mode

Any WiFi card that supports monitor mode *should* work. I've tested it with Alfa `AWUSO36NH` and `AWUS036NHA`.

Raspberry Pi 3  embed WiFi card will work when using Re4son kernel:
```sh
wget -O re4son-kernel_current.tar.xz https://re4son-kernel.com/download/re4son-kernel-current/
tar -xJf re4son-kernel_current.tar.xz
cd re4son-kernel_4*
sudo ./install.sh
```

#### Bluetooth device
Built in Raspberry Pi bluetooth works out of the box.

#### SDR device
USB [DVB-T key (RTL2832U)](https://osmocom.org/projects/rtl-sdr/wiki/Rtl-sdr) with antenna (less than 15$) or a [OsmocomBB phone](https://osmocom.org/projects/baseband/wiki/Phones) or [HackRF](https://greatscottgadgets.com/hackrf/).

## Setup

### Server

Copy the `.env.example` into `.env` and set the variables to connect to the database, as well as your Nova License and Docker settings (in case you want to use those).

### Docker

Build and start the container:
```sh
docker compose up -d
```

Prompt a bash into the docker container:
```sh
docker exec -it sigint-app-1 bash
```

Then follow the non-docker setup.

### Non-Docker
For the server, install using [Composer](https://getcomposer.org/):
```sh
composer install
```

Generate a Laravel application key:
```sh
php artisan key:generate
```

And then run the database migrations and seeders:
```sh
php artisan migrate --seed
```

If you're using Laravel Nova, you can create a web user with:
```sh
php artisan nova:user
```

Then you will be able to login using the web panel at `http://127.0.0.1/nova`.

### Stations

First create your station in the DB. If using Nova, you can do that using the web panel.
Otherwise you can manually create that directly from the DB.
Each station have a token that will be used as authentication for the API calls.

Set the server `API_URL` (for example `http://127.0.0.1/api/`) and the `API_KEY` generated in `scripts/.env`.

#### Running
Start monitor mode on your WiFi device: `sudo airmon-ng start wlan1` (requires aircrack-ng) or `sudo iw phy phy0 interface add mon0 type monitor; sudo ifconfig mon0 up`.

Make sure the Bluetooth service is enabled: `sudo systemctl status bluetooth.service`. 
If not, enable it with `sudo systemctl enable bluetooth.service` and `sudo systemctl start bluetooth.service`.
List the Bluetooth interfaces with `bt-adapter -i` (requires `bluez-tools`).

Run those two scripts in a background session (or as a daemons), change the interface if needed:

```sh
cd scripts; 
python bluetooth.py hci0
```

```sh
cd scripts; 
python wifi.py wlan1mon
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
WiFi: 2.4 GHz and 5.0 GHz IEEE 802.11.b/g/n/ac
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
