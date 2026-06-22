# Build stage
FROM node:20-alpine AS builder
ARG MIRROR

# Copy frontend directory
COPY frontend /opt/frontend

# Build Next.js application
WORKDIR /opt/frontend

# BuildKit must be enabled for --mount=type=cache to work
# Docker 23.0+ has BuildKit enabled by default
# For older versions, set environment variable: DOCKER_BUILDKIT=1
# Or add "features": {"buildkit": true} to ~/.docker/config.json
# Use BuildKit named caches for npm cache and node_modules
# - id=npm-cache: persists across builds, keyed by cache id
# - sharing=locked: allows concurrent access from multiple builds
# Cache will be reused as long as package.json and package-lock.json content don't change
RUN --mount=type=cache,id=npm-cache,target=/root/.npm,sharing=locked \
    --mount=type=cache,id=node-modules,target=/opt/frontend/node_modules,sharing=locked \
    if [ -n "$MIRROR" ]; then npm config set registry "$MIRROR"; fi && \
    npm install --verbose && \
    NODE_ENV=production npm run build && \
    mkdir -p ../frontend-dist && \
    cp -r .next ../frontend-dist/ && \
    cp -r public ../frontend-dist/ && \
    cp server.js ../frontend-dist/server.js && \
    echo '{\
  "name": "nexent",\
  "version": "0.1.0",\
  "private": true,\
  "scripts": {\
    "start": "NODE_ENV=production HOSTNAME=localhost node server.js"\
  },\
  "dependencies": {\
    "next": "15.5.7",\
    "react": "18.2.0",\
    "react-dom": "18.2.0",\
    "http-proxy": "^1.18.1",\
    "dotenv": "^16.4.7",\
    "cookie": "^1.1.1"\
  }\
}' > ../frontend-dist/package.json && \
    cd ../frontend-dist && \
    if [ -n "$MIRROR" ]; then npm config set registry "$MIRROR"; fi && \
    npm install --verbose --omit=dev --production && \
    rm -rf .next/cache

# Production stage
FROM node:20-alpine
ARG APK_MIRROR
LABEL authors="nexent"

# Configure Alpine mirrors if specified
RUN if [ "$APK_MIRROR" = "tsinghua" ]; then \
        echo "https://mirrors.tuna.tsinghua.edu.cn/alpine/latest-stable/main" > /etc/apk/repositories && \
        echo "https://mirrors.tuna.tsinghua.edu.cn/alpine/latest-stable/community" >> /etc/apk/repositories; \
    fi

# Update package index, upgrade busybox first, then install curl
# This avoids trigger script issues in cross-platform builds with QEMU emulation
RUN apk update && \
    apk upgrade --no-cache busybox || true && \
    apk add --no-cache --no-scripts curl

WORKDIR /opt/frontend-dist

# Copy only the necessary files from builder
COPY --from=builder /opt/frontend-dist .

# Expose the service port
EXPOSE 3000

# Start the server
CMD ["npm", "start"]
