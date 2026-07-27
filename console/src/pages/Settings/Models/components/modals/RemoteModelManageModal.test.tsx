import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  buildAddModelBody,
  RemoteModelManageModal,
} from "./RemoteModelManageModal";
import type { ProviderInfo } from "../../../../../api/types";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));

vi.mock("../../../../../contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false }),
}));

vi.mock("../../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: {
      error: vi.fn(),
      info: vi.fn(),
      success: vi.fn(),
      warning: vi.fn(),
    },
  }),
}));

vi.mock("../../../../../api", () => ({
  default: {},
}));

vi.mock("@agentscope-ai/design", () => {
  const Button = ({
    children,
    icon,
    ...props
  }: React.PropsWithChildren<{
    icon?: React.ReactNode;
    onClick?: () => void;
    "aria-label"?: string;
  }>) => (
    <button {...props}>
      {icon}
      {children}
    </button>
  );

  const Form = ({ children }: React.PropsWithChildren) => (
    <form>{children}</form>
  );
  Form.useForm = () => [
    {
      resetFields: vi.fn(),
      validateFields: vi.fn(),
    },
  ];
  Form.Item = ({ children }: React.PropsWithChildren) => <div>{children}</div>;

  const Input = (props: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input {...props} />
  );
  const Modal = ({
    children,
    open,
  }: React.PropsWithChildren<{ open?: boolean }>) =>
    open ? <div role="dialog">{children}</div> : null;
  Modal.confirm = vi.fn();

  return {
    Button,
    Form,
    Input,
    Modal,
    Tag: ({ children }: React.PropsWithChildren) => <span>{children}</span>,
    Tooltip: ({ children }: React.PropsWithChildren) => <>{children}</>,
  };
});

const provider: ProviderInfo = {
  id: "volcengine-cn",
  name: "Volcano Engine",
  api_key_prefix: "",
  chat_model: "OpenAIChatModel",
  models: [
    {
      id: "builtin-model",
      name: "Builtin Model",
      supports_multimodal: false,
      supports_image: false,
      supports_video: false,
      generate_kwargs: {},
    },
  ],
  extra_models: [
    {
      id: "manual-model",
      name: "Manual Model",
      supports_multimodal: false,
      supports_image: false,
      supports_video: false,
      generate_kwargs: {},
    },
  ],
  is_custom: false,
  is_local: false,
  support_model_discovery: false,
  support_connection_check: true,
  freeze_url: true,
  require_api_key: true,
  api_key: "",
  base_url: "",
  generate_kwargs: {},
};

describe("RemoteModelManageModal", () => {
  it("uses a supported dimension for Tongyi Vision Flash", () => {
    expect(
      buildAddModelBody(
        "tongyi-embedding-vision-flash-2026-03-06",
        "Tongyi Embedding Vision Flash",
        "embedding",
        "dashscope",
      ),
    ).toMatchObject({
      model_type: "embedding",
      embedding_protocol: "dashscope_multimodal",
      embedding_dimensions: 768,
    });
  });

  it("shows delete actions for both builtin and manually added models", () => {
    render(
      <RemoteModelManageModal
        provider={provider}
        open
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
    );

    expect(
      screen.getAllByRole("button", { name: "common.delete" }),
    ).toHaveLength(2);
  });
});
