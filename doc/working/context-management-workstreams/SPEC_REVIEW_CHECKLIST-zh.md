# 工作流规范评审检查清单

> 检查项 1–6 源自 W1 验收后回顾（2026-06-16）。
> 检查项 7–10 源自 W1/W2 后续回顾（2026-06-22）——W2 PR 的端到端测试
> 加上六周的清理工作暴露了四类新 bug，其中最严重的是层间交互 bug：
> 静默丢弃运维人员的容量编辑，并在用户每次"确认"时软删除其刚添加的目录行。
> 适用于每个新工作流规范在标记为 Accepted **之前**。
> 再次适用于每个现有规范在实现开始 **之前**。每个检查项都有具体的子问题；
> "OK" 要求对 **所有** 子问题给出肯定回答，不仅仅是主问题。

## 如何使用

1. 将此文件复制到每个工作流的评审中（例如 `W2_REVIEW.md`）。
2. 对于六个检查项中的每一项，用纯文本填写答案。
3. 如果任何子问题未回答或不清楚，标记该项为 ❌。
4. 规范在所有项都标记为 ✅ 或有明确的"推迟到后续工作流 W_NN"且该后续工作流已开启之前，
   不应标记为 Ready to Implement。

## 六个检查项

### 1. 用户旅程章节

**主问题：** 规范是否描述了真实运维人员或开发者如何从头到尾体验此工作流的行为？

子问题：
- [ ] 受影响的用户角色是谁？（运维人员、终端用户、集成者、值班人员）
- [ ] 作为此工作流的直接结果，用户看到/输入/点击了什么？
- [ ] 用户 **不再** 看到什么，或现在看到的内容有何不同？
- [ ] 如果某个值从"运维人员输入"变为"系统推导"，谁知道推导规则，
      当推导错误时如何纠正？

> **W1 教训**：ADR Decision 1 建模了目录数据、运行时契约和指纹。
> 但从未建模"运维人员如何将容量值放入 `model_record_t` 行"——
> 默认的 `model_factory = 'OpenAI-API-Compatible'` 导致每个标准添加路径
> 都静默地错过了目录。规范通过了评审；用户实际上无法使用该功能。

### 2. 前端步骤分解

**主问题：** 如果工作流有前端影响，是否分解为 ≥ 3 个覆盖不同关注点的具体子项？

子问题：
- [ ] **状态**：是否描述了新的表单状态机？（初始值、转换、必填与可选字段）
- [ ] **视觉**：哪个现有 UI 元素被替换/移除/添加？布局是什么样的（草图/行排列）？
- [ ] **服务层**：哪些 `*.service.ts` / API 调用点需要新的 camelCase ↔ snake_case 映射？
- [ ] **验证**：客户端验证规则（哪些字段必填、哪些组合被拒绝、错误消息键）
- [ ] **现有数据迁移**：当现有行有遗留字段 X 但没有新字段 Y 时，
      编辑加载时会发生什么？保存时会发生什么？
- [ ] **同级组件**：哪些其他对话框/页面与变更的组件共享状态或语义，
      必须同步更新？

> **W1 教训**：W1 规范步骤 7 说"更新前端添加/编辑表单和标签；
> 显示容量来源和警告"。一句话 → 8 个不同的 bug（回顾中的 B1–B8），
> 因为上述 6 个子关注点在规范中都没有答案。

### 3. 端到端演示脚本

**主问题：** 验收章节是否包含一个具体、可复制粘贴的演示脚本，
人类可以在真实部署上执行以证明工作流有效？

子问题：
- [ ] 脚本是否从干净状态开始并产生可验证的产物（数据库行、监控记录、UI 截图）？
- [ ] 是否命名了 **具体值**（模型名称、提供商、请求体），而不是仅类型（"一个 LLM 模型"——太模糊）？
- [ ] 是否也有 **负面路径** 演示？（"添加一个没有目录匹配的模型 → 期望回退到 X 和警告 Y"）
- [ ] 脚本是否引用了评审者可以粘贴的验证 SQL / curl / 日志行？

