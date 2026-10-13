#!/bin/bash

echo "options spidev bufsiz=8192" | sudo tee /etc/modprobe.d/spidev.conf
 
yes | sudo wget -q https://pkg.duet3d.com/duet3d.gpg 
yes | sudo wget -q https://pkg.duet3d.com/duet3d.list
sudo mv duet3d.gpg /etc/apt/trusted.gpg.d/
sudo mv duet3d.list /etc/apt/sources.list.d/duet3d.list
sudo chown root:root /etc/apt/trusted.gpg.d/duet3d.gpg
sudo chown root:root /etc/apt/sources.list.d/duet3d.list
 
# If am using the python bindings for DSF so they can be installed omitted here
# yes | sudo apt-get install python3-dsf-python apt-transport-https

yes | sudo apt-get update
yes | sudo apt-get upgrade

echo "Reboot Required"
