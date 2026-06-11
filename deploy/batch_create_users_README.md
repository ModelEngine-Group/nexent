# Batch User Creation Script

Through CSV file batch create users, using Northbound API for operations.

## Tenant Provisioning

Use `provision_tenant.py` to create new tenants with their admin users and optional initial members in one step. The script sends the spec to the backend internal API.

### JSON Config File

```json
{
  "internal_key": "your-supabase-service-role-key",
  "backend_url": "http://localhost:5013",
  "tenants": [
    {
      "tenant_name": "Acme Corp",
      "admin_email": "admin@acme.com",
      "admin_password": "SecurePass123",
      "users": [
        { "email": "alice@acme.com", "password": "Pass1", "role": "USER" },
        { "email": "bob@acme.com",   "password": "Pass2", "role": "DEV" }
      ]
    }
  ]
}
```

Run:

```bash
python scripts/provision_tenant.py --config tenants.json
```

### Authentication

The `internal_key` field should contain your Supabase **service role key** (the same value as `SERVICE_ROLE_KEY` configured on the server). The backend validates it against its own `SERVICE_ROLE_KEY` via the `X-Internal-Key` header.

### What the backend creates

1. Tenant config records (`TENANT_ID`, `TENANT_NAME`, `DEFAULT_GROUP_ID`)
2. Default group
3. Admin user in Supabase auth + `user_tenant_t` + group membership
4. Default tools and skills for the admin
5. TTS/STT model stubs for the admin
6. Access Key for the admin
7. Each listed user (duplicate emails are skipped with `[SKIP]`)

### Roles

| Role | Description |
|------|-------------|
| USER | Regular user with basic permissions |
| DEV | Developer with additional tool access |
| ADMIN | Full administrative permissions |

## Batch User Creation

After provisioning a tenant, use the batch creation script to create users via the Northbound API.

## Full Workflow

**Step 1 — Provision a tenant (requires running backend):**

Create `tenants.json` with your service role key and tenant spec, then:

```bash
python scripts/provision_tenant.py --config tenants.json
```

Save the printed `Access Key` — it is required for Step 2.

**Step 2 — Batch create users (requires running backend):**

```bash
python scripts/batch_create_users.py --csv users.csv --token <access_key>
```

The batch creation script uses the Northbound API (`/api/nb/v1`) and requires a running backend server. The provisioning script does **not** require a running server.

## CSV 文件格式

### 文件示例

```csv
email,password,role
alice@example.com,password123,USER
bob@example.com,password456,DEV
carol@example.com,adminpass,ADMIN
```

### 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| email | 是 | 用户邮箱地址 |
| password | 是 | 账户密码（至少 6 个字符） |
| role | 否 | 用户角色，默认为 USER，可选值：USER、DEV、ADMIN |

### 角色说明

| 角色 | 说明 |
|------|------|
| USER | 普通用户，拥有基础功能权限 |
| DEV | 开发者用户，拥有开发工具权限 |
| ADMIN | 管理员，拥有全部管理权限 |

## 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--base-url` | `http://localhost:5013/api/nb/v1` | API 服务地址 |
| `--csv` | - | CSV 文件路径（必填） |
| `--token` | - | Access Key 认证令牌（必填） |
| `--concurrency` | `5` | 并发请求数 |
| `--retry` | `2` | 失败重试次数 |

## 使用示例

### 1. 基本批量创建

```bash
python scripts/batch_create_users.py --csv users.csv --token nexent-1bd1cef12a6c18b2d33496f9
```

### 2. 提高并发数

对于大量用户创建，可以提高并发数以加快速度：

```bash
python scripts/batch_create_users.py --csv users.csv --token your-admin-token --concurrency 10
```

### 3. 禁用重试

如果希望失败时立即终止，不进行重试：

```bash
python scripts/batch_create_users.py --csv users.csv --token your-admin-token --retry 0
```

### 4. 指定不同的 API 地址

测试或开发环境使用不同的地址：

```bash
python scripts/batch_create_users.py \
  --base-url http://192.168.1.100:5013/api \
  --csv users.csv \
  --token your-admin-token
```

### 5. 创建单个用户

如果只需要创建单个用户，可以创建一个只包含一行数据的 CSV 文件：

```csv
email,password,role
newuser@example.com,mypassword,USER
```

## 输出说明

### 成功输出示例

```
============================================================
Batch User Creation
============================================================
Target URL:     http://localhost:5013/api/users
CSV File:       users.csv
Total Users:    3
Concurrency:    5
Retries:        2
============================================================

  [OK] alice@example.com: Created
  [OK] bob@example.com: Created
  [FAIL] carol@example.com: EMAIL_ALREADY_EXISTS

============================================================
Batch User Creation Results
============================================================
Total:      3
Created:    2
Skipped:    1 (email already exists)
Failed:     0
Duration:   0.45s
============================================================
```

