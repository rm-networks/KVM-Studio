#!/bin/sh
# After installation and after each upgrade.

if [ -d /run/systemd/system ]; then
    systemctl daemon-reload || :
    systemctl enable --now kvmstudio-helper.socket || :
    # A helper already running keeps the old code until restarted.
    systemctl try-restart kvmstudio-helper.service || :
    if systemctl is-active --quiet NetworkManager.service; then
        systemctl reload NetworkManager.service || :
    fi
fi

if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    firewall-cmd --reload >/dev/null 2>&1 || :
fi

exit 0
