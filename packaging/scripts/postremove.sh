#!/bin/sh
# After removal (and after the old version is gone during an upgrade).

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
