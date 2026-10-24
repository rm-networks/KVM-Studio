#!/bin/sh
# After removal (and after the old version is gone during an upgrade).

# A real removal leaves no file behind: rpm keeps an edited helper.toml as
# .rpmsave, dpkg keeps it until purge.
case "$1" in
    0 | purge)
        rm -f /etc/kvm-studio/helper.toml.rpmsave /etc/kvm-studio/helper.toml
        rmdir /etc/kvm-studio 2>/dev/null || :
        ;;
esac

if [ -d /run/systemd/system ]; then
    systemctl daemon-reload || :
    if systemctl is-active --quiet NetworkManager.service; then
        systemctl reload NetworkManager.service || :
    fi
fi

if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    firewall-cmd --reload >/dev/null 2>&1 || :
fi

exit 0
