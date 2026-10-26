#!/bin/sh
# Run after installing the package: the backend imports with the distribution's
# Python packages, passes its check and answers on /api/health in web mode.
set -eu
dir=$(mktemp -d)
export HOME="$dir" XDG_CONFIG_HOME="$dir/config"
printf '[libvirt]\nuri = "test:///default"\n\n[web]\nport = 60080\n' > "$dir/config.toml"

kvm-studio --version
kvm-studio --config "$dir/config.toml" --check
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/opt/kvm-studio/lib:/opt/kvm-studio/vendor python3 -c \
    "import kvmstudio.app, kvmstudio.auth.guest, kvmstudio.shell.web, kvmstudio.shell.desktop"

kvm-studio --config "$dir/config.toml" --mode web --no-browser > "$dir/log" 2>&1 &
pid=$!
ok=0
for _ in $(seq 60); do
    if python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:60080/api/health', timeout=1)" 2>/dev/null; then
        ok=1
        break
    fi
    sleep 0.5
done
kill "$pid" 2>/dev/null || true
wait "$pid" || true
cat "$dir/log"
rm -rf "$dir"
if [ "$ok" != 1 ]; then
    echo "the backend did not answer on /api/health" >&2
    exit 1
fi
echo "backend answered on /api/health"
