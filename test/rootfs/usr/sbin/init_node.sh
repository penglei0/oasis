#!/bin/sh

install_benchmark_profile() {
    profile="$1"
    template="/usr/bin/regular_benchmark_${profile}.sh"
    if [ ! -f "$template" ]; then
        echo "Unknown benchmark profile: $profile" >&2
        exit 2
    fi
    cp "$template" /usr/bin/regular_test.sh
    chmod 755 /usr/bin/regular_test.sh
}

if [ "${1:-}" = "--benchmark-profile" ]; then
    [ -n "${2:-}" ] || { echo "--benchmark-profile requires a profile" >&2; exit 2; }
    install_benchmark_profile "$2"
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
    echo 'PermitRootLogin yes' | tee -a /etc/ssh/sshd_config
    echo 'PasswordAuthentication no' | tee -a /etc/ssh/sshd_config
    echo 'StrictModes no' | tee -a /etc/ssh/sshd_config
    service ssh start
}

init_library() {
    echo "Initializing libraries for the node..."
}

init_ssh
init_library
