# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise Prompt page objects in Chromium without claiming live acceptance."""
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[4]


def test_debug_compare_uses_visible_accessible_editors(tmp_path):
    script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require(TYPESCRIPT);
const {chromium} = require(PLAYWRIGHT);
const {expect} = require(PLAYWRIGHT + '/test');
const mod = {exports:{}};
const compiled = ts.transpileModule(fs.readFileSync(ROOT + '/test-e2e/infra/automation/d4/pages/agent.page.ts','utf8'), {
  compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}
}).outputText;
new Function('require','module','exports',compiled)(
  name => name === 'playwright/test' ? require(PLAYWRIGHT + '/test') :
    name.includes('runtime-config') ? {appPath:x=>x} : require(name), mod, mod.exports);
(async()=>{
 const browser=await chromium.launch({headless:true, ...(process.platform==='win32'?{channel:'msedge'}:{})});
 try {
  const page=await browser.newPage({baseURL:'http://fixture'});
  await page.setContent(`
    <textarea aria-label="智能体描述" placeholder="新版描述提示">persisted description</textarea>
    <button aria-pressed="true">智能体调试</button>
    <div data-testid="agent-debug-panel">
      <button id="compare-mode" aria-pressed="false">切换对比模式</button>
      <div id="normal"><textarea aria-label="对话输入" placeholder=""></textarea></div>
      <div id="compare" hidden>
        <div class="flex h-full w-full flex-col"><select aria-label="左模型"><option>A</option></select><div id="left"></div></div>
        <div class="flex h-full w-full flex-col"><select aria-label="右模型"><option>B</option></select><div id="right"></div></div>
        <div role="textbox" contenteditable="true" aria-label="对话输入"></div>
      </div>
      <button id="send">发送</button>
    </div>
    <script>
      const normal=document.querySelector('#normal'), compare=document.querySelector('#compare'), toggle=document.querySelector('#compare-mode');
      toggle.onclick=()=>{
        const enabled=toggle.getAttribute('aria-pressed')!=='true';
        toggle.setAttribute('aria-pressed',String(enabled));
        normal.hidden=enabled;compare.hidden=!enabled;
      };
      document.querySelector('#send').onclick=()=>{
        const text=compare.querySelector('[contenteditable]').textContent;
        for(const id of ['left','right']) {
          const answer=document.createElement('div');
          answer.setAttribute('data-slot','aui_assistant-message-root');
          const content=document.createElement('div');content.setAttribute('data-citation-index-map','{}');
          const md=document.createElement('div');md.className='aui-md';md.textContent=text;
          content.append(md);answer.append(content);document.getElementById(id).append(answer);
        }
      };
    </script>`);
  assert.equal(await page.getByRole('textbox',{name:'智能体描述',exact:true}).inputValue(),'persisted description');
  const agent=new mod.exports.AgentPage(page);
  await agent.openDebugCompare();
  assert.deepEqual(await agent.sendDebugCompare('old-marker','old-marker'),['old-marker','old-marker']);
  assert.deepEqual(await agent.sendDebugCompare('new-marker','new-marker'),['new-marker','new-marker']);
  assert.equal(await page.locator('[data-slot="aui_assistant-message-root"]').count(),4);
  await agent.closeDebugCompare();
  await expect(page.getByRole('textbox',{name:'对话输入',exact:true})).toHaveCount(1);
  await page.getByRole('textbox',{name:'对话输入',exact:true}).fill('normal input');
  await page.route('http://fixture/agents', route=>route.fulfill({contentType:'text/html; charset=utf-8',body:`
    <button>新建智能体</button><input placeholder="按名称、描述或标签搜索">
    <article><button aria-label="Owned Agent Neighbor">Neighbor</button>
      <button aria-label="更多操作" onclick="document.querySelector('#configure').onclick=()=>location.href='/agents/12';document.querySelector('#menu').hidden=false">More</button></article>
    <article><button aria-label="Owned Agent">Owned Agent</button>
      <button aria-label="更多操作" onclick="document.querySelector('#configure').onclick=()=>location.href='/agents/77';document.querySelector('#menu').hidden=false">More</button></article>
    <div id="menu" role="menu" hidden><button id="configure" role="menuitem">配置</button></div>`}));
  await page.route('http://fixture/agents/77', route=>route.fulfill({contentType:'text/html; charset=utf-8',body:`
    <input placeholder="请输入智能体名称" value="Owned Agent"><h2>模型与提示词</h2>`}));
  await agent.select('Owned Agent');
  await expect(page).toHaveURL('http://fixture/agents/77');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    for key, path in [('TYPESCRIPT', ROOT / 'frontend/node_modules/typescript/lib/typescript.js'),
                      ('PLAYWRIGHT', ROOT / 'test-e2e/infra/automation/d4/node_modules/playwright'),
                      ('ROOT', ROOT)]:
        script = script.replace(key, json.dumps(str(path)))
    path = tmp_path / 'prompt-selectors.cjs'
    path.write_text(script, encoding='utf-8')
    result = subprocess.run(['node', str(path)], text=True, encoding='utf-8',
                            capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
