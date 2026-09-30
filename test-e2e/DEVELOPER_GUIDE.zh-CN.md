# 开发者本地测试与失败用例修复指南

本文适用于仓库内 `test-e2e/` 的正式 D1–D5 测试。开发者在自己的分支修改用例和固定脚本，使用本机配置执行验证，再将正式测试资产随产品代码提交。现有 `test/backend`、`test/sdk` 等 Legacy UT 仍独立维护。

所有命令均从 Nexent 仓库根目录执行。文中的 Case、Feature、Change ID 需要替换成实际 ID。

## 1. 代码、配置和结果放在哪里

| 内容 | 位置 | 是否提交 Git |
| --- | --- | --- |
| 功能定义、业务规则 | `test-e2e/features/<Feature-ID>/feature.yaml` | 是 |
| 用例前置条件、步骤、预期 | `test-e2e/cases/<Case-ID>/case.yaml` | 是 |
| 固定测试脚本 | 同一 Case 目录内的 `test.*` | 是 |
| 脚本选择器、框架、准备声明 | 同一 Case 目录内的 `execution.yaml` | 是 |
| 需求、缺陷、测试修复记录 | `test-e2e/changes/<type>/<Change-ID>.yaml` | 是 |
| registry、Excel、Feature 导航 | `test-e2e/infra/generated/` 和各 Feature 的 `cases.md` | 工具生成后检查差异并提交 |
| 机器配置、账号和密钥 | `<test-home>/config/` | 否 |
| 虚拟环境、浏览器、运行时资产 | `<test-home>/runtime/` 等本地目录 | 否 |
| 执行日志、报告、截图和 Trace | `<test-home>/runs/` | 否 |

`test-home` 是每位开发者自选的绝对路径，必须位于 Git 仓库之外，也不能包含仓库。它不需要与同事或 Ubuntu 的路径相同。正式脚本通过配置 helper 和逻辑资产名称访问资源，不能写入个人绝对路径、固定数据库资源 ID 或明文密钥。

## 2. 首次准备本机环境

### 2.1 基础软件和被测产品

准备 Python 3.11、uv、Node.js 22 或更高版本及 npm。部署容器和 Docker 相关测试还需要 Docker。Windows 示例使用 `py -3.11`；没有 Python Launcher 时，替换为已安装的 Python 3.11 可执行文件。

D1 中的进程内测试通常不需要部署产品；在线 D2、D3、D4、D5 需要对应服务。修改了产品代码后，按项目部署方式更新本地服务，再进行在线测试。运行器不会因为执行 `run` 自动构建镜像或更新容器；正在运行的旧容器不能证明工作区内的产品修复有效。

为会写入数据的测试准备独立测试部署和数据目录。`test-home` 仅隔离测试配置和产物，不能自动隔离已经运行的产品数据库。共用一台机器时，还要检查 Compose 项目、容器名称、网络、端口和实际持久化挂载。D5 故障注入、恢复等测试必须满足用例声明的隔离条件。

### 2.2 创建配置和安装依赖

Windows PowerShell：

```powershell
$TestHome = "D:\nexent-test-suite"

py -3.11 test-e2e/infra/scripts/run-suite.py onboard --test-home $TestHome
py -3.11 test-e2e/infra/scripts/run-suite.py onboard --test-home $TestHome --execute
py -3.11 test-e2e/infra/scripts/run-suite.py bootstrap --test-home $TestHome --execute

$TestPython = Join-Path $TestHome "runtime/test-venv/Scripts/python.exe"
```

希望交互式选择 test-home 和服务地址时，用下面的命令替代上面的两条 `onboard` 命令，并将后续 `$TestHome` 设为实际选择的路径：

```powershell
py -3.11 test-e2e/infra/scripts/run-suite.py onboard --interactive --execute
```

引导只创建缺失文件；已有文件会显示 `KEPT`，不会重新询问或覆盖其中的配置。需要调整已有地址时，直接编辑本机配置。

