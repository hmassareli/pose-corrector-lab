#!/bin/sh
set -eu
cd /opt/corner-boxing
docker build -t corner-boxing-relay:20261001 .
docker service create --name corner-boxing-relay --network easypanel \
  --limit-memory 128m --limit-cpu 0.5 --replicas 1 \
  --label traefik.enable=true \
  --label 'traefik.http.routers.corner-relay-http.entrypoints=http' \
  --label 'traefik.http.routers.corner-relay-http.rule=Host(`corner-relay.lnyx9r.easypanel.host`)' \
  --label 'traefik.http.routers.corner-relay-http.middlewares=redirect-to-https' \
  --label 'traefik.http.routers.corner-relay-https.entrypoints=https' \
  --label 'traefik.http.routers.corner-relay-https.rule=Host(`corner-relay.lnyx9r.easypanel.host`)' \
  --label 'traefik.http.routers.corner-relay-https.tls.certresolver=letsencrypt' \
  --label 'traefik.http.routers.corner-relay-https.tls.domains[0].main=corner-relay.lnyx9r.easypanel.host' \
  --label 'traefik.http.services.corner-relay.loadbalancer.server.port=8790' \
  corner-boxing-relay:20261001
