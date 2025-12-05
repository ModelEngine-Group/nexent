# Build stage
FROM node:20-alpine AS builder
ARG MIRROR

# Copy frontend directory
COPY frontend /opt/frontend

# Build Next.js application
WORKDIR /opt/frontend
# Configure npm with increased timeout and retry settings
RUN if [ -n "$MIRROR" ]; then npm config set registry "$MIRROR"; fi && \
    npm config set fetch-timeout 600000 && \
    npm config set fetch-retries 5 && \
    npm config set fetch-retry-mintimeout 20000 && \
    npm config set fetch-retry-maxtimeout 120000

# Install dependencies with retry mechanism
RUN npm install --verbose || \
    (echo "First install attempt failed, retrying..." && sleep 5 && npm install --verbose) || \
    (echo "Second install attempt failed, retrying..." && sleep 10 && npm install --verbose)

# Build Next.js with increased timeout and memory
# Set environment variables for Next.js build
# Add retry mechanism for network timeouts during build (e.g., Google Fonts loading)
RUN NODE_ENV=production \
    NODE_OPTIONS="--max-old-space-size=4096" \
    NEXT_TELEMETRY_DISABLED=1 \
    (npm run build || \
     (echo "Build failed, retrying after 10 seconds..." && sleep 10 && npm run build) || \
     (echo "Second build attempt failed, retrying after 20 seconds..." && sleep 20 && npm run build))

# Prepare production distribution
RUN mkdir -p ../frontend-dist && \
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
    "next": "15.4.5",\
    "react": "18.2.0",\
    "react-dom": "18.2.0",\
    "http-proxy": "^1.18.1",\
    "dotenv": "^16.4.7"\
  }\
}' > ../frontend-dist/package.json

# Install production dependencies with retry mechanism
WORKDIR /opt/frontend-dist
RUN if [ -n "$MIRROR" ]; then npm config set registry "$MIRROR"; fi && \
    npm config set fetch-timeout 600000 && \
    npm config set fetch-retries 5 && \
    npm config set fetch-retry-mintimeout 20000 && \
    npm config set fetch-retry-maxtimeout 120000 && \
    (npm install --verbose --omit=dev --production || \
     (echo "First install attempt failed, retrying..." && sleep 5 && npm install --verbose --omit=dev --production) || \
     (echo "Second install attempt failed, retrying..." && sleep 10 && npm install --verbose --omit=dev --production)) && \
    npm cache clean --force && \
    rm -rf /root/.npm && \
    rm -rf /root/.cache && \
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
