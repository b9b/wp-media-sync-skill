#!/usr/bin/env bash
set -euo pipefail

mkdir -p /run/sshd /root/.ssh
chmod 700 /root/.ssh

if [[ -f /tmp/wp-media-sync/id_ed25519.pub ]]; then
  cp /tmp/wp-media-sync/id_ed25519.pub /root/.ssh/authorized_keys
  chmod 600 /root/.ssh/authorized_keys
fi

ssh-keygen -A >/dev/null
sed -ri 's/^#?PermitRootLogin .*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sed -ri 's/^#?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config

/usr/sbin/sshd

exec docker-entrypoint.sh "$@"