> **W1 教训**："测试覆盖 combined-window 和 separate-input-limit 提供商"
> 和"监控报告总窗口、输出预留、安全输入预算、实际输入使用和容量来源"——
> 都是抽象描述。CM-031 直到验收后约 10 天才被发现，当时有人手动运行了
> 真实的模型添加。验收中的演示脚本会在第一天就暴露 CM-031。

### 4. 运维依赖

**主问题：** 除了 `git pull`，部署还需要做什么才能让此工作流生效？

子问题：
- [ ] 哪些容器需要重建镜像？（哪个 Dockerfile，哪个 `compose up --force-recreate <service>`）
- [ ] 哪些数据库迁移需要手动运行？（`docker/sql/` 中的哪些 SQL 文件）
- [ ] 哪些环境变量 / `consts.const` 条目需要设置？
- [ ] 哪些功能开关存在，默认值是什么？租户级覆盖机制？
- [ ] 是否有分阶段发布的运维手册步骤？回滚流程？
- [ ] 哪些监控仪表板/告警需要更新？

> **W1 教训**：W1 步骤 2 在 `docker/sql/` 中发布了三个 SQL 文件。
> 在运行环境中约 24 小时内没有人应用它们，直到用户尝试添加模型
> 并得到 SQL "column does not exist" 错误，被前端错误翻译为
> "无法连接到 ModelEngine"。规范从未说明这些文件必须手动应用，
> 因为没有迁移运行器——也没有将缺少运行器标记为依赖。
> （参见 `nexent 代码改动生效流程.md` 坑 6。）

### 5. 同级组件枚举

**主问题：** 对于提到的每个组件、文件、表或调用点，
是否明确列出了其近同级（即使只是说"有意排除在范围外"）？

子问题：
- [ ] 如果修改了对话框/页面，是否命名了共享相同表单状态或模型记录架构的每个其他对话框？
- [ ] 如果修改了函数，是否列出了所有调用者（`grep` 证据或 file:line 引用）？
- [ ] 如果添加了数据库列，是否命名了所有 ORM/Pydantic/SQL 镜像文件？
- [ ] 如果 Python 模块在一个 sys.modules 键下加载，是否命名了另一个键
      （例如 `backend.services.X` vs `services.X`）？

> **W1 教训**：步骤 7 命名了 `ModelEditDialog` 但没有命名其同级
> `ProviderConfigEditDialog`。修复后两者都渲染了容量字段，
> 但只有一个得到了修复。同一个对话框文件，两个导出的组件——
> 按功能名称 grep 时很容易遗漏。

### 6. 反向测试："用户能否实际使用此功能？"

**主问题：** 假设你是需要此工作流所启用功能的运维人员/开发者。
从头到尾走一遍步骤。你会遇到死胡同、模糊的默认值或不可见的失败吗？

子问题：
- [ ] 不阅读源代码，用户能否知道 **功能是否激活** 对于他们的请求？
      （可见状态、监控行等）
- [ ] 功能依赖的所有值是否 **可通过 UI 访问**（不仅仅是通过 SQL UPDATE）？
- [ ] 如果功能静默回退，回退是否 **可观察**？（日志行、监控字段、UI 标记）
- [ ] 如果工作流不可见（纯后端），什么能让值班工程师在 <60 秒内回答"W_N 现在健康吗？"

> **W1 教训**：glm-5.1 成功添加，"连通性检查通过"，用户没有任何信号表明
> 目录被错过。唯一发现的方法是直接查询 `model_monitoring_record_t`。
> 规范评审期间的反向测试审查会捕获这一点。

## W1/W2 后续追加（2026-06-22）

> 检查项 7–10 来自 W2 PR 的端到端测试窗口。检查项 1–6 关注规范完整性；
> 这四项关注的是"按报告的单个 bug 修复时容易遗漏的实现契约"——尤其当
> 同一个概念有多个前端配置面、多个后端构造调用点、或多个必须保持一致
> 的 key 推导算法分支时。

### 7. 前端配置面矩阵

**主问题：** 对于此工作流修改的每个表单/对话框，是否枚举了配置面的
**完整矩阵**，并验证了每个配置面的契约（状态、验证、保存处理器、wire
payload）？

