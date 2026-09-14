assistant-ui 已原生支持 A2UI over AG-UI，推荐接入方式是：后端通过 AG-UI 的 ACTIVITY_SNAPSHOT 事件发送 A2UI 操作，前端使用 useAgUiRuntime 接收并渲染。

1. 安装依赖
```npm install @assistant-ui/react-generative-ui @assistant-ui/react-ag-ui```

2. 注册 present 工具
```
import {
  JSONGenerativeUI,
  defaultGenerativeUILibrary,
} from "@assistant-ui/react-generative-ui";

const generative = new JSONGenerativeUI({
  library: defaultGenerativeUILibrary,
});

const toolkit = {
  present: generative.present({ display: "standalone" }),
};
```
然后把 toolkit 按照普通 Generative UI 的方式注册到 assistant-ui。useAgUiRuntime 会自动识别：

```
{
  "type": "ACTIVITY_SNAPSHOT",
  "activityType": "a2ui-surface",
  "content": {
    "a2ui_operations": [
      {
        "version": "v0.9",
        "createSurface": { "surfaceId": "s1" }
      }
    ]
  }
}
```
组件树使用 A2UI 的 adjacency-list 格式，例如 root 节点通过 children 引用其他组件。assistant-ui 会自动把常见 A2UI 组件映射为 Card、Text、Column、Button、TextField 等 Generative UI 组件，同时支持数据模型绑定和 v0.9 / v1.0 格式。

3. 处理按钮事件
如果 A2UI 中包含按钮操作，可以使用 useAgUiSendA2uiAction：

```
const sendAction = useAgUiSendA2uiAction();

const generative = new JSONGenerativeUI({
  library: defaultGenerativeUILibrary,
  actions: createActionRegistry({
    "a2ui:action": ({ payload }) => sendAction(payload),
  }),
});
```
事件会通过新的 AG-UI run 发送给后端，后端可从 forwardedProps.a2uiAction.userAction 获取用户操作。

需要注意：A2UI 的传输协议这里是 AG-UI 的 ACTIVITY_SNAPSHOT，并不是直接把 A2UI JSON 放进普通 assistant message。如果你的后端不是 AG-UI，需要先将 A2UI 操作转换成该事件格式。完整说明见 [A2UI over AG-UI](https://www.assistant-ui.com/docs/tools/a2ui)，相关 Generative UI 配置见 [Generative UI](https://www.assistant-ui.com/docs/tools/generative-ui)。

最后，因为我们目前sse chunk还没有适配AGUI，所以只能令a2ui相关的type符合AGUI的规范去做。