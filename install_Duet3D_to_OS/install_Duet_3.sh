#!/bin/bash

# delete current DSF SD folders
# copy the Duet SD backup to the DSF folder
# change ownership

#sys files
sudo rm -r /opt/dsf/sd/sys
sudo cp -r /home/stuart/Downloads/Duet/sd/sys /opt/dsf/sd/sys
sudo chmod -R 775 /opt/dsf/sd/sys
sudo chown -R dsf:dsf /opt/dsf/sd/sys

#macro files
sudo rm -r /opt/dsf/sd/macros
sudo cp -r /home/stuart/Downloads/Duet/sd/macros /opt/dsf/sd/macros
sudo chmod -R 775 /opt/dsf/sd/macros
sudo chown -R dsf:dsf /opt/dsf/sd/macros

echo "Reboot required"

