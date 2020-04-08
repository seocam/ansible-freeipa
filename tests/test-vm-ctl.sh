#!/bin/bash

. create-test-vm.sh

set +e

SUBCOMMAND=$1
VM_NAME=$2
shift 2
ALL_OTHER_ARGS=$@

check_if_vm_exists() {
    local escaped_vm_name="\\${VM_NAME}\\b"
    if ! virsh list --name --all | grep $escaped_vm_name -q; then
        die "VM '$VM_NAME' doesn't exist."
    fi
}

start_if_not_running() {
    local escaped_vm_name="\\${VM_NAME}\\b"
    if ! virsh list --name | grep $escaped_vm_name -q; then
        echo -n "- Starting $VM_NAME ... "
        virsh start $VM_NAME > /dev/null
        [[ $? ]] && ok
    fi
}

wait_until_ready() {
    check_if_vm_exists
    start_if_not_running
    get_vm_ip $VM_NAME  # sets the variable $IP_ADDRESS
    wait_for_ssh $IP_ADDRESS
}

restore() {
    local escaped_vm_name="\\${VM_NAME}\\b"
    if virsh list --name | grep $escaped_vm_name -q; then
        shutdown_vm $VM_NAME
    fi

    echo -n "- Reverting $VM_NAME to snapshot \"ipa-installed\" ... "
    virsh snapshot-revert $VM_NAME --snapshotname ipa-installed --running
    ok
}

run_tests() {
    get_inventory_file $IP_ADDRESS  # sets the variable #INVENTORY_FILE
    echo "Executing tests on $IP_ADDRESS ... "
    ansible-playbook -i $INVENTORY_FILE $*
}


if [[ $VM_NAME == "" ]]; then
    die "VM_NAME must be given"
fi


case $SUBCOMMAND in
    restore )
        check_if_vm_exists
        restore
    ;;
    test )
        wait_until_ready
        run_tests $ALL_OTHER_ARGS
    ;;
    ssh )
        wait_until_ready
        ssh_vm $IP_ADDRESS $ALL_OTHER_ARGS
    ;;
esac