bootstrap 将 Python 依赖安装到 `<test-home>/runtime/test-venv`，安装 SDK 及其依赖，执行各前端测试包的 `npm ci`，并准备 Chromium。前端 `node_modules` 位于对应仓库包目录，浏览器位于 test-home。已有可用环境不需要每次重复安装；依赖声明或锁文件变化后重新执行。

Linux 的对应入口示例：

```bash
TEST_HOME=/absolute/path/to/nexent-test-suite
python3.11 test-e2e/infra/scripts/run-suite.py onboard --test-home "$TEST_HOME" --execute
python3.11 test-e2e/infra/scripts/run-suite.py bootstrap --test-home "$TEST_HOME" --execute
TEST_PYTHON="$TEST_HOME/runtime/test-venv/bin/python"
```

Linux 的 Chromium 系统库需要另外由主机环境提供。

### 2.3 配置环境变量和测试资产

编辑本机 `<test-home>/config/`，保留模板的字段名称和结构：

| 文件 | 开发者需要配置的内容 |
| --- | --- |
| `environment.yaml` | 前端地址及 Config、Runtime、Northbound、Data Process 等服务地址 |
| `users.yaml` | 本机测试租户、账号和角色；`password_env_key` 引用密钥文件中的变量名 |
| `models.yaml` | 模型能力、Provider、地址和模型名称；`secret_env_key` 引用密钥变量名 |
| `secrets.env` | 上述引用实际使用的密码、API Key 等；使用 `KEY=value` 格式 |
| `daily.env` | 非敏感运行参数，以及产品容器访问测试 HTTP/MCP 服务所需的主机地址 |
| `test-assets.yaml`、`anchor-assets.yaml` | 用例所需的逻辑资产配置，按现有 helper 和用例声明填写 |
| `asset-policy.yaml` | 测试资源保留和清理策略 |
| `pipeline.yaml` | 完整 Daily 的构建、部署等钩子；普通 `run` 验证不要求配置这些部署钩子 |

模板中的 `replace-me` 必须替换。账号必须存在于当前测试部署且具有对应角色；密钥引用已填写不代表登录或模型调用一定成功，实际用例还会验证这些能力。只有对应功能确实未启用的可选配置才可留空。

Windows Docker Desktop 的容器访问宿主机通常使用 `host.docker.internal`。容器内的 `127.0.0.1` 指向容器自身。按实际网络设置 `NEXENT_TEST_ASSETS_CONTAINER_HOST` 和 `NEXENT_TEST_MCP_CONTAINER_HOST`。

不要自行发明环境变量。新增配置需要同步维护读取 helper、适用的 Schema 和示例。不要通过共享 test-home 把机器密钥和地址覆盖到其他开发者或 Ubuntu。

复制并检查仓库提供的静态测试文件：

```powershell
& $TestPython test-e2e/infra/tools/static_assets.py plan --test-home $TestHome --source-assets test-e2e/infra/assets
& $TestPython test-e2e/infra/tools/static_assets.py apply --test-home $TestHome --source-assets test-e2e/infra/assets
& $TestPython test-e2e/infra/tools/static_assets.py verify --test-home $TestHome
& $TestPython test-e2e/infra/scripts/run-suite.py doctor --test-home $TestHome --live
uv pip check --python $TestPython
```

遇到缺失资产或校验冲突时，按命令结果处理；不要拿空文件代替。`doctor --live` 主要检查配置、依赖和服务可达性，不代表所有账号、模型、业务流程已经通过。离线用例可省略 `--live`，并用 `--case <Case-ID>` 缩小检查范围。

## 3. 收到失败结果后如何修改

先定位失败 Case ID，阅读原批次的报告、用例日志、失败步骤和清理记录，再查看对应 Feature、`case.yaml`、`execution.yaml` 和脚本。记录复现时的产品版本、测试分支和环境差异。

| 判断结果 | 修改方法 |
| --- | --- |
| 脚本定位、断言实现、选择器或准备流程错误 | 修复 `test.*`，必要时改 `execution.yaml`；在 `changes/test-fixes/` 新建记录，列出受影响 Case ID |
| 产品违反了正确的验收标准 | 修产品代码；保留可复现的用例，按需补强；在 `changes/bugs/` 记录原因和覆盖缺口 |
| 已确认的需求发生变化或契约存在遗漏 | 更新所属 Feature、Case、脚本和执行绑定，并建立相应需求或缺陷记录 |
| 账号、模型、服务或资产未准备好 | 修本机配置或部署，保持与需求一致的断言 |

