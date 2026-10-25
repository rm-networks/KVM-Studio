#!/bin/sh
# Before removal. rpm passes 0 on removal and 1 on upgrade, deb passes
# "remove" or "upgrade": only a real removal cleans up.
case "$1" in
    0 | remove) ;;
    *) exit 0 ;;
esac

# Only the package files go: virtual machines, kvmnet networks and settings stay.
case "${LANG:-}" in
    fr*) echo "@APP_NAME@ : VMs, réseaux kvmnet et réglages conservés. Pour les retirer aussi, utilisez « Désinstaller @APP_NAME@ » dans le menu des applications." ;;
    *) echo "@APP_NAME@: virtual machines, kvmnet networks and settings are kept. To remove them too, use \"Uninstall @APP_NAME@\" in the applications menu." ;;
esac

if [ -d /run/systemd/system ]; then
    systemctl disable --now kvmstudio-helper.socket kvmstudio-helper.service || :
    systemctl disable kvmstudio-forwards.service || :
fi

# Access rights the helper gave QEMU on ISO libraries: only those it added.
/opt/kvm-studio/bin/kvmstudio-helper --clear-state || :

# Close the LAN sharing port in every zone where it was opened.
if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    for zone in $(firewall-cmd --get-zones); do
        if firewall-cmd --permanent --zone="$zone" --query-service=kvm-studio >/dev/null 2>&1; then
            firewall-cmd --permanent --zone="$zone" --remove-service=kvm-studio >/dev/null 2>&1 || :
        fi
    done
fi

exit 0
