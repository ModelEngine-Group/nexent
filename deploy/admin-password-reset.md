# 管理员密码重置

通过后端内部 API 以管理员权限重置用户密码。无需验证旧密码。

## 架构

```
scripts/reset_user_password.py
    |
    |-- POST /api/nb/v1/internal/users/{user_id}/password
            |
            |-- northbound_app.py   (HTTP 层，认证检查)
                    |
                    |-- northbound_service.py  (admin_reset_password)
                            |
                            |-- Supabase admin client (update_user_by_id)
```

- **服务层**（`northbound_service.py`）：`admin_reset_password()` — 跳过旧密码验证，使用 Supabase service-role key。
- **应用层**（`northbound_app.py`）：`POST /api/nb/v1/internal/users/{user_id}/password` — 校验 `X-Internal-Key` 请求头。
- **脚本**（`scripts/reset_user_password.py`）：命令行工具，读取 JSON 配置并调用 API。

## 认证

内部端点使用 `X-Internal-Key` 请求头认证，其值必须与后端服务器配置的 `SERVICE_ROLE_KEY` 环境变量一致。

## 密码要求

- 最少 **8 个字符**（由服务层的 `validate_password_strength` 强制校验）。
- 密码强度不足将返回 HTTP 400，错误信息为 `PROFILE_PASSWORD_WEAK`。

## API 端点

### `POST /api/nb/v1/internal/users/{user_id}/password`

**认证方式：** `X-Internal-Key: <SERVICE_ROLE_KEY>`

**路径参数：**

| 参数    | 类型   | 说明              |
|---------|--------|------------------|
| user_id | string | Supabase 用户 ID（UUID） |

**请求体：**
```json
{
  "new_password": "NewSecurePass123"
}
```

**响应状态码：**

| 状态码 | 含义                    |
|--------|------------------------|
| 200    | 密码重置成功            |
| 400    | 密码强度不足 / 用户不存在 |
| 401    | `X-Internal-Key` 无效  |
| 500    | 服务器内部错误          |

**成功响应（200）：**
```json
{
  "message": "Password reset successfully",
  "data": {
    "user_id": "a1b2c3d4-...",
    "email": "alice@example.com"
  }
}
```

**错误响应（400）：**
```json
{
  "detail": "PROFILE_PASSWORD_WEAK"
}
```

---

## 使用方法

### 第一步 — 准备 JSON 配置文件

创建配置文件（如 `passwords.json`）：

```json
{
  "internal_key": "your-service-role-key-here",
  "backend_url": "http://localhost:5013",
  "resets": [
    {
      "user_id": "a1b2c3d4-xxxx-xxxx-xxxx-ffffffffffff",
      "new_password": "NewSecurePass123"
    },
    {
      "user_id": "b2c3d4e5-xxxx-xxxx-xxxx-eeeeeeeeeeee",
      "new_password": "AnotherPass456"
    }
  ]
}
```

**配置字段说明：**

| 字段          | 必填 | 默认值                | 说明         |
|--------------|------|----------------------|--------------|
| `internal_key` | 是  | —                    | `SERVICE_ROLE_KEY` 的值 |
| `backend_url`  | 否   | `http://localhost:5013` | 后端服务地址  |
| `resets`       | 是   | —                    | 重置项数组    |

**每项字段说明：**

| 字段           | 必填 | 说明              |
|---------------|------|------------------|
| `user_id`      | 是   | Supabase 用户 UUID |
| `new_password` | 是   | 新密码（至少 8 字符）|

### 第二步 — 运行脚本

```bash
python scripts/reset_user_password.py --config passwords.json
```

或者直接传入 JSON 字符串：

```bash
python scripts/reset_user_password.py --json '{
  "internal_key": "your-key",
  "resets": [{"user_id": "...", "new_password": "Pass12345"}]
}'
```

### 第三步 — 查看输出

```
Resetting passwords for 2 user(s) via http://localhost:5013 ...
Backend URL: http://localhost:5013
Reset count: 2

[OK]   user_id=a1b2c3d4-xxxx-xxxx-xxxx-ffffffffffff (alice@example.com)
[OK]   user_id=b2c3d4e5-xxxx-xxxx-xxxx-eeeeeeeeeeee (bob@example.com)

============================================================
Results: 2 succeeded, 0 failed
============================================================
```

## 如何获取 `user_id`

`user_id` 是 Supabase 的 UUID，可通过以下方式获取：

1. **从初始化脚本输出中查找** — `provision_tenant.py` 会输出租户 ID 和管理员的 `user_id`。
2. **从数据库查询** — 在 `user_tenant_t` 表中查询：

   ```sql
   SELECT user_id, user_email, user_role FROM user_tenant_t
   WHERE user_email = 'alice@example.com';
   ```
3. **从后端日志中查找** — 登录和 API 调用日志中会记录 `user_id`。

## 安全注意事项

- `X-Internal-Key` 授予完整管理员权限，请像对待数据库密码一样妥善保管它。
- 将包含敏感信息的 JSON 配置文件加入 `.gitignore`，避免提交到版本控制。
- 建议定期轮换 `SERVICE_ROLE_KEY`。
- 此端点不对公网暴露，只应从可信的内部网络或 CI/CD 流水线中访问。