用例验收标准正确时，纯脚本修复不必改 `case.yaml`；文件名、选择器和准备声明没变时，也不必改 `execution.yaml`。保留原 Case ID。新增用例使用新 ID，历史契约需要退出时标记 `retired`。

Bugfix 有相关 SPEC 时，沿用其中 Feature、业务规则和 Case 的关联，并结合实际调用路径确认影响。没有可用 SPEC 时，在文档仓库创建轻量 `design.md`，按 [Bugfix design 模板](../.agents/skills/nexent-spec-coding/references/bugfix-design-template.md) 描述完整、内聚的功能边界与最终预期，保留与新需求相同的 `D1-D5 Test Design` 矩阵。它列出功能范围内的已知覆盖，Notes 标注复用、补强、新增、仅回归或不受影响；本次修复与验证范围单独写明。无需强制补齐 proposal/task 或整模块需求文档。

优先复用能复现的用例，缺一个边界时补强原用例，只有缺少必要证明才新增。允许新增 0 条，也不要求每层一条。区分“没有 SPEC”“当前分支没有迁入基线”和“已确认覆盖缺口”：找不到基线时记录未知及检索范围，不自动补全整个功能。矩阵中的 N/A 表示不适用，GAP 表示已知缺口，UNKNOWN 表示覆盖不可确认；这些标注不是 Case ID，也不代表通过。

Bug Change 的 `affected_cases.existing` 放入只需复用或回归的已有用例，`modified` 放入实际修改的 Case 或脚本，`added` 放入新用例。不受影响的 Case 可以保留在 design 的功能覆盖矩阵中，不列入本次执行选择。已有用例能准确检出时 `coverage_gap.type` 可为 `no_gap`；基线不可见时可为 `unknown_baseline`。关联原因和 design 路径记录在 `notes`，不必新增独立 manifest。

Change 文件位于 `changes/{requirements,bugs,refactors,test-fixes}/`，每个文件一条记录。它记录关联关系，正式 Feature 和 Case 仍保留在各自目录。测试修复记录也要列出受影响 Case，方便通过 `--change` 选择验证范围。具体字段按现有 Schema 校验，不要仅创建一篇自由格式说明代替记录。

固定脚本必须验证正式用例的前置条件、操作和预期；不能用常量断言、吞掉异常、随意 skip/xfail 或删除失败断言来获得通过。脚本使用现有资产 helper，并登记测试创建的资源，供清理过程追踪。创建本身属于被测行为时，应在测试步骤内创建并断言，不能靠前置准备绕过。

使用 AI 助手修改时，指定仓库的 [nexent-test-assets](../.agents/skills/nexent-test-assets/SKILL.md) 规范，并提供 Case ID、失败证据、当前产品契约和本机 test-home。涉及产品缺陷或需求文档时，同时遵循仓库的需求/缺陷生命周期规范。

## 4. 校验资产并执行受影响用例

修改了 Feature 或用例设计时先运行设计校验；纯脚本修复可跳过第一条：

```powershell
& $TestPython test-e2e/infra/tools/validate_test_assets.py --phase design --generate
& $TestPython test-e2e/infra/tools/validate_test_assets.py --phase implementation --generate
& $TestPython test-e2e/infra/tools/validate_test_assets.py --phase implementation
```

生成器统一更新 registry、Feature 导航和 Excel。最后一条只读检查会发现生成视图过期。只修改受影响的源文件，但执行全局一致性检查。静态校验通过还需要实际运行。

先复测单条失败用例，再扩大到本次变更影响的范围：

