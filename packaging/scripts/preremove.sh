#!/bin/sh
# Before removal. rpm passes 0 on removal and 1 on upgrade, deb passes
# "remove" or "upgrade": only a real removal cleans up.
case "$1" in
    0 | remove) ;;
    *) exit 0 ;;
esac

if [ -d /run/systemd/system ]; then
    systemctl disable --now kvmstudio-helper.socket kvmstudio-helper.service || :
fi

# Close the LAN sharing port in every zone where it was opened.
if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    for zone in $(firewall-cmd --get-zones); do
        if firewall-cmd --permanent --zone="$zone" --query-service=kvm-studio >/dev/null 2>&1; then
            firewall-cmd --permanent --zone="$zone" --remove-service=kvm-studio >/dev/null 2>&1 || :
        fi
    done
fi

exit 0
