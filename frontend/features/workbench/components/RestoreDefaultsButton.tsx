import { Button, type ButtonProps } from "antd";

export function RestoreDefaultsButton(props: ButtonProps) {
  return (
    <Button
      {...props}
      type="text"
      className="!px-0 !text-muted-foreground hover:!bg-transparent hover:!text-foreground"
    />
  );
}
