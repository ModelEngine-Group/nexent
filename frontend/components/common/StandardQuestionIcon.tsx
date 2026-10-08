import type { ComponentProps } from "react";
import { QuestionCircleOutlined } from "@ant-design/icons";

export type StandardQuestionIconProps = ComponentProps<
  typeof QuestionCircleOutlined
>;

export function StandardQuestionIcon(props: StandardQuestionIconProps) {
  return <QuestionCircleOutlined {...props} />;
}
