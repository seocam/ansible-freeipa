# Ansible FreeIPA Test Playbooks

This directory contains a series of playbooks used to test the idempotency of roles and modules provided by ansible-freeipa.

The only requirement to run ansible-freeipa tests it's to have a server with freeipa installed and ansible installed on your machine.

**WARNING**: Don't run those tests in actual server with real data neither on your on machine! It's probably a good idea to use a virtual machine for that.


## Requirements

In order to run the tests you need to have ansible installed on your machine and SSH access to a disposable server with FreeIPA server installed on it.


## Running the tests

To run the tests just execute the playbooks as the example bellow:

```console
$ ansible-playbook -i group/test_group.yml
```


## Setting up testing VMs

To help with the creation and execution of tests we provide a pair of scripts:
`create-test-vm.sh` and `test-vm-ctl.sh`.

### Script Requirements

In order to use those scripts you need to have the KVM hypervisor installed,
along with a few other packages.

In Fedora those packages can be installed using the following command:

```console
sudo dnf -y install genisoimage virt-install libguestfs-tools-c qemu-img libvirt-client wget
```

You will also need to download the `kvm-install-vm` script and place it in your PATH (a suggestion is to place it on `~/.scripts/` directory).
Please download it from it's git repository in https://github.com/giovtorres/kvm-install-vm.

Last but not least, you will need to download cloud images to start your VM from.

There are a few suggestions:

* CentOS Stream 20200113: https://cloud.centos.org/centos/8-stream/x86_64/images/CentOS-Stream-GenericCloud-8-20200113.0.x86_64.qcow2
* CentOS 8.1: https://cloud.centos.org/centos/8/x86_64/images/CentOS-8-GenericCloud-8.1.1911-20200113.3.x86_64.qcow2
* CentOS 7.7: https://cloud.centos.org/centos/7/images/CentOS-7-x86_64-GenericCloud-1907.qcow2.xz
* CentOS 7.6: https://cloud.centos.org/centos/7/images/CentOS-7-x86_64-GenericCloud-1811.qcow2.xz
* CentOS 7.3: https://cloud.centos.org/centos/7/images/CentOS-7-x86_64-GenericCloud-1611.qcow2.xz


### Creating a VM

To create test vms you will need to use `./create-test-vm.sh <cloud-image-localpath> <vm-name>`.

This script will start a VM from a cloud image, perform all basic configuration and then configure an FreeIPA server with DNS support. The whole process should take from 10 to 20 minutes.

This is an example of execution:

```console
./create-test-vm.sh \
    ~/cloud-images/centos8.1/CentOS-8-GenericCloud-8.1.1911-20200113.3.x86_64.qcow2 \
    ipa-centos8.1
```

At the end of the process the script will create a snapshot called `ipa-installed` so will be able to revert to it after tests if you need to.


### Running the tests in the VM

To run the tests you will need to use the script `./test-vm-ctl.sh test <vm-name> <playbook-localpath>`.

Here is an example:

```console
./test-vm-ctl.sh test ipa-centos8.1 group/test_group.yml
```


### Connecting to a VM

While developing is quite helpful to connect to a VM console to debug and make sure everything is working as it should. In order to do that you can use `./test-vm-ctl.sh ssh <vm-name> [<command>]`.

For example to connect to the `ipa-centos8.1`:

```console
./test-vm-ctl.sh ssh ipa-centos8.1
```

You could also execute a command on the server:

```console
./test-vm-ctl.sh ssh ipa-centos8.1 ls /var/log
```


### Reverting to a snapshot

To revert the VM to the snapshot created just after FreeIPA server installation use `./test-vm-ctl.sh restore <vm-name>`.

For example:
```console
./test-vm-ctl.sh restore ipa-centos8.1
```
