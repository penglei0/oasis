#!/bin/sh

set -u

usr_sbin_dir="${OASIS_USR_SBIN_DIR:-/usr/sbin}"
ln -sfn install_regular_benchmark_profile.sh "${usr_sbin_dir}/install_benchmark_profile.sh"

node_init_marker="${OASIS_RUNTIME_DIR:-/run/oasis}/node_initialized"
mkdir -p "$(dirname "$node_init_marker")"
if [ -f "$node_init_marker" ]; then
    echo "Node common initialization already completed; skipping."
    exit 0
fi

# This script is executed by the init process of each node in the network.
init_ssh() {
    echo "Initializing SSH for the node..."
    rm -rf /root/.ssh/
    mkdir -p /root/.ssh
    cp /root/oasis/test/keys/* /root/.ssh/
    cp /root/.ssh/id_rsa.pub /root/.ssh/authorized_keys
    # fix: Permissions 0644 for '/root/.ssh/id_rsa' are too open
    chmod 600 /root/.ssh/id_rsa
    chmod 600 /root/.ssh/id_rsa.pub
    ensure_sshd_config 'PermitRootLogin yes'
    ensure_sshd_config 'PasswordAuthentication no'
    ensure_sshd_config 'StrictModes no'
    service ssh start
}

ensure_sshd_config() {
    setting="$1"
    grep -qxF "$setting" /etc/ssh/sshd_config || printf '%s\n' "$setting" >> /etc/ssh/sshd_config
}

init_library() {
    echo "Initializing libraries for the node..."
}

init_ssh
init_library
printf '%s\n' "initialized" > "$node_init_marker"
