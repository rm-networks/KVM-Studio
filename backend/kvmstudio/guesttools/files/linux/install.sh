#!/bin/sh
# KVM Studio guest tools for Linux: qemu-guest-agent (lets KVM Studio see the
# guest) and spice-vdagent (copy and paste with the host).
set -e

if [ "$(id -u)" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
        exec sudo sh "$0" "$@"
    elif command -v pkexec >/dev/null 2>&1; then
        exec pkexec sh "$0" "$@"
    fi
    echo "Root password:"
    exec su root -c "sh '$0'"
fi

packages="qemu-guest-agent spice-vdagent"
if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y $packages
elif command -v dnf >/dev/null 2>&1; then
    dnf install -y $packages
elif command -v zypper >/dev/null 2>&1; then
    zypper --non-interactive install $packages
elif command -v pacman >/dev/null 2>&1; then
    pacman -S --needed --noconfirm $packages
else
    echo "No supported package manager found (apt, dnf, zypper, pacman)." >&2
    exit 1
fi

if command -v systemctl >/dev/null 2>&1; then
    # On Debian the agent unit is static: started, not enabled.
    systemctl enable --now qemu-guest-agent 2>/dev/null || systemctl start qemu-guest-agent || true
    systemctl enable --now spice-vdagentd.socket 2>/dev/null \
        || systemctl enable --now spice-vdagentd 2>/dev/null || true
fi

echo
echo "Guest tools installed. Sign out and back in for copy and paste to work."
