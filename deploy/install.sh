#!/bin/sh
# Install or update wow as a system service on the Pi (3A AD-13, AD-14).
#
#     sudo deploy/install.sh
#
# Run from the repository, after `uv sync --frozen` and with the built
# display in src/wow/web/static/. Builds the wheel, installs it with the
# locked dependencies into /opt/wow/venv, creates the user wow and
# /var/lib/wow, copies /etc/wow/wow.toml once, and (re)starts wow.service.
set -eu

cd "$(dirname "$0")/.."
if [ "$(id -u)" -ne 0 ]; then
    echo "run with sudo" >&2
    exit 1
fi
UV="${UV:-$(command -v uv || echo "/home/${SUDO_USER:-root}/.local/bin/uv")}"
if [ ! -f src/wow/web/static/index.html ]; then
    echo "src/wow/web/static/index.html missing: build or copy the display first" >&2
    exit 1
fi

id wow >/dev/null 2>&1 || useradd --system --home-dir /var/lib/wow \
    --shell /usr/sbin/nologin --groups bluetooth wow
install -d -o wow -g wow -m 0750 /var/lib/wow
# The API key and the TLS key: readable by wow only (APP-817, T-SYS-05).
[ ! -d /var/lib/wow/tls ] || chown -R wow:wow /var/lib/wow/tls
[ ! -d /var/lib/wow/tls ] || chmod 0750 /var/lib/wow/tls
for secret in /var/lib/wow/secrets.json /var/lib/wow/tls/server.key; do
    if [ -f "$secret" ]; then
        chown wow:wow "$secret"
        chmod 0600 "$secret"
    fi
done
install -d -m 0755 /etc/wow /opt/wow
[ -f /etc/wow/wow.toml ] || install -m 0644 deploy/wow.pi.toml /etc/wow/wow.toml

rm -rf dist
"$UV" build --wheel --out-dir dist
"$UV" export --frozen --no-dev --no-emit-project -o /opt/wow/requirements.txt
[ -x /opt/wow/venv/bin/python ] || "$UV" venv --python /usr/bin/python3.13 /opt/wow/venv
"$UV" pip install --python /opt/wow/venv/bin/python -r /opt/wow/requirements.txt
"$UV" pip install --python /opt/wow/venv/bin/python --reinstall --no-deps dist/*.whl
chown -R "${SUDO_USER:-root}" dist

install -m 0644 deploy/wow.service /etc/systemd/system/wow.service
systemctl daemon-reload
systemctl enable wow.service
systemctl restart wow.service
systemctl --no-pager --lines=5 status wow.service