```powershell
$CaseId = "UT-SDK-001"
& $TestPython test-e2e/infra/scripts/run-suite.py plan --test-home $TestHome --case $CaseId
& $TestPython test-e2e/infra/scripts/run-suite.py run --test-home $TestHome --case $CaseId --execute

# Replace with the actual Change ID.
$ChangeId = "TEST-FIX-001"
& $TestPython test-e2e/infra/scripts/run-suite.py plan --test-home $TestHome --change $ChangeId
& $TestPython test-e2e/infra/scripts/run-suite.py run --test-home $TestHome --change $ChangeId --execute
```

也可以重复 `--case` 选择多条，或使用 `--feature <Feature-ID>`、`--stage D2`。省略 `--execute` 只生成计划。Linux 使用同样参数，将 PowerShell 的 `& $TestPython` 替换为 `"$TEST_PYTHON"`，变量名称改为对应 Bash 变量。

优先使用 `run-suite.py run`。它按每条 `execution.yaml` 的声明执行受控服务启动、前置资产准备、测试和资源清理。准备失败会阻止该条业务测试执行。`infra/tools/run_cases.py` 是低层直跑入口，不负责这套资产准备和最终清理，通常不适合开发者首次复现在线用例。

修改了测试或产品代码后创建新批次复测。`resume` 仅适用于代码和配置保持一致、能够确认清理状态的干净中断；不用于把修改后的脚本与原有通过记录拼接。

## 5. 查看结果和排查阻断

运行命令会打印本地批次目录，通常位于 `<test-home>/runs/repository-daily/<batch>/`；目录名中的 daily 不表示本次执行了完整 Daily。

| 产物 | 用途 |
| --- | --- |
| `report.md`、`summary.json` | 汇总通过、失败、阻断及批次是否完整 |
| `plan.json`、`provenance.json` | 核对选择范围和执行时的代码、配置指纹 |
| `cases/<Case-ID>/receipt.json` | 核对用例终态、测试结果和清理结果 |
| 用例目录内的日志和框架产物 | 定位前置准备、测试步骤或框架异常 |
| `runtime/resolved-assets.yaml`、`runtime/asset-journal.jsonl`（产生资产时） | 追踪该用例实际使用、创建的资源 |
| D4 失败产物目录 | 查看截图、Trace；成功用例不保留截图和 Trace |

`BLOCKED`、`TIMEOUT`、`AUTOMATION_ERROR`、`CLEANUP_FAILED` 都不能按通过处理。清理策略可能保留失败现场；检查 receipt 和资源日志后再复跑。某些早期准备失败尚未启动浏览器，因此不会有截图。

常见处理方式：虚拟环境缺失或依赖变化时重跑 bootstrap；配置出现 placeholder 时填写本机配置；服务不可达时检查部署和端口；缺少 preparation 声明时修 `execution.yaml`；生成视图过期时重跑实现阶段生成命令。不要修改全局忽略策略来绕过单条失败。

## 6. 提交前检查和 Daily 衔接

1. 受影响 Case 已实际执行，核对计划数量、所有终态和清理结果。没有运行的范围明确标记未验证。
2. 实现阶段只读校验通过，检查 `git diff` 中正式资产及生成视图的变化。
3. 提交必要的产品修复、Case、脚本、绑定、Feature 和 Change 记录；本机配置、密码、运行结果和截图留在本地。
4. PR 中说明修复原因、执行的 Case ID、结果和未验证范围。保留本机证据供排查，不把测试产物混入代码提交。

截至 2026-09-29，Windows 已完成引导、依赖安装、配置检查、Playwright 启动以及 D1/D2 抽样验证；完整 D3–D5 和中断恢复等仍需逐步实测。仓库入口的全量 `daily` 需要配置部署钩子并完成迁移验证，不能把普通 `run` 当成 Daily 部署验证。

现有 Ubuntu Daily 仍由外部测试套件控制。提交仓库用例不等于已经自动切换该控制器；按项目迁移安排接入后，Daily 消费仓库资产，失败修复继续回到开发分支完成。

更多说明：[测试目录总览](README.md)、[环境准备](infra/environment/README.md)、[逐用例准备和清理](infra/environment/preparation.md)、[尚未完成的迁移验证](infra/migration/runtime-migration-status.md)。
