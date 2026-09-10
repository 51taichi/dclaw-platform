import { createContext } from "react";
import type { ExpertIdentity } from "../utils/expertIdentity";

// SDK cards cache their initial renderer. Context keeps the mounted card's
// identity current when the asynchronous agent lookup finishes.
export const ExpertIdentityContext = createContext<ExpertIdentity | null>(null);