矩阵至少 4 个面，通常是 6 个：
- 单个添加（`ModelAddDialog` 单行表单）
- 单个编辑（`ModelEditDialog`）
- 批量添加顶部默认值（`ModelAddDialog` 批量导入面板）
- 批量添加每行齿轮弹窗（`ModelAddDialog` Settings Modal）
- 批量编辑每行齿轮弹窗（从 `ModelDeleteDialog` 唤起的
  `ProviderConfigEditDialog`）
- 批量编辑"确认"按钮 / "修改配置"批量应用
  （`ModelDeleteDialog` 底部确认按钮 + `hideCapacityFields=true` 模式
  的 `ProviderConfigEditDialog`）

子问题：
- [ ] 规范是否 **列出了** 矩阵中所有允许运维人员配置此概念的面？
      即使只是说"此工作流有意排除——后续 W_NN 处理"。
- [ ] 对于每个配置面，表单状态初始化是否文档化？（哪些字段从哪里预填；
      已有 NULL 或空字段时的行为；遇到后端注入的 `DEFAULT_LLM_MAX_TOKENS`
      sentinel 时的行为）
- [ ] 对于每个配置面，验证契约是否文档化？（哪些字段必填；Save 按钮是仅
      `disabled` 控制，还是处理器内部也再检查一遍——见检查项 9）
- [ ] 对于每个配置面，**保存处理器的 wire payload 格式**是否文档化？
      （camelCase vs snake_case；provider 前缀格式；数字 model_id vs
      名称；可选字段在什么条件下被包含）
- [ ] 对于每个批量模式的面，**销毁性语义**是否被点出？
      （"批量编辑模式下'确认'会删除所有不在 incoming list 中的现存模型"
      这类契约必须在 spec 中可见，而不是埋在
      `batch_create_models_for_tenant` 里。）
- [ ] 如果修复应用到一个面，是否 **明确复制到** 其它所有共享同一概念的
      面？或者为每个剩余面开了 follow-up？

> **W1/W2 后续教训**：W1 步骤 7 命名了 `ModelEditDialog`，spec 承认
> `ProviderConfigEditDialog` 是其同级。六周后我们发现同一类修复在四个
> 面上依然缺失：`ModelAddDialog` 批量导入每行齿轮（commit `4f770de1c`）、
> `ModelAddDialog` 单加 payload 清理（`5985d4ba4`）、`ModelEditDialog`
> 防御性 isFormValid 兜底（`60655efbb`）、`ModelDeleteDialog` "确认"
> 闸 + provider 级批量应用面板（`6dd735162`）。前端模型配置的"4 象限"
> 视图（`add`/`edit` × `single`/`batch`）从未被写下来，所以每次单 bug
> 修复都让其它三个象限保留了 bug。压轴事故（commit `67a75f014`）就是
> 其中两个象限的交互：批量编辑齿轮静默丢弃容量编辑，然后批量编辑确认
> 在每次点击时软删除刚添加的目录行。

### 8. Pydantic Optional 在构造调用点的静默掉值

**主问题：** 当向 request/response schema 添加一个新的 `Optional[X] = None`
字段时，是否审查了每一个 **显式构造** 该 schema 的调用点，并更新它们传入
新字段？

子问题：
- [ ] `grep -rn "ClassName(" backend/ sdk/` 产出一个有限的列表。是否
      每个调用点都被审查？这些构造调用点用的是 `**dict` 透传（安全——
      新字段自动流过去）还是显式 kwargs（不安全——会静默掉到默认值）？
- [ ] 对于用显式 kwargs 的调用点，是否有测试 pin 住构造器的
      `call_args`（不是返回 dict——mock `model_dump` 的话返回 dict 断言
      无论构造器实际收到什么都能平凡通过）？
- [ ] 是否有回归测试验证 schema 字段的"运维人员期望值"最终落到了 DB 列，
      而不是只落到了 schema 默认值？
- [ ] 如果 spec 加了一个"标记"字段（例如 `capacity_source`，`operator`
      vs `provider_candidate` 语义），operator-vs-marker 契约是在构造调用
      点强制的，还是只在调用方"希望它"成立？

