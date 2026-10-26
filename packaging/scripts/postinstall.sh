#!/bin/sh
# After installation and after each upgrade.

# The NetworkManager rule only covers devices NetworkManager meets from now
# on. Bridges and VM interfaces it already took (shown "connected
# (externally)" in the applet) are released, and profiles left on them go.
hide_kvm_studio_interfaces() {
    command -v nmcli >/dev/null 2>&1 || return 0
    for device in $(nmcli -g DEVICE device status 2>/dev/null); do
        case "$device" in
            kvmnet* | ks-* | vnet*) nmcli device set "$device" managed no >/dev/null 2>&1 || : ;;
        esac
    done
    for uuid in $(nmcli -g UUID connection show 2>/dev/null); do
        name=$(nmcli -g connection.interface-name connection show "$uuid" 2>/dev/null)
        case "$name" in
            kvmnet* | ks-* | vnet*) nmcli connection delete "$uuid" >/dev/null 2>&1 || : ;;
        esac
    done
}

# Installed as a dependency, the libvirt daemons of Fedora have their sockets
# enabled but not started until the next boot. Started here, only if enabled
# and not running yet: a running daemon is never restarted.
start_libvirt_sockets() {
    for daemon in virtqemud virtnetworkd virtstoraged virtnodedevd virtsecretd virtinterfaced virtnwfilterd virtlogd virtlockd; do
        if systemctl is-enabled --quiet "$daemon.socket" 2>/dev/null &&
            ! systemctl is-active --quiet "$daemon.socket"; then
            systemctl start "$daemon.socket" || :
        fi
    done
}

if [ -d /run/systemd/system ]; then
    systemctl daemon-reload || :
    start_libvirt_sockets
    udevadm control --reload 2>/dev/null || :
    systemctl enable --now kvmstudio-helper.socket || :
    # Writes the port forwarding table at boot and after nftables, firewalld
    # or libvirt restart; restarted here so the new code applies it.
    systemctl enable kvmstudio-forwards.service || :
    systemctl restart kvmstudio-forwards.service || :
    # A helper already running keeps the old code until restarted.
    systemctl try-restart kvmstudio-helper.service || :
    if systemctl is-active --quiet NetworkManager.service; then
        systemctl reload NetworkManager.service || :
        hide_kvm_studio_interfaces
    fi
fi

if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    firewall-cmd --reload >/dev/null 2>&1 || :
fi

exit 0
