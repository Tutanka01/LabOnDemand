#!/bin/bash
set -e
apt-get autoremove -y
apt-get clean
rm -rf /var/lib/apt/lists/*