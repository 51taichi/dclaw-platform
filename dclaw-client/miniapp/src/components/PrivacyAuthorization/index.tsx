import { Button, Text, View } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { useEffect, useRef, useState } from "react";

import "./index.scss";

const DEFAULT_PRIVACY_CONTRACT_NAME = "《DClaw 用户隐私保护指引》";
const PRIVACY_AGREE_BUTTON_ID = "dclaw-privacy-agree-button";

type PrivacyResolve = (
  option: Taro.onNeedPrivacyAuthorization.ResolveOption,
) => void;

export default function PrivacyAuthorization() {
  const [visible, setVisible] = useState(false);
  const [contractName, setContractName] = useState(
    DEFAULT_PRIVACY_CONTRACT_NAME,
  );
  const pendingResolveRef = useRef<PrivacyResolve | null>(null);

  useEffect(() => {
    Taro.getPrivacySetting({
      success: (result) => {
        setContractName(
          result.privacyContractName || DEFAULT_PRIVACY_CONTRACT_NAME,
        );
        setVisible(Boolean(result.needAuthorization));
      },
    });

    Taro.onNeedPrivacyAuthorization((resolve) => {
      pendingResolveRef.current = resolve;
      setVisible(true);
      resolve({ event: "exposureAuthorization" });
    });
  }, []);

  const openPrivacyContract = () => {
    Taro.openPrivacyContract({
      fail: () => {
        Taro.showToast({ title: "隐私保护指引暂时无法打开", icon: "none" });
      },
    });
  };

  const handleAgreePrivacyAuthorization = () => {
    pendingResolveRef.current?.({
      event: "agree",
      buttonId: PRIVACY_AGREE_BUTTON_ID,
    });
    pendingResolveRef.current = null;
    setVisible(false);
  };

  const handleDisagree = () => {
    pendingResolveRef.current?.({ event: "disagree" });
    pendingResolveRef.current = null;
    setVisible(false);
    Taro.showToast({
      title: "未同意前，文件、图片、剪贴板等能力可能无法使用",
      icon: "none",
    });
  };

  if (!visible) {
    return null;
  }

  return (
    <View className="privacy-auth">
      <View className="privacy-auth__mask" />
      <View className="privacy-auth__sheet">
        <Text className="privacy-auth__title">隐私保护提示</Text>
        <Text className="privacy-auth__content">
          为了上传文件、选择图片、复制链接等功能正常使用，请先阅读并同意
        </Text>
        <Text className="privacy-auth__link" onClick={openPrivacyContract}>
          {contractName}
        </Text>
        <View className="privacy-auth__actions">
          <Button
            className="privacy-auth__button privacy-auth__button--ghost"
            onClick={handleDisagree}
          >
            暂不使用
          </Button>
          <Button
            id={PRIVACY_AGREE_BUTTON_ID}
            className="privacy-auth__button privacy-auth__button--primary"
            openType="agreePrivacyAuthorization"
            onAgreePrivacyAuthorization={handleAgreePrivacyAuthorization}
          >
            同意并继续
          </Button>
        </View>
      </View>
    </View>
  );
}
