import { useCallback, useEffect, useState } from "react";
import { billingApi } from "../../api/modules/billing";
import type { BillingWallet } from "../../api/types/billing";

export function useBillingWallet() {
  const [wallet, setWallet] = useState<BillingWallet | null>(null);
  const [loading, setLoading] = useState(true);
  const [unavailable, setUnavailable] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setWallet(await billingApi.getWallet());
      setUnavailable(false);
    } catch {
      setWallet(null);
      setUnavailable(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const handleSettlement = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => void refresh(), 50);
    };
    window.addEventListener("dclaw:billing-settled", handleSettlement);
    return () => {
      if (timer) clearTimeout(timer);
      window.removeEventListener("dclaw:billing-settled", handleSettlement);
    };
  }, [refresh]);

  return { wallet, loading, unavailable, refresh };
}