> **W1/W2 后续教训**：W1 把 W1/W2 容量字段（`context_window_tokens`、
> `max_output_tokens` 等）加进 `ModelRequest` Pydantic schema。单加和
> 单编辑 service 路径走的是 dict 透传（`dict(model_data) →
> create_model_record`），所以新字段自动落库。但
> `prepare_model_dict`（在 `backend/services/model_provider_service.py`
> 的批量创建路径，2025-08-06 引入，W1/W2 commit 从未碰过它）用的是
> `ModelRequest(model_factory=..., model_name=..., max_tokens=...)`
> ——显式 kwargs，没有 `**`。新的 W2 字段是 `Optional[int] = None`，
> 所以构造器静默地把它们设成 `None`。每个批量拉取的 LLM 都以
> `context_window_tokens=NULL` 落库；只有 legacy `max_tokens` mirror
> 留下了痕迹（glm-5.1 / glm-5.2 事故，commit `8bbd6075a`）。
> 更糟的是，已有测试
> `test_prepare_model_dict_does_not_persist_provider_capacity_candidates`
> 只断言"输出的 dump dict 里不含 W2 字段"——但这个 dump 是 mock 控制的，
> 所以无论构造器实际接收什么 kwargs 这个断言都平凡通过。强化测试同时
> pin `mock_model_request.call_args`（commit `70d231b2d`）才真正堵住了
> 回归口。

### 9. 防御性 Save 处理器兜底

**主问题：** 对于每个由 `disabled={!isValid()}` 控制按钮的 Save / Submit
处理器，处理器函数体顶部 **是否也** 检查了 `if (!isValid()) return`？

子问题：
- [ ] 处理器是否可能被非点击路径触发？（Modal `onOk`、表单 submit、
      键盘 Enter、程序化派发、第三方组件回调）
- [ ] React 的 `disabled` 属性可能比 state update 慢一拍——处理器是否
      容忍"在 disabled 状态下被触发"？
- [ ] 如果验证识别出必填项缺失，处理器是否在发送不完整 payload 之前
      bail out，还是发出去靠后端拒绝？
- [ ] 同样的 guard pattern 是否对称应用到同级对话框？（如果一个对话框
      有 guard 另一个没有，那个缺 guard 的同级会在同一个边界条件上摔跤。）

> **W1/W2 后续教训**：`ModelEditDialog.handleSave` 的 Save 按钮有
> `disabled={!isFormValid()}` 但处理器内部没有兜底 guard。用户为 glm-5.2
> 打开这个对话框（W2 列因为检查项 8 的 bug 在 DB 里是 NULL），看到空的
> 必填字段，不知怎么触发了保存（可能 Modal `onOk` 触发，或在 disabled
> 状态传播之前的 fast-click），然后这一行就以 `context_window_tokens=NULL,
> max_output_tokens=NULL` 通过一个不完整 payload 落了库。Save 按钮被
> disabled 是一个提示，不是一个强制。`ProviderConfigEditDialog` 早就有
> `if (!valid()) return` 在它的处理器里——让两个对话框对称（commit
> `60655efbb`）才补上了缺口。

### 10. wire 协议 key 在 backend 两半之间的一致性

**主问题：** 对于每个既要做"按 key 查找现有"又要做"按 key 删除不在
列表中的"的后端路由，两半是否用 **相同的 key 推导算法** 从同一行计算
key？前端发出的 payload 是否匹配后端 lookup 的预期？

子问题：
- [ ] 构造 key 的每一处是否都用了 **同一个 helper 函数**（例如
      `add_repo_to_name`）？还是其中一半用裸字符串拼接，另一半用 helper？
- [ ] 如果某个行字段为空/None，构造 key 的 helper 是否忽略分隔符？
      裸拼接是否也忽略？（对空 `model_repo` 的不一致处理就是
      glm-4.7 事故。）
- [ ] 是否有测试覆盖"某行 key 的一个分量为空"的场景，并验证 membership
      检查返回预期结果？
- [ ] 前端发出的 `model_id`（或任何 lookup handle）是否匹配后端 lookup
      预期？（`{factory}/{name}` vs 裸 `{name}` vs 数字主键）
