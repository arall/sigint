#!/bin/bash

INTERFACE=${interface:-wlan0mon}

while [ $# -gt 0 ]; do
   if [[ $1 == *"--"* ]]; then
        param="${1/--/}"
        declare $param="$2"
   fi
  shift
done

echo $INTERFACE

# channel hop every 2 seconds
channel_hop() {

	IEEE80211bg="1 2 3 4 5 6 7 8 9 10 11"
	IEEE80211bg_intl="$IEEE80211b 12 13 14"
	IEEE80211a="36 40 44 48 52 56 60 64 149 153 157 161"
	IEEE80211bga="$IEEE80211bg $IEEE80211a"
	IEEE80211bga_intl="$IEEE80211bg_intl $IEEE80211a"

	while true ; do
		for CHAN in $IEEE80211bg ; do
			echo "sudo iwconfig $INTERFACE channel $CHAN"
			sudo iwconfig $INTERFACE channel $CHAN
			sleep 2
		done
	done
}

channel_hop &