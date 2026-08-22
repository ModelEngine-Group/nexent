---
globs: frontend/app/**,frontend/components/**
alwaysApply: false
---
# Frontend UI Standards Rules

## Principle
Use Ant Design as primary UI library with minimal Tailwind CSS. Prioritize mature Ant Design solutions for responsive layouts. Avoid secondary encapsulation unless necessary.

## Technology Usage Guidelines
- **Ant Design**: Forms, data display, complex interactions (`<Button>`, `<Modal>`, `<Form>`)
- **Tailwind CSS**: Spacing, layout, simple styling (`className="flex items-center gap-2 text-sm"`)
- **Inline Styles**: Special cases (`style={{ fontSize: "48px" }}`)
- **Override AntD**: Use `<style jsx global>` when necessary

## Layout Standards

### Global Layout
Use Header, Sider, Footer, Content structure. Reference: https://ant.design/components/layout-cn

```tsx
const { Header, Footer, Sider, Content } = Layout;

<Layout>
  <Header>Header</Header>
  <Layout>
    <Sider width="25%">Sider</Sider>
    <Content>Content</Content>
  </Layout>
  <Footer>Footer</Footer>
</Layout>
```

### Responsive Grid
Use AntD Grid for responsive layouts. Reference: https://ant.design/components/grid-cn

```tsx
<Row gutter={{ xs: 8, sm: 16, md: 24, lg: 32 }}>
  <Col span={6}>col-6</Col>
  <Col span={6}>col-6</Col>
  <Col span={6}>col-6</Col>
  <Col span={6}>col-6</Col>
</Row>
```

### Flex Layout
Use AntD Flex for component alignment. Reference: https://ant.design/components/flex-cn

```tsx
<Flex vertical className="h-full overflow-hidden">
  <Row><Col>Content 1</Col></Row>
  <Row><Col>Content 2</Col></Row>
  <Row className="flex:1 min-h-0">
    <Col><Flex className="h-full overflow-hidden">...</Flex></Col>
  </Row>
</Flex>
```

## Component Standards

### Modals
1. **Complex Modal**: For reusable modals with custom content
2. **Simple Modal**: Use `useConfirmModal` for one-time confirmations

#### Modal Standards
- Use `centered` for positioning
- Confirm buttons: `type="primary" danger={true}`
- i18n keys: `common.cancel`, `common.confirm`
- Icon: `<ExclamationCircleFilled />` aligned with title

```tsx
// Complex modal
<Modal
  open={isOpen}
  centered
  okButtonProps={{ type: "primary", danger: true }}
  okText={t("common.confirm")}
>
  <div className="flex items-start gap-4">
    <ExclamationCircleFilled style={{ color: token.colorWarning, fontSize: '22px' }} />
    <div>
      <div className="font-medium">{t("title")}</div>
      <div className="text-sm">{t("content")}</div>
    </div>
  </div>
</Modal>

// Simple modal
const { confirm } = useConfirmModal();
confirm({
  title: t("delete.confirmTitle"),
  content: t("delete.confirmContent"),
  onOk: () => { /* ... */ }
});
```

### Icon Library
- **Primary**: `lucide-react` for consistency
- **Fallback**: `@ant-design/icons` when lucide-react lacks icons

```tsx
import { ExternalLink } from "lucide-react";
import { PlusOutlined } from '@ant-design/icons';

<ExternalLink />
<PlusOutlined />
```

## i18n Usage

```tsx
import { useTranslation, Trans } from "react-i18next";

// Simple text
t("common.confirm")

// HTML content
<Trans
  i18nKey="modal.description"
  values={{ title }}
  components={{ strong: <strong /> }}
/>
```