### 输出状态说明

| 状态 | 说明 |
|------|------|
| `[OK]` | 用户创建成功 |
| `[FAIL]` | 用户创建失败（可能是邮箱已存在或其他错误） |

## 错误处理

### 常见错误及解决方案

#### 1. 401 未授权错误

```
[FAIL] user@example.com: Unauthorized
```

**原因：** 提供的 Access Key 无效或已过期。

**解决方案：**
- 检查 Access Key 是否正确
- 从后端管理界面获取新的 Access Key

#### 2. 400 请求参数错误

```
[FAIL] user@example.com: Invalid email format
```

**原因：** 邮箱格式不正确。

**解决方案：**
- 确保所有邮箱地址格式正确（如 user@example.com）
- 检查 CSV 文件是否有格式问题

#### 3. 409 邮箱已存在

```
[FAIL] user@example.com: EMAIL_ALREADY_EXISTS
```

**原因：** 该邮箱已被其他用户注册。

**解决方案：**
- 使用新的邮箱地址
- 跳过已存在的用户（脚本默认会跳过）

#### 4. 超时错误

```
[FAIL] user@example.com: Timeout
```

**原因：** API 请求超时。

**解决方案：**
- 检查 API 服务是否正常运行
- 降低并发数
- 增加重试次数

## CSV 文件最佳实践

### 1. 文件编码

建议使用 UTF-8 编码保存 CSV 文件，以避免中文字符出现乱码。

### 2. 数据验证

在运行脚本之前，建议检查 CSV 文件：

- 确认所有必填字段都有值
- 确认邮箱格式正确
- 确认密码长度符合要求（至少 6 个字符）
- 确认角色值有效（USER、DEV、ADMIN）

### 3. 批量导入建议

- 首次导入建议先测试 5-10 个用户
- 确认无误后再进行大批量导入
- 建议保留原始 CSV 文件作为记录

## 安全注意事项

1. **保护 Access Key**：不要将 Access Key 提交到代码仓库
2. **CSV 文件安全**：包含密码的 CSV 文件应该妥善保管，使用后及时删除
3. **密码强度**：建议使用强密码，符合安全策略要求
4. **日志审查**：定期审查创建日志，检查异常活动

## 集成到自动化流程

### Shell 脚本集成示例

```bash
#!/bin/bash
# batch_import.sh

# 从环境变量获取 Access Key
ACCESS_KEY="${NEXENT_ACCESS_KEY}"

if [ -z "$ACCESS_KEY" ]; then
    echo "Error: NEXENT_ACCESS_KEY environment variable not set"
    exit 1
fi

# 执行批量导入
python scripts/batch_create_users.py \
  --csv data/users_batch1.csv \
  --token "$ACCESS_KEY" \
  --concurrency 10

if [ $? -eq 0 ]; then
    echo "Batch import completed successfully"
else
    echo "Batch import failed"
    exit 1
fi
```

### Python 脚本集成示例

```python
import subprocess
import os

def batch_import(csv_file: str, access_key: str):
    """批量导入用户的封装函数"""
    result = subprocess.run(
        [
            "python", "scripts/batch_create_users.py",
            "--csv", csv_file,
            "--token", access_key,
            "--concurrency", "10"
        ],
        capture_output=True,
        text=True
    )
    return result.returncode == 0, result.stdout, result.stderr
```

## 性能参考

| 并发数 | 100 用户预计耗时 | 推荐场景 |
|--------|------------------|----------|
| 1 | 30-50 秒 | 稳定测试、慢速环境 |
| 5 | 10-20 秒 | 默认设置、通用场景 |
| 10 | 5-10 秒 | 快速导入、网络良好 |
| 20 | 3-5 秒 | 大量导入、高性能环境 |

## 常见问题

### Q: 如何获取 Access Key？

Access Key 需要通过后端管理界面创建，具体步骤：
1. 登录后端管理系统
2. 进入 API Key 管理页面
3. 创建新的 Access Key
4. 复制生成的 Key

### Q: CSV 文件中可以有表头吗？

可以。脚本会自动跳过表头行（email、password、role）。

### Q: 如何处理部分失败的批量创建？

脚本会继续处理剩余用户，失败的用户会记录在错误列表中。查看输出中的 "Failed Users" 部分了解详情。

### Q: 支持从其他格式导入吗？

当前版本仅支持 CSV 格式。如需其他格式，可以扩展脚本的 `load_csv_users` 方法。
