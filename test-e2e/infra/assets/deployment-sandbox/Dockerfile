FROM docker:27-dind
RUN apk add --no-cache bash curl openssl python3 git coreutils findutils util-linux sudo lsof iproute2
# Never mount a host socket or live data; test creates an ephemeral outer container.
