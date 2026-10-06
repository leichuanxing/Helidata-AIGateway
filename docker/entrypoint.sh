#!/bin/bash
set -Eeuo pipefail
umask 027
mkdir -p /data/{postgres,redis,uploads,logs,backup,config} /run/postgresql
mkdir -p /data/logs/call-log-outbox /data/logs/compliance-outbox
chown root:gateway /data/logs
chmod 750 /data/logs
chown gateway:gateway /data/logs/call-log-outbox /data/logs/compliance-outbox
chmod 700 /data/logs/call-log-outbox /data/logs/compliance-outbox
mkdir -p /data/backup/manual
chown root:gateway /data/backup /data/uploads
chmod 750 /data/backup /data/uploads
chown gateway:gateway /data/backup/manual
chmod 700 /data/backup/manual
chmod 711 /data
chown postgres:postgres /data/postgres /run/postgresql
chown redis:redis /data/redis
chmod 700 /data/postgres /data/redis
python -m app.core.config
python -m app.services.render_runtime
chown root:gateway /data/config /data/config/config.yaml
chmod 750 /data/config
chmod 640 /data/config/config.yaml

if [ ! -s /data/postgres/PG_VERSION ]; then
  runuser -u postgres -- initdb -D /data/postgres --auth-local=peer --auth-host=scram-sha-256 --encoding=UTF8 --locale=C.UTF-8
  printf "\nlisten_addresses = '127.0.0.1'\nunix_socket_directories = '/run/postgresql'\n" >> /data/postgres/postgresql.conf
fi

cleanup() {
  runuser -u postgres -- pg_ctl -D /data/postgres -m fast -w stop || true
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
runuser -u postgres -- pg_ctl -D /data/postgres -l /data/postgres/bootstrap.log -w -t 60 start
runuser -u postgres -- /usr/local/bin/python -m app.services.provision_database
alembic upgrade head
python -m app.services.provider_crypto
chown root:gateway /data/config/provider-encryption.key
chmod 640 /data/config/provider-encryption.key
python -m app.services.bootstrap
cleanup
trap - EXIT TERM INT
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
