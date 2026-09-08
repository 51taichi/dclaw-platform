import { createGlobalStyle } from "antd-style";
import {
  ConfigProvider,
  bailianDarkTheme,
  bailianTheme,
} from "@agentscope-ai/design";
import { App as AntdApp, Spin } from "antd";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import jaJP from "antd/locale/ja_JP";
import ruRU from "antd/locale/ru_RU";
import idID from "antd/locale/id_ID";
import type { Locale } from "antd/es/locale";
import { theme as antdTheme } from "antd";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import "dayjs/locale/zh-cn";
import "dayjs/locale/ja";
import "dayjs/locale/ru";
import "dayjs/locale/id";
dayjs.extend(relativeTime);
import ClientLayout from "./layouts/ClientLayout";
import AdminLayout from "./layouts/AdminLayout";
import { ThemeProvider, useTheme } from "./contexts/ThemeContext";
import { PluginProvider, usePlugins } from "./plugins/PluginContext";
import { ApprovalProvider } from "./contexts/ApprovalContext";
import { RuntimeEventProvider } from "./contexts/RuntimeEventContext";
import { Suspense } from "react";
import { lazyImportWithRetry } from "./utils/lazyWithRetry";

const LoginPage = lazyImportWithRetry("./pages/Login/index");
import { languageApi } from "./api/modules/language";
import { AuthProvider, useAuth } from "./contexts/AuthContext";

import "./styles/layout.css";
import "./styles/form-override.css";

const antdLocaleMap: Record<string, Locale> = {
  zh: zhCN,
  en: enUS,
  ja: jaJP,
  ru: ruRU,
  id: idID,
};

const dayjsLocaleMap: Record<string, string> = {
  zh: "zh-cn",
  en: "en",
  ja: "ja",
  ru: "ru",
  id: "id",
};

const GlobalStyle = createGlobalStyle`
* {
  margin: 0;
  box-sizing: border-box;
}
`;

const FullScreenLoading = () => (
  <div
    style={{
      display: "flex",
      justifyContent: "center",
      alignItems: "center",
      height: "100vh",
      width: "100vw",
    }}
  >
    <Spin size="large" />
  </div>
);

function AuthGuard({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();

  if (status === "loading") return <FullScreenLoading />;
  if (status === "auth-required")
    return (
      <Navigate
        to={`/login?redirect=${encodeURIComponent(window.location.pathname)}`}
        replace
      />
    );
  return <>{children}</>;
}

function RoleGuard({
  children,
  requireAdmin,
}: {
  children: React.ReactNode;
  requireAdmin?: boolean;
}) {
  const { role } = useAuth();

  if (requireAdmin && role !== "admin") {
    // If not admin, redirect to client workbench
    return <Navigate to="/workbench" replace />;
  }

  return <>{children}</>;
}

function getRouterBasename(pathname: string): string | undefined {
  return /^\/console(?:\/|$)/.test(pathname) ? "/console" : undefined;
}

function AppInner() {
  const basename = getRouterBasename(window.location.pathname);
  const { i18n } = useTranslation();
  const { isDark } = useTheme();
  const { loading: pluginsLoading } = usePlugins();
  const selectedTheme = isDark ? bailianDarkTheme : bailianTheme;
  const lang = i18n.resolvedLanguage || i18n.language || "en";
  const [antdLocale, setAntdLocale] = useState<Locale>(
    antdLocaleMap[lang] ?? enUS,
  );

  useEffect(() => {
    if (!localStorage.getItem("language")) {
      languageApi
        .getLanguage()
        .then(({ language }) => {
          if (language && language !== i18n.language) {
            i18n.changeLanguage(language);
            localStorage.setItem("language", language);
          }
        })
        .catch((err) =>
          console.error("Failed to fetch language preference:", err),
        );
    }
  }, []);

  useEffect(() => {
    const handleLanguageChanged = (lng: string) => {
      const shortLng = lng.split("-")[0];
      setAntdLocale(antdLocaleMap[shortLng] ?? enUS);
      dayjs.locale(dayjsLocaleMap[shortLng] ?? "en");
    };

    // Set initial dayjs locale
    dayjs.locale(dayjsLocaleMap[lang.split("-")[0]] ?? "en");

    i18n.on("languageChanged", handleLanguageChanged);
    return () => {
      i18n.off("languageChanged", handleLanguageChanged);
    };
  }, [i18n]);

  // Wait for plugins to load before rendering routes that might be patched
  if (pluginsLoading) {
    return <FullScreenLoading />;
  }

  return (
    <BrowserRouter basename={basename}>
      <GlobalStyle />
      <ConfigProvider
        {...selectedTheme}
        prefix="qwenpaw"
        prefixCls="qwenpaw"
        locale={antdLocale}
        theme={{
          ...(selectedTheme as any)?.theme,
          algorithm: isDark
            ? antdTheme.darkAlgorithm
            : antdTheme.defaultAlgorithm,
          token: {
            colorPrimary: "#2563EB",
            colorInfo: "#2563EB",
            colorSuccess: "#10b981",
            colorWarning: "#f59e0b",
            colorError: "#ef4444",
            colorTextLightSolid: "#fff",
            borderRadius: 10,
            fontFamily:
              "'PingFang SC', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif",
          },
          components: {
            Button: {
              borderRadius: 8,
              colorTextLightSolid: "#ffffff",
              colorPrimaryText: "#ffffff",
            },
            Menu: {
              itemBorderRadius: 8,
            },
          },
        }}
      >
        <AntdApp>
          <RuntimeEventProvider>
            <ApprovalProvider>
              <Routes>
                <Route
                  path="/login"
                  element={
                    <Suspense fallback={null}>
                      <LoginPage />
                    </Suspense>
                  }
                />
                <Route
                  path="/admin/*"
                  element={
                    <AuthGuard>
                      <RoleGuard requireAdmin>
                        <AdminLayout />
                      </RoleGuard>
                    </AuthGuard>
                  }
                />
                <Route
                  path="/*"
                  element={
                    <AuthGuard>
                      <ClientLayout />
                    </AuthGuard>
                  }
                />
              </Routes>
            </ApprovalProvider>
          </RuntimeEventProvider>
        </AntdApp>
      </ConfigProvider>
    </BrowserRouter>
  );
}

function App() {
  return (
    <AuthProvider>
      <ThemeProvider>
        <PluginProvider>
          <AppInner />
        </PluginProvider>
      </ThemeProvider>
    </AuthProvider>
  );
}

export default App;
