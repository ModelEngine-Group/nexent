# Build stage
FROM node:20-alpine AS builder
ARG MIRROR

# Copy frontend directory
COPY frontend /opt/frontend

# Build Next.js application
WORKDIR /opt/frontend
RUN if [ -n "$MIRROR" ]; then npm config set registry "$MIRROR"; fi && \
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
    "next": "15.4.5",\
    "react": "18.2.0",\
    "react-dom": "18.2.0",\
    "http-proxy": "^1.18.1",\
    "dotenv": "^16.4.7"\
  }\
}' > ../frontend-dist/package.json && \
    cd ../frontend-dist && \
    if [ -n "$MIRROR" ]; then npm config set registry "$MIRROR"; fi && \
    npm install --verbose --omit=dev --production && \
    npm cache clean --force && \
    rm -rf /root/.npm && \
    rm -rf /root/.cache && \
    rm -rf .next/cache

# Production stage
FROM node:20-alpine
LABEL authors="nexent"

RUN echo "https://mirrors.tuna.tsinghua.edu.cn/alpine/latest-stable/main" > /etc/apk/repositories && \
    echo "https://mirrors.tuna.tsinghua.edu.cn/alpine/latest-stable/community" >> /etc/apk/repositories && \
    apk add --no-cache curl

WORKDIR /opt/frontend-dist

# Copy only the necessary files from builder
COPY --from=builder /opt/frontend-dist .

# Expose the service port
EXPOSE 3000

# Start the server
CMD ["npm", "start"]
