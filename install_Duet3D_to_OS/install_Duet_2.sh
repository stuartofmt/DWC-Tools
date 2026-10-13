#!/bin/bash

yes | sudo apt-get install duetsoftwareframework
 
# enable Duet Control Server
sudo systemctl enable duetcontrolserver
sudo systemctl start duetcontrolserver
 
# enable Duet Web Server
sudo systemctl enable duetwebserver
sudo systemctl start duetwebserver
 
# enable Duet Plugin Services
sudo systemctl enable duetpluginservice  
sudo systemctl enable duetpluginservice-root
sudo systemctl start duetpluginservice  
sudo systemctl start duetpluginservice-root
 
echo "Reboot reuired"
 
