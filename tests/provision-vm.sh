#!/bin/bash

source /etc/os-release

# IPA expects the server hostname to be an valid FQDN
sudo hostnamectl set-hostname ipaserver.test.local

sudo yum remove cloud-init -y

if [[ "${ID}" == "centos" ]]; then
    # CentOS 7.x
    if [[ "${VERSION_ID}" == "7" ]]; then
        sudo yum update nss -y
    fi

    # CentOS 7.3
    if rpm -qf /etc/redhat-release | grep centos-release-7-3 -q; then
        sudo yum update dbus -y
        REBOOT="yes"
    fi
fi

sudo touch /etc/provision_ok

if [[ "${REBOOT}" == "yes" ]]; then
    sudo reboot
fi
