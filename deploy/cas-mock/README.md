# Nexent 本地 CAS 测试服务

这是一个仅用于本地联调的 CAS 2.0 Mock Server，不用于生产环境。默认预置一个用户：

```text
用户名：casuser
密码：casuser
邮箱：casuser@example.com
角色：USER
租户：tenant_id
```

## 启动

```powershell
docker compose -f deploy/cas-mock/docker-compose.yml up -d --build
```

服务地址为 `http://localhost:3001/cas`，健康检查地址为 `http://localhost:3001/healthz`。

## Nexent 配置

Docker Desktop 下，Nexent 后端容器访问宿主机发布的 CAS 服务使用 `host.docker.internal`：

```env
CAS_ENABLED=true
CAS_SERVER_URL=http://host.docker.internal:3001/cas
CAS_VALIDATE_PATH=/p3/serviceValidate
CAS_CALLBACK_BASE_URL=http://localhost:30000
CAS_LOGIN_MODE=button
CAS_USER_ATTRIBUTE=uid
CAS_EMAIL_ATTRIBUTE=email
CAS_ROLE_ATTRIBUTE=role
CAS_TENANT_ATTRIBUTE=tenant_id
CAS_DEFAULT_ROLE=USER
CAS_DEFAULT_TENANT_ID=tenant_id
CAS_SYNTHETIC_EMAIL_DOMAIN=@cas.local
CAS_LOGOUT_URL=/logout
CAS_SSL_VERIFY=true
```

`CAS_CALLBACK_BASE_URL` 要改成浏览器实际访问 Nexent 的地址。本地前端使用 `http://localhost:30001` 时就填写该地址；如果使用 Docker Compose 的 `3000:3000` 映射或部署脚本的 NodePort，则填写实际的访问地址。

## 验证

1. 打开 Nexent CAS 登录入口。
2. 使用 `casuser / casuser` 登录。
3. 回到 Nexent 后，顶部和个人信息页应显示 `casuser`。
4. `GET /api/user/current_user_info` 应返回 `auth_provider: "cas"`。
5. 直接访问 `http://localhost:3001/cas/p3/serviceValidate` 不带 ticket 应返回 `INVALID_TICKET`，说明校验接口已启动。

可通过环境变量覆盖默认用户属性，例如 `CAS_MOCK_EMAIL`、`CAS_MOCK_DISPLAY_NAME`、`CAS_MOCK_ROLE` 和 `CAS_MOCK_TENANT_ID`。
