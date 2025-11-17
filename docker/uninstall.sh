#!/bin/bash

docker rm -f nexent
docker rm -f nexent-postgresql
docker rm -f nexent-minio
docker rm -f nexent-elasticsearch
docker rm -f nexent-data-process
docker rm -f nexent-web
docker rm -f nexent-redis
docker rm -f supabase-kong-mini
docker rm -f supabase-auth-mini
docker rm -f supabase-db-mini
docker network rm nexent_nexent