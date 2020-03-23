#!/bin/bash

D=~/.vm-disks

VM=ipaserver
GATEWAY=$(ip addr show virbr0 | grep "inet\b" | awk '{print $2}' | cut -d/ -f1)
IP_ADDRESS="${GATEWAY}0"
NAMESERVER=$GATEWAY

FQDN="$VM.test.local"

USERNAME=ipauser
USER_PASSWORD=ipa123
AUTHORIZED_KEY=$(cat ~/.ssh/id_rsa.pub)

#CLOUD_IMAGE="/home/scampos/Downloads/CentOS-Stream-GenericCloud-8-20200113.0.x86_64.qcow2"
CLOUD_IMAGE="$PWD/CentOS-7-x86_64-GenericCloud.qcow2"

MEMORY=1600
VCPUS=1
DISK_SIZE="8.2G"

OS_VARIANT="rhel7"

VM_D="${D}/${VM}"

if [ -d "$VM_D" ]; then
    echo "Directory ${VM_D} already exists. Exiting."
    exit 1
fi

HASHED_PASS=$(mkpasswd --method=SHA-512 --rounds=4096 $USER_PASSWORD)

mkdir -vp "${VM_D}"
cd $VM_D

cat <<EOT >> meta-data
instance-id: $VM
EOT

cat <<EOT >> network-config
version: 2
ethernets:
    eth0:
        addresses:
            - $IP_ADDRESS/24
        gateway4: $GATEWAY
        nameservers:
            addresses: ['$NAMESERVER']
EOT

cat <<EOT >> user-data
#cloud-config

fqdn: $FQDN

users:
    - default
    - name: $USERNAME
      groups: wheel
      shell: /bin/bash
      sudo: ALL=(ALL) NOPASSWD:ALL
      ssh_authorized_keys:
        - $AUTHORIZED_KEY
      passwd: $HASHED_PASS
      lock_passwd: false

# Configure where output will go
output:
    all: ">> /var/log/cloud-init.log"

# Remove cloud-init
runcmd:
    - echo "${IP_ADDRESS} ${FQDN}" >> /etc/hosts
    - systemctl stop network && systemctl start network
    - yum -y remove cloud-init
EOT

cp -v $CLOUD_IMAGE $VM.qcow2

export LIBGUESTFS_BACKEND=direct
qemu-img create -f qcow2 -o preallocation=metadata $VM.new.image $DISK_SIZE

virt-resize --quiet --expand /dev/sda1 $VM.qcow2 $VM.new.image

mv $VM.new.image $VM.qcow2

CIDATA_IMAGE="${VM}-cidata.iso"

genisoimage -o $CIDATA_IMAGE -V cidata -J -r user-data meta-data network-config

virt-install --import --name $VM \
--memory $MEMORY --vcpus $VCPUS --cpu host \
--disk $VM.qcow2,format=qcow2,bus=virtio \
--disk $CIDATA_IMAGE,device=cdrom \
--network bridge=virbr0,model=virtio \
--os-variant=$OS_VARIANT \
--graphics spice \
--noautoconsole

attempts=0
echo "Waiting for VM network..."
while [ 0 ]; do
    ping $IP_ADDRESS -c 3 > /dev/null
    if [[ "$?" == 0 ]]; then
        break
    fi

    attempts=$((attempts+1))
    if [ "$attempts" -gt 50 ]; then
       echo "Could not get VM network working."
       exit 1
    fi
done

echo "${VM} created and running with IP ${IP_ADDRESS}"

virsh change-media $VM $VM_D/$CIDATA_IMAGE --eject

cat <<EOT >> /tmp/ip_address
export VM_IP_ADDRESS=$IP_ADDRESS
EOT