- [ ] 当一个前端静默 no-op（bug A）和一个后端销毁性默认行为（bug B）
      相互交互时，失败模式对用户不可见直到数据被销毁。**层间交互**
      是否被显式测试覆盖？

> **W1/W2 后续教训**（commit `67a75f014`）：
> `batch_create_models_for_tenant` 构造 `existing_model_map` 用的 key 是
> `add_repo_to_name(model_repo, model_name)`——当 `model_repo` 为空时
> 返回 `"glm-4.7"`。同一函数十几行上方的删除循环用的是
> `model["model_repo"] + "/" + model["model_name"]`——当
> `model_repo=""` 时返回 `"/glm-4.7"`。对于 DashScope 行（catalog 给
> 裸名 `glm-4.7`，落库时 `model_repo=""`），删除循环的 key 永远匹配不
> 上 catalog id，所以每次批量创建调用都会软删所有现存行。独立的另一
> 个 bug：`ModelDeleteDialog` 齿轮弹窗构造
> `model_id = selectedSingleModel.model_name || selectedSingleModel.id`，
> 发出去是裸 `"glm-4.7"` 而不是 `"dashscope/glm-4.7"`；后端按 `/` 拆，
> 得不到 `model_factory`，所以
> `get_model_by_name_factory(model_name="glm-4.7", model_factory=None)`
> 返回 None，记一条 warning 不报错。前端收到 HTTP 200 无 diff，齿轮
> 弹窗关闭，用户以为容量编辑落地了。这两个 bug 组合起来让齿轮保存不
> 可见地丢失编辑、然后下次"确认"软删除用户刚添加的行。任何一个单独存
> 在都会很快被注意到；交互才让失败模式静默。

## 严重程度校准

应用检查清单时：

- **🟢 OK**：所有子问题已回答，证据已内联（file:line、SQL、具体值）。
- **🟡 Partial**：主问题回答是，≥1 个子问题未回答。
- **🔴 Gap**：主问题回答否，或答案矛盾。

即使有一个 🔴 的工作流不应标记为 Accepted。所有都是 🟡 的工作流
应在实现开始前开启并跟踪后续工作。

## 输出格式

每个工作流的评审写一个表格：

| 检查项 | 状态 | 证据/差距 | 必要行动 |
| --- | --- | --- | --- |
| 1. 用户旅程 | 🟡 | 运维人员可见效果部分描述；无 UI 章节 | 添加"运维人员可见效果"+"配置路径"章节 |
| 2. 前端分解 | N/A | 范围内无前端（纯后端） | N/A |
| 3. 端到端演示 | 🔴 | 验收是抽象指标，无脚本 | 在 §Tests 中添加具体脚本 |
| ... | ... | ... | ... |

每个必要行动要么成为规范编辑，要么成为明确的后续工作。

## 存在原因

W1 工作流通过了 26 个发现的正式评审、三轮实现 PR，并被标记为 Accepted。
在端到端测试的 24 小时内，约 17 个不同问题在目录采用、前端 UX 和运维方面浮现。
检查项 1–6 是该教训的最小形式化。

六周后，W2 PR 的端到端测试又暴露了约 20 个问题，其中几个是静默数据丢失
bug（齿轮保存 no-op + batch_create 软删级联），毁掉了运维人员刚添加的
目录行。每个 bug 都至少符合以下模式之一：

- 同一个概念有多个前端配置面（`add`/`edit` × `single`/`batch` ×
  `per-row`/`provider-level`）；一个面修了，其它面继续 buggy。
- 一个新 schema 字段是 Optional 且默认 None；一个构造调用点用 `**dict`
  透传，另一个用显式 kwargs；显式 kwargs 那个静默掉了新字段。
- 一个 save 处理器只靠 `disabled={!isValid()}`；处理器通过非点击路径
  仍然被触发，落库了不完整行。
- 一个后端路由在相邻的两个循环里用两种不同方式为同一行算 lookup key；
  key 不一致导致每次"确认"都触发级联软删。

检查项 7–10 覆盖这些模式。完整的检查清单是每个 spec 在 implementation
前应该通过的、也是每个 PR 描述里应该回答的。