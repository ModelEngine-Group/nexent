import { expect, type Locator, type Page } from "playwright/test";
import { appPath } from "../runner/runtime-config";

export class McpPage {
  constructor(readonly page: Page) {}

  async openMine(): Promise<void> {
    await this.page.goto(appPath("/mcp-space"), { waitUntil: "domcontentloaded" });
    await this.page.getByRole("tab", { name: /我的MCP/ }).click();
    await expect(this.page.getByRole("button", { name: /^添加\s*MCP\s*服务$/ })).toBeVisible();
  }

  card(name: string): Locator {
    return this.page
      .getByRole("heading", { name, exact: true })
      .locator("xpath=ancestor::div[contains(@class,'rounded-xl') and contains(@class,'shadow-sm')][1]");
  }

  async search(name: string): Promise<void> {
    await this.page.getByPlaceholder(/^(搜索 MCP 服务名称、描述或标签|按名称或标签检索 MCP 服务)$/).fill(name);
    await expect(this.page.getByRole("heading", { name, exact: true })).toBeVisible({ timeout: 180000 });
  }

  async resolveId(name: string): Promise<number> {
    const id = await this.findId(name);
    if (id === null) throw new Error(`expected exactly one MCP ${name}, found 0`);
    return id;
  }

  async findId(name: string): Promise<number | null> {
    const response = await this.page.request.get("/api/mcp/list");
    if (!response.ok()) throw new Error(`MCP list returned ${response.status()}`);
    const body = await response.json();
    const rows = body.remote_mcp_server_list || body.data || [];
    const matches = rows.filter((row: any) => (row.remote_mcp_server_name || row.name) === name);
    if (matches.length === 0) return null;
    if (matches.length !== 1) throw new Error(`expected exactly one MCP ${name}, found ${matches.length}`);
    const id = Number(matches[0].mcp_id || matches[0].id);
    if (!Number.isInteger(id) || id <= 0) throw new Error(`MCP ${name} omitted its id`);
    return id;
  }

  private async openAdd(tab: string): Promise<{ dialog: Locator; panel: Locator }> {
    await this.page.getByRole("button", { name: /^添加\s*MCP\s*服务$/ }).click();
    const dialog = this.page.getByRole("dialog", { name: /^添加\s*MCP\s*服务/ });
    await dialog.getByRole("tab", { name: tab, exact: true }).click();
    const panel = dialog.locator('[role="tabpanel"]:visible');
    await expect(panel).toHaveCount(1);
    return { dialog, panel };
  }

  async addRemote(name: string, url: string): Promise<void> {
    const { dialog, panel } = await this.openAdd("添加MCP服务器");
    await panel.getByPlaceholder("服务器名称").fill(name);
    await panel.getByPlaceholder(/服务器URL/).fill(url);
    await panel.getByPlaceholder("服务描述").fill(`controlled remote ${name}`);
    const response = this.page.waitForResponse((r) => /\/api\/.*mcp/i.test(r.url()) && r.request().method() === "POST");
    await dialog.getByRole("button", { name: "保存并添加", exact: true }).click();
    if (!(await response).ok()) throw new Error("Remote MCP creation failed");
    await this.search(name);
  }

  async addContainer(name: string, configJson: string, port: number): Promise<void> {
    const { dialog, panel } = await this.openAdd("添加容器化MCP服务");
    await panel.getByPlaceholder("请输入MCP服务器配置JSON").fill(configJson);
    await panel.getByPlaceholder("请填写服务名称").fill(name);
    await panel.getByPlaceholder("请输入端口号").fill(String(port));
    await panel.getByPlaceholder("服务描述").fill(`controlled container ${name}`);
    await dialog.getByRole("button", { name: "保存并添加", exact: true }).click();
    await this.search(name);
  }

  async addApi(name: string, serverUrl: string, openApiJson: string): Promise<void> {
    const { dialog, panel } = await this.openAdd("API转换为MCP");
    await panel.getByPlaceholder(/服务名称/).fill(name);
    await panel.getByPlaceholder(/服务器地址|Server URL|服务地址/).fill(serverUrl);
    await panel.getByPlaceholder("服务描述").fill(`controlled api ${name}`);
    await panel.getByPlaceholder("请输入OpenAPI JSON配置").fill(openApiJson);
    await dialog.getByRole("button", { name: "保存并添加", exact: true }).click();
    await this.search(name);
  }

  async health(name: string): Promise<void> {
    const card = this.card(name);
    const [checked] = await Promise.all([
      this.page.waitForResponse((r) => /\/mcp\/.*health|\/mcp\/health|test-connection/i.test(r.url())),
      card.getByRole("button", { name: "连通性校验", exact: true }).click(),
    ]);
    if (!checked.ok()) {
      const detail = (await checked.text().catch(() => "")).slice(0, 1000);
      const failure = new Error(`MCP ${name} product health check returned ${checked.status()}: ${detail}`);
      failure.name = "ProductFailure";
      throw failure;
    }
    await expect(this.page.getByText("mcp服务器连接成功", { exact: true })).toBeVisible();
  }

  async enable(name: string): Promise<void> {
    const button = this.card(name).getByRole("button", { name: /启用|已启用/ });
    if ((await button.innerText()).trim() === "启用") await button.click();
    await expect(button).toHaveText("已启用");
  }

  async openTools(name: string, toolName: string): Promise<void> {
    await this.card(name).getByRole("button", { name, exact: true }).click();
    const dialog = this.page.getByRole("dialog");
    await dialog.getByRole("button", { name: /查看工具|工具/ }).click();
    await expect(this.page.getByText(toolName, { exact: true })).toBeVisible();
    await this.page.keyboard.press("Escape");
    await this.page.keyboard.press("Escape");
  }

  async delete(name: string): Promise<void> {
    await this.search(name);
    const card = this.card(name);
    await card.getByRole("button", { name: "更多操作", exact: true }).click();
    await this.page.getByRole("menuitem", { name: "删除", exact: true }).click();
    const dialog = this.page.locator(".ant-modal-confirm:visible");
    await expect(dialog).toBeVisible();
    const removed = this.page.waitForResponse((r) => r.request().method() === "DELETE" && /\/api\/.*mcp/i.test(r.url()));
    await dialog.getByRole("button", { name: /删\s*除|Delete/ }).click();
    const response = await removed;
    if (!response.ok()) throw new Error(`MCP delete returned ${response.status()}`);
    await expect(dialog).toBeHidden({ timeout: 120_000 });
    await expect(this.page.getByRole("heading", { name, exact: true })).toHaveCount(0);
  }
}
