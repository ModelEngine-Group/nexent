# Build stage
FROM node:20-alpine AS builder
ARG MIRROR
ARG TARGETARCH

# Build Next.js application
WORKDIR /opt/frontend
COPY frontend/package.json ./package.json

# Use BuildKit named cache for npm downloads across builds.
RUN --mount=type=cache,id=nexent-web-npm-${TARGETARCH},target=/root/.npm,sharing=locked \
    if [ -n "$MIRROR" ]; then npm config set registry "$MIRROR"; fi && \
    npm install --verbose

COPY frontend /opt/frontend

RUN --mount=type=cache,id=nexent-web-next-${TARGETARCH},target=/opt/frontend/.next/cache,sharing=locked \
    NODE_ENV=production npm run build && \
    mkdir -p ../frontend-dist && \
    cp -r .next/standalone/. ../frontend-dist/ && \
    mkdir -p ../frontend-dist/.next && \
    cp -r .next/static ../frontend-dist/.next/static && \
    cp -r public ../frontend-dist/ && \
    cp server.js ../frontend-dist/server.js && \
    mkdir -p ../frontend-dist/node_modules/next/dist/compiled && \
    cp -r node_modules/next/dist/compiled/. ../frontend-dist/node_modules/next/dist/compiled/ && \
    mkdir -p ../frontend-dist/node_modules && \
    cp -r \
        node_modules/cookie \
        node_modules/dotenv \
        node_modules/eventemitter3 \
        node_modules/follow-redirects \
        node_modules/http-proxy \
        node_modules/requires-port \
        node_modules/multiparty \
        node_modules/safe-buffer \
        node_modules/http-errors \
        node_modules/depd \
        node_modules/uid-safe \
        node_modules/random-bytes \
        node_modules/inherits \
        node_modules/statuses \
        node_modules/toidentifier \
        node_modules/setprototypeof \
        ../frontend-dist/node_modules/ && \
    rm -rf ../frontend-dist/.next/cache

# Production stage
FROM node:20-alpine
ARG APK_MIRROR
ARG TARGETARCH
LABEL authors="nexent"

# Configure Alpine mirrors if specified
RUN if [ "$APK_MIRROR" = "tsinghua" ]; then \
        echo "https://mirrors.tuna.tsinghua.edu.cn/alpine/latest-stable/main" > /etc/apk/repositories && \
        echo "https://mirrors.tuna.tsinghua.edu.cn/alpine/latest-stable/community" >> /etc/apk/repositories; \
    fi

# Update package index, upgrade busybox first, then install curl
# This avoids trigger script issues in cross-platform builds with QEMU emulation
RUN --mount=type=cache,id=nexent-web-apk-${TARGETARCH},target=/var/cache/apk,sharing=locked \
    mkdir -p /var/cache/apk && \
    apk update && \
    (apk upgrade busybox || true) && \
    apk add --no-scripts curl

WORKDIR /opt/frontend-dist

# Copy only the necessary files from builder
COPY --from=builder /opt/frontend-dist .

ENV NODE_ENV=production
ENV HOSTNAME=localhost

# Expose the service port
EXPOSE 3000

# Start the server
CMD ["node", "server.js"]
