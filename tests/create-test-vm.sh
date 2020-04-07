#!/bin/bash

DISTRO_NAME="$1"
VM_NAME="$2"

set -e

red() { echo -e "\e[31m$@\e[0m" ; }
green() { echo -e "\e[32m$@\e[0m" ; }
die() { red "ERR: $@" >&2 ; exit 2 ; }
ok() { green "${@:-OK}" ; }

wait_until_provision_ends() {
    local ip=$1
    echo -en "- Waiting provision script finish ... "
    until ssh_vm $ip test -f /etc/provision_ok; do
        sleep 1
    done
    ok
}

wait_for_ssh() {
    local ip=$1
    echo -en "- Waiting for ssh to be ready ... "
    until ssh_vm $ip echo -n 2> /dev/null ; do
        sleep 1
    done
    ok
}

get_vm_ip() {
    echo -en "- Waiting for network to be available ... "
    local vm_name="$1"

    IP_ADDRESS=

    local attempts=0
    while [[ "$IP_ADDRESS" == "" ]]; do
        IP_ADDRESS=$(virsh domifaddr $vm_name --source=arp | grep ipv4 | awk '{ print $4 }' | cut -d"/" -f1)
        sleep 2
        attempts=$((attempts+1))
        if [ "$attempts" -gt 150 ]; then  # wait up to 300 seconds (5 minutes)
            die "Couldnt't find IP address for ${vm_name}"
            exit 1
        fi
    done
    ok
}

ssh_vm() {
    local ip=$1
    shift 1
    local cmd=$@
    ssh $ip \
        -o StrictHostKeyChecking=no \
        -o LogLevel=ERROR \
        $cmd
}

get_inventory_file() {
    local ip=$1
    INVENTORY_FILE="/tmp/inventory-${ip}"

    cat <<EOT > $INVENTORY_FILE
    [ipaserver]
    ipaserver.test.local ansible_host=$ip ansible_ssh_extra_args='-o StrictHostKeyChecking=no'

    [ipaserver:vars]
    ipaserver_setup_dns=yes
    ipaserver_auto_forwarders=yes
    ipaadmin_password=SomeADMINpassword
    ipadm_password=SomeDMpassword
    ipaserver_domain=test.local
    ipaserver_realm=TEST.LOCAL
EOT
}

shutdown_vm() {
    local vm_name=$1

    echo -en "- Shutting down $vm_name ... "
    virsh shutdown $vm_name > /dev/null 2>&1 || die "Could not shutdown domain"

    while virsh list --state-running | grep -q "$vm_name"; do
       sleep 0.5
    done
    sleep 1
    ok
}

eject_ci_data() {
    local vm_name=$1
    device_name=$(virsh domblklist $vm_name | grep "cidata.iso" | awk '{ print $1 }')
    virsh change-media $vm_name $device_name --eject
}

main() {
    kvm-install-vm create \
        -t $DISTRO_NAME \
        -c 2 \
        -m 2048 \
        -s $PWD/provision-vm.sh \
        -D "test.local" \
        $VM_NAME

    get_vm_ip $VM_NAME

    wait_until_provision_ends $IP_ADDRESS

    export ANSIBLE_ROLES_PATH="$PWD/../roles"

    get_inventory_file $IP_ADDRESS

    ansible-playbook \
        -i $INVENTORY_FILE ../playbooks/install-server.yml \
        --ssh-extra-args='-o StrictHostKeyChecking=no'

    eject_ci_data $VM_NAME
    shutdown_vm $VM_NAME

    echo -en "- Creating snapshot 'ipa-installed' ... "
    virsh snapshot-create-as $VM_NAME --name "ipa-installed"
    ok

    echo "$VM_NAME provisioned with FreeIPA server."
}

(return 0 2>/dev/null) || main $@
