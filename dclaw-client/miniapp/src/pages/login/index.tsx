import { Button, Input, Text, View } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useState } from "react";

import AssetImage from "../../components/AssetImage";
import PrivacyAuthorization from "../../components/PrivacyAuthorization";
import usePageShare from "../../hooks/usePageShare";
import { requestRoot } from "../../services/api";
import { type LoginResponse, setAuthSession } from "../../services/auth";

import "./index.scss";

export default function LoginPage() {
  usePageShare({
    title: "DClaw｜企业 AI 助手登录",
    path: "/pages/login/index",
  });

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleLogin = async () => {
    if (!username.trim() || !password.trim()) {
      Taro.showToast({ title: "请输入账号和密码", icon: "none" });
      return;
    }

    setSubmitting(true);
    try {
      const response = await requestRoot<LoginResponse>("/auth/login", {
        method: "POST",
        data: {
          username: username.trim(),
          password,
        },
      });
      setAuthSession(response);
      Taro.reLaunch({ url: "/pages/workbench/index" });
    } catch (error) {
      Taro.showToast({
        title: error instanceof Error ? error.message : "登录失败",
        icon: "none",
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <View className="page-shell login-page">
      <View className="login-brand">
        <AssetImage slot="logo" className="login-logo" mode="aspectFit" />
        <Text className="login-subtitle">企业 AI 助手 · 为员工提效</Text>
      </View>
      <AssetImage slot="mascotLogin" className="login-mascot" />
      <View className="card login-card">
        <Text className="login-card-title">登录 DClaw</Text>
        <Text className="field-label">账号</Text>
        <Input
          className="login-input"
          value={username}
          placeholder="请输入账号"
          onInput={(event) => setUsername(String(event.detail.value || ""))}
        />
        <Text className="field-label">密码</Text>
        <Input
          className="login-input"
          password
          value={password}
          placeholder="请输入密码"
          onInput={(event) => setPassword(String(event.detail.value || ""))}
        />
        <Button
          className="login-button"
          loading={submitting}
          onClick={handleLogin}
        >
          登录
        </Button>
      </View>
      <Text className="login-switch">使用账号密码登录</Text>
      <PrivacyAuthorization />
    </View>
  );
}
