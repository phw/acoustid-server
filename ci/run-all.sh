#!/usr/bin/env bash

set -ex

cd $(dirname $0)

docker-compose build --build-arg=jenkins_uid=$(id -u) tests
docker-compose run tests

docker-compose down
