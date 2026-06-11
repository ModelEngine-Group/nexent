# 使用轻量级的 Nginx Alpine 镜像
FROM nginx:alpine

# 安装 openssl 以生成证书
RUN apk add --no-cache openssl

# 创建存放证书的目录
RUN mkdir -p /etc/nginx/ssl

# 生成自签名证书
# -nodes: 不对私钥加密
# -subj: 设置证书信息（CN 处填写你的域名）
RUN openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/nginx/ssl/nginx.key \
    -out /etc/nginx/ssl/nginx.crt \
    -subj "/C=CN/ST=Default/L=Default/O=Default/CN=your-domain.com"

# 删除默认配置，复制我们自定义的配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 暴露 80 和 443 端口
EXPOSE 80 443

# 启动 Nginx
CMD ["nginx", "-g", "daemon off;"]