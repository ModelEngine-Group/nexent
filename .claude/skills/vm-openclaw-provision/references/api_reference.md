# FusionCompute API 参考

FusionCompute 虚拟机发放完整 API 文档。

## 认证

### 登录

获取后续 API 调用所需的认证令牌。

**接口**: `POST /service/session`

**请求头**:
```http
Accept: application/json;version=8.1;charset=UTF-8
X-Auth-User: <用户名>
X-Auth-Key: <密码>
X-Auth-UserType: 2
X-ENCRYPT-ALGORITHM: 1
```

**响应头**:
- `X-Auth-Token`: 认证令牌（后续所有调用必需）

**示例**:
```bash
curl -k -X POST https://fc-ip/service/session \
  -H "Accept: application/json;version=8.1;charset=UTF-8" \
  -H "X-Auth-User: admin" \
  -H "X-Auth-Key: password123" \
  -H "X-Auth-UserType: 2" \
  -H "X-ENCRYPT-ALGORITHM: 1"
```

---

## 站点管理

### 获取站点列表

获取所有可用站点。

**接口**: `GET /service/sites`

**请求头**:
```http
Accept: application/json;version=8.1;charset=UTF-8
Content-Type: application/json;charset=UTF-8
X-Auth-Token: <token>
```

**响应**: 站点对象数组

---

### 获取站点详情

获取指定站点的详细信息。

**接口**: `GET /service/sites/<site_id>`

**请求头**:
```http
Accept: application/json;version=8.1;charset=UTF-8
Content-Type: application/json;charset=UTF-8
X-Auth-Token: <token>
```

---

## 虚拟机管理

### 获取虚拟机列表

获取站点内所有虚拟机。

**接口**: `GET /service/sites/<site_id>/vms`

**请求头**:
```http
Accept: application/json;version=8.1;charset=UTF-8
Content-Type: application/json;charset=UTF-8
X-Auth-Token: <token>
```

**响应**: 虚拟机对象数组

---

### 获取虚拟机详情

获取指定虚拟机的详细信息。

**接口**: `GET /service/sites/<site_id>/vms/<vm_id>`

**请求头**:
```http
Accept: application/json;version=8.1;charset=UTF-8
Content-Type: application/json;charset=UTF-8
X-Auth-Token: <token>
```

**响应**: 包含完整配置的虚拟机对象

---

### 克隆虚拟机（异步）

从模板创建新虚拟机。这是一个异步操作，返回任务 ID。

**接口**: `POST /service/sites/<site_id>/vms/<vm_id>/action/clone`

**请求头**:
```http
Accept: application/json;version=8.1;charset=UTF-8
Content-Type: application/json;charset=UTF-8
X-Auth-Token: <token>
```

**请求体**:
```json
{
  "name": "虚拟机名称",
  "description": "虚拟机描述",
  "vmConfig": {
    "cpu": {
      "quantity": 4,
      "cpuHotPlug": 1,
      "cpuThreadPolicy": "prefer",
      "cpuPolicy": "shared",
      "cpuBindType": "nobind"
    },
    "memory": {
      "quantityMB": 8192,
      "memHotPlug": 1
    },
    "properties": {
      "recoverByHost": true
    }
  },
  "osOptions": {
    "osType": "Linux",
    "osVersion": 10088,
    "guestOSName": ""
  },
  "autoBoot": true,
  "isLinkClone": false
}
```

**响应**: 包含 `task_id` 的任务对象

---

### 启动虚拟机（异步）

启动已停止的虚拟机。

**接口**: `POST /service/sites/<site_id>/vms/<vm_id>/action/start`

**请求头**:
```http
Accept: application/json;version=8.1;charset=UTF-8
Content-Type: application/json;charset=UTF-8
X-Auth-Token: <token>
```

**响应**: 包含 `task_id` 的任务对象

---

### 停止虚拟机（异步）

停止运行中的虚拟机。

**接口**: `POST /service/sites/<site_id>/vms/<vm_id>/action/stop`

**请求头**:
```http
Accept: application/json;version=8.1;charset=UTF-8
Content-Type: application/json;charset=UTF-8
X-Auth-Token: <token>
```

**响应**: 包含 `task_id` 的任务对象

---

### 休眠虚拟机（异步）

休眠运行中的虚拟机。

**接口**: `POST /service/sites/<site_id>/vms/<vm_id>/action/hibernate`

**请求头**:
```http
Accept: application/json;version=8.1;charset=UTF-8
Content-Type: application/json;charset=UTF-8
X-Auth-Token: <token>
```

**响应**: 包含 `task_id` 的任务对象

---

### 修改虚拟机（异步）

修改虚拟机配置。注意：CPU 和内存需要分别修改。

**接口**: `PUT /service/sites/<site_id>/vms/<vm_id>`

**请求头**:
```http
Accept: application/json;version=8.1;charset=UTF-8
Content-Type: application/json;charset=UTF-8
X-Auth-Token: <token>
```

**请求体（修改 CPU）**:
```json
{
  "cpu": {
    "quantity": 8
  }
}
```

**请求体（修改内存）**:
```json
{
  "memory": {
    "quantityMB": 16384
  }
}
```

**响应**: 包含 `task_id` 的任务对象

---

### 删除虚拟机（异步）

删除虚拟机。

**接口**: `DELETE /service/sites/<site_id>/vms/<vm_id>`

**请求头**:
```http
Accept: application/json;version=8.1;charset=UTF-8
Content-Type: application/json;charset=UTF-8
X-Auth-Token: <token>
```

**响应**: 包含 `task_id` 的任务对象

---

## 任务管理

### 获取任务状态

查询异步任务的状态。

**接口**: `GET /service/sites/<site_id>/tasks/<task_id>`

**请求头**:
```
Accept: application/json;version=8.1;charset=UTF-8
Content-Type: application/json;charset=UTF-8
X-Auth-Token: <token>
```

**响应**: 包含 `taskUrn` 的任务对象

```json
{
    "taskUrn": "urn:sites:E3600FCD:tasks:145498"
}
```

响应示例：
- `taskUrn`: 格式为 `urn:sites:E3600FCD:tasks:145498`
- `taskUri`: 格式为 `/service/sites/E3600FCD/tasks/145489`

从 `taskUrn` 中提取 task_id (如 145498) 用于后续的 wait_for_task 等操作。task_id | `145498` | `urn:sites:E3600FCD:tasks:145498` |

**响应**: 包含状态的任务对象

**任务状态值**:
- `pending`: 任务排队中
- `running`: 任务执行中
- `success`: 任务成功完成
- `failed`: 任务失败
- `timeout`: 任务超时

---

## 错误处理

### HTTP 状态码

- `200`: 成功
- `201`: 已创建（异步任务）
- `202`: 已接受
- `400`: 请求错误
- `401`: 未授权（token 过期）
- `403`: 禁止访问
- `404`: 未找到
- `500`: 服务器内部错误
- `503`: 服务不可用

### 通用错误响应格式
```json
{
  "error": {
    "code": "错误代码",
    "message": "错误描述"
  }
}
```
