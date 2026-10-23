FROM node:20-alpine AS builder
ARG MIRROR
ARG TARGETARCH

WORKDIR /app
COPY doc/package.json ./package.json

RUN --mount=type=cache,id=nexent-docs-npm-${TARGETARCH},target=/root/.npm,sharing=locked \
    if [ -n "$MIRROR" ]; then npm config set registry "$MIRROR"; fi && \
    npm install --verbose

COPY doc .

RUN \
    npm run docs:build

FROM nginx:1.27-alpine
ARG APK_MIRROR

RUN if [ "$APK_MIRROR" = "tsinghua" ]; then \
        echo "https://mirrors.tuna.tsinghua.edu.cn/alpine/latest-stable/main" > /etc/apk/repositories && \
        echo "https://mirrors.tuna.tsinghua.edu.cn/alpine/latest-stable/community" >> /etc/apk/repositories; \
    fi && \
    printf '%s\n' \
        'server {' \
        '    listen 4173;' \
        '    server_name _;' \
        '    root /usr/share/nginx/html;' \
        '    index index.html;' \
        '    location / {' \
        '        try_files $uri $uri/ /index.html;' \
        '    }' \
        '}' > /etc/nginx/conf.d/default.conf

COPY --from=builder /app/docs/.vitepress/dist /usr/share/nginx/html

EXPOSE 4173

HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD wget -q --spider http://localhost:4173/ || exit 1
