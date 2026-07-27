import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button, Form, Input } from "antd";
import { useAppMessage } from "../../hooks/useAppMessage";
import { authApi } from "../../api/modules/auth";
import { setAuthToken } from "../../api/config";
import { useAuth } from "../../contexts/AuthContext";
import loginMascotAsset from "../../assets/login/login-mascot.png";
import loginGreetingAsset from "../../assets/login/login-greeting.png";
import loginUsernameAsset from "../../assets/login/login-username.png";
import loginPasswordAsset from "../../assets/login/login-password.png";
import loginButtonAsset from "../../assets/login/login-button.png";
import styles from "./index.module.less";

export default function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { checkAuth } = useAuth();
  const [loading, setLoading] = useState(false);
  const [isRegister, setIsRegister] = useState(false);
  const [hasUsers, setHasUsers] = useState(true);
  const [isLoginButtonImageReady, setIsLoginButtonImageReady] = useState(false);
  const { message } = useAppMessage();

  useEffect(() => {
    authApi
      .getStatus()
      .then((res) => {
        if (!res.enabled) {
          navigate("/workbench", { replace: true });
          return;
        }
        setHasUsers(res.has_users);
        setIsRegister(!res.has_users);
      })
      .catch(() => {});
  }, [navigate]);

  useEffect(() => {
    let isActive = true;
    const image = new Image();

    image.onload = () => {
      if (isActive) {
        setIsLoginButtonImageReady(true);
      }
    };
    image.onerror = () => {
      if (isActive) {
        setIsLoginButtonImageReady(false);
      }
    };
    image.src = loginButtonAsset;

    return () => {
      isActive = false;
      image.onload = null;
      image.onerror = null;
    };
  }, []);

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true);
    try {
      const raw = searchParams.get("redirect") || "/workbench";
      const redirect =
        raw.startsWith("/") && !raw.startsWith("//") ? raw : "/workbench";

      if (isRegister) {
        const res = await authApi.register(values.username, values.password);
        if (res.token) {
          setAuthToken(res.token);
          await checkAuth();
          message.success(t("login.registerSuccess"));
          navigate(redirect, { replace: true });
        }
      } else {
        const res = await authApi.login(values.username, values.password);
        if (res.token) {
          setAuthToken(res.token);
          await checkAuth();
          navigate(redirect, { replace: true });
        } else {
          message.info(t("login.authNotEnabled"));
          await checkAuth();
          navigate(redirect, { replace: true });
        }
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "";
      const isRateLimited = errorMessage.toLowerCase().includes("too many");
      message.error(
        isRegister
          ? errorMessage || t("login.registerFailed")
          : isRateLimited
          ? t("login.tooManyAttempts")
          : t("login.failed"),
      );
    } finally {
      setLoading(false);
    }
  };

  const pageTitle = isRegister ? t("login.registerTitle") : t("login.title");
  const submitText = isRegister ? t("login.register") : t("login.submit");
  const shouldUseLoginButtonImage = !isRegister && isLoginButtonImageReady;

  return (
    <main className={styles.loginPage} data-design-ratio="8000:4500">
      <div className={styles.shell}>
        <section className={styles.hero} aria-label="DClaw">
          <div className={styles.mascotStage} aria-hidden="true">
            <div className={styles.hello}>Hello ~</div>
            <img
              className={styles.mascot}
              src={loginMascotAsset}
              alt=""
              draggable={false}
            />
          </div>
        </section>

        <section className={styles.card} aria-labelledby="login-title">
          <div className={styles.cardInner}>
            <img
              className={styles.greeting}
              src={loginGreetingAsset}
              alt={pageTitle}
              draggable={false}
            />
            <h1 id="login-title" className={styles.srOnly}>
              {pageTitle}
            </h1>

            {!hasUsers && (
              <p className={styles.hint}>{t("login.firstUserHint")}</p>
            )}

            <Form
              className={styles.form}
              layout="vertical"
              onFinish={onFinish}
              autoComplete="off"
              size="large"
            >
              <Form.Item
                className={`${styles.formItem} ${styles.usernameItem}`}
                name="username"
                label={
                  <span className={styles.imageLabel}>
                    <img
                      src={loginUsernameAsset}
                      alt={t("login.usernamePlaceholder")}
                      draggable={false}
                    />
                  </span>
                }
                rules={[
                  { required: true, message: t("login.usernameRequired") },
                ]}
              >
                <Input
                  className={styles.input}
                  placeholder={t("login.usernamePlaceholder")}
                  autoComplete="username"
                  autoFocus
                />
              </Form.Item>

              <Form.Item
                className={`${styles.formItem} ${styles.passwordItem}`}
                name="password"
                label={
                  <span className={styles.imageLabel}>
                    <img
                      src={loginPasswordAsset}
                      alt={t("login.passwordPlaceholder")}
                      draggable={false}
                    />
                  </span>
                }
                rules={[
                  { required: true, message: t("login.passwordRequired") },
                ]}
              >
                <Input.Password
                  className={styles.input}
                  placeholder={t("login.passwordPlaceholder")}
                  autoComplete={
                    isRegister ? "new-password" : "current-password"
                  }
                />
              </Form.Item>

              <Form.Item className={styles.submitItem}>
                <Button
                  type="primary"
                  htmlType="submit"
                  loading={loading}
                  block
                  className={`${styles.submitButton} ${
                    shouldUseLoginButtonImage ? styles.loginButtonImage : ""
                  }`}
                >
                  {submitText}
                </Button>
              </Form.Item>
            </Form>

            <div className={styles.footer}>© DeepMage Technology Co.,Ltd</div>
          </div>
        </section>
      </div>
    </main>
  );
}
