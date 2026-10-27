# 迁移计划：A2A 重复关联精确提示与错误码规范化

当前分支 `dc-fix-a2a-duplicate-relation-tip-1026` 已与 `origin/develop` 顶点（003771c9d）完全一致、工作区干净；原功能 commit `f05618382` 仅存在于旧分支 `dc/fix-a2a-duplicate-relation-tip-1023`，未混入当前分支，可直接按文档落改动。

## 前置核实结论（相对迁移文档的修正）

- **后端端点文件已迁移**：`backend/apps/a2a_client_app.py` 已不存在（develop 重构 ef7a3b553 拆分），端点现位于 `backend/management/api/a2a/a2a_client.py`（POST /a2a/client/relations，L343-375，`except ValueError` 在 L370-372），逻辑与文档一致。
- **import 无需新增**：该文件已导入 `ErrorCode`（L19，`contracts.errors.codes`）和 `AppException`（L20，`contracts.errors.exceptions`）。ErrorCode 模块实际是 `backend/contracts/errors/codes.py`（非文档猜测的 `consts/error_code.py`）。
- **错误码设施吻合**：`COMMON_RESOURCE_ALREADY_EXISTS = "000502"`（codes.py L68），`ERROR_CODE_HTTP_STATUS` 映射为 409（L318）→ HTTP 状态不变，仅 body 从 `{"message"}` 变为标准 `{"code","message","details"}`（全局 handler：`backend/management/utils/app_factory.py:93-103`）。db 层重复关联仍抛 `ValueError("Relation already exists")`（`backend/management/db/a2a/repository.py:762-774`）；`AgentNotFoundError` 虽是 ValueError 子类但被更早的 except 捕获，映射安全；无全局 ValueError 中间件，本地 try/except 仍是现行惯例（同文件 L647-656 已有 `raise AppException(...) from exc` 先例）。
- **前端设施吻合**：`frontend/services/a2aService.ts` 路径与文档一致；`ApiError` 来自 `'./api'`（`code: string | number`）；`ErrorCode` 在 `frontend/const/errorCode.ts` L55（`RESOURCE_ALREADY_EXISTS: "000502"`）但尚未在该文件导入；`fetchWithErrorHandling` 对非 2xx 抛 ApiError 并解析顶层 `{code, message}` → 000502 落入 `addRelation` 的 catch（L382-385），方案成立。现行比较惯例是 `String(error.code) === ErrorCode.X`。
- **测试文件吻合**：`test/backend/app/test_a2a_relation_authorization.py` 存在，`test_binding_persistence_error_mapping`（L28-33，参数化 ValueError→409 仅断言状态码，改动后仍绿）与 `test_owned_relationship_success`（L36-42）相邻；测试 App 自带 AppException handler（`test_a2a_client_app.py` L54-59，返回 `exc.to_dict()` = `{code, message, details}`），新测试断言 body 可行。
- **其他**：`.gitignore` 无 `.worktrees/` → 执行可选 chore；`scripts/check_copyright.py` 存在；文案 key `a2a.service.relationAlreadyExists` 不存在 → 需新增（en L4235 / zh L4038 为 addRelationFailed）；正式用例 API-094 已覆盖重复添加→409 且仅断言状态码 → 不受影响，无需更新 test-e2e。

## 修改清单（6 文件）

### 1. `backend/management/api/a2a/a2a_client.py`（L370-372）

`except ValueError` 分支改为抛标准异常，加英文注释、`from e` 链（与同文件 L367/L369/L647-656 惯例一致）：

```python
    except ValueError as e:
        # Duplicate relation is the only ValueError raised by the db layer here;
        # map it to the standard "already exists" error code (000502, HTTP 409)
        # so the frontend can show a precise message instead of a generic failure.
        logger.error(f"Add relation failed: {e}")
        raise AppException(
            ErrorCode.COMMON_RESOURCE_ALREADY_EXISTS,
            message=str(e)
        ) from e
```

### 2. `frontend/services/a2aService.ts`

- L4 后新增：`import { ErrorCode } from '@/const/errorCode';`
- `addRelation` catch（L382-385）改为：

```ts
    } catch (error) {
      log.error('Failed to add relation:', error);
      // Duplicate relation: backend answers 409 with code 000502 ("Relation
      // already exists"); surface a precise hint instead of a generic failure.
      if (
        error instanceof ApiError &&
        (String(error.code) === ErrorCode.RESOURCE_ALREADY_EXISTS ||
          error.message.includes('already exists'))
      ) {
        return { success: false, message: t('a2a.service.relationAlreadyExists') };
      }
      return { success: false, message: discoveryErrorMessage(error, 'a2a.service.addRelationFailed') };
    }
```

（与原 commit 的差异：`error.code ===` 按现行惯例改为 `String(error.code) ===`，因 `ApiError.code` 类型为 `string | number`，更稳；其余错误路径按原 commit 统一走 `discoveryErrorMessage`。）

### 3. `frontend/public/locales/en/common.json`

在 `"a2a.service.addRelationFailed"` 后插入：
`"a2a.service.relationAlreadyExists": "This external agent is already associated with the current agent",`

### 4. `frontend/public/locales/zh/common.json`

同位置插入：
`"a2a.service.relationAlreadyExists": "该外部Agent已关联至当前智能体，无需重复添加",`

### 5. `test/backend/app/test_a2a_relation_authorization.py`

- 新增项目导入：`from contracts.errors.codes import ErrorCode`（放在现有 contracts 导入旁，按字母序）。
- 在 `test_binding_persistence_error_mapping` 与 `test_owned_relationship_success` 之间插入：

```python
def test_duplicate_relation_returns_already_exists_code(mocker):
    """Duplicate relation must surface the machine-readable code (000502) so the
    frontend can show a precise hint instead of a generic failure message."""
    mocker.patch.object(app, "require_external_relation_edit")
    mocker.patch.object(
        app.a2a_agent_db,
        "add_external_agent_relation",
        side_effect=ValueError("Relation already exists"),
    )
    response = legacy.client.post("/a2a/client/relations", json={
        "local_agent_id": 1, "external_agent_id": 2})
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == ErrorCode.COMMON_RESOURCE_ALREADY_EXISTS.value
    assert body["message"] == "Relation already exists"
```

### 6. `.gitignore`

末尾追加：

```gitignore

# Git worktrees
.worktrees/
```

## 验证步骤

1. **回归先证伪**：先写好测试、在改后端前运行一次，确认 `body["code"]` 断言失败（旧 body 无 code 字段），证明测试能检测缺陷；再改后端使其转绿。
2. `pytest test/backend/app/test_a2a_relation_authorization.py -v`（仓库根目录，backend 环境）——全部通过。
3. `cd frontend && npm run check-all`（type-check + lint + format + build）。
4. `python scripts/check_copyright.py` 校验改动的源文件（所有目标文件已带 header，预期直接通过）。
5. 报告实际运行/受阻的检查结果。

## 范围说明（与原 commit 保持一致）

- `AgentConfigurationDrawer` → `frontend/lib/externalAgentRelations.ts` 的批量同步路径会丢弃 message、仍显示通用失败文案，原 commit 未覆盖，本次不动（可作后续改进）。
- en/zh 已有通用 `errorCode.000502` 文案 key，本次不使用，保持 a2a 专用文案。
- 不新增/修改 D1-D5 正式资产：API-094 已在 API 边界锁定 409 契约且不受影响，组件级回归由新增 UT 承担。