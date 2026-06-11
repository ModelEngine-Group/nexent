# Nginx 离线部署指南

本指南说明如何在 x86 和 ARM 架构下构建并离线部署 Nginx 反向代理。

## 构建镜像

```bash
cd nexent/make/nginx

# x86_64 架构
docker build --platform linux/amd64 -t nexent-nginx:amd64 .

# ARM64 架构（如 Apple Silicon、Raspberry Pi 4/5）
docker build --platform linux/arm64 -t nexent-nginx:arm64 .

# ARMv7 架构（如 Raspberry Pi 3）
docker build --platform linux/arm/v7 -t nexent-nginx:armv7 .
```

## 导出镜像

```bash
# 导出为 tar 文件
docker save -o nexent-nginx-amd64.tar nexent-nginx:amd64

# ARM64 版本
docker save -o nexent-nginx-arm64.tar nexent-nginx:arm64
```

## 离线部署

将 tar 文件拷贝到目标机器后加载：

```bash
# 加载镜像
docker load -i nexent-nginx-amd64.tar

# 确认加载成功
docker images | grep nexent-nginx
```

## 配置 SSL 证书

默认使用自签名证书。如需自定义域名，修改 Dockerfile 第 16 行：

```dockerfile
-subj "/C=CN/ST=省份/L=城市/O=组织/CN=你的域名.com"
```

或挂载自己的证书：

```yaml
services:
  nginx:
    image: nexent-nginx:amd64
    volumes:
      - /path/to/nginx.crt:/etc/nginx/ssl/nginx.crt:ro
      - /path/to/nginx.key:/etc/nginx/ssl/nginx.key:ro
    ports:
      - "80:80"
      - "443:443"
```

## 启动容器

```bash
# 加载镜像后，直接运行
docker run -itd --name nexent-nginx -p 443:443 --network nexent_nexent nexent-nginx:amd64

# ARM64 架构
docker run -itd --name nexent-nginx -p 443:443 --network nexent_nexent nexent-nginx:arm64
```

常用参数说明：
- `-itd`：后台运行
- `--name nexent-nginx`：容器名称
- `-p 443:443`：映射 HTTPS 端口
- `--network nexent_nexent`：加入 nexent 网络，与其他容器通信

## 架构说明

| 架构 | 平台 | 适用设备 |
|------|------|----------|
| x86_64 | linux/amd64 | Intel/AMD 服务器、电脑 |
| ARM64 | linux/arm64 | Apple Silicon、Raspberry Pi 4/5 |
| ARMv7 | linux/arm/v7 | Raspberry Pi 3 |
