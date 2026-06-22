# 使用 Node.js 18 作为基础镜像
FROM node:18-alpine
ARG MIRROR

WORKDIR /app

# 复制文档项目
COPY doc .

# 安装系统依赖
RUN apk add --no-cache wget

# 安装依赖并构建
RUN npm add -D vitepress && \
    npm run docs:build

# 暴露端口
EXPOSE 4173

# 设置健康检查
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:4173/ || exit 1

# 启动 VitePress 预览服务（服务构建后的静态文件）
CMD ["npm", "run", "docs:preview", "--", "--host", "0.0.0.0", "--port", "4173"]