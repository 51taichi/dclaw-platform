/**
 * dynamicModuleRegistry.ts
 *
 * Runtime dynamic module discovery using Vite's import.meta.glob
 * Replaces the need for auto-generated registerHostModules.ts
 *
 * Benefits:
 * - No generated files to commit
 * - No merge conflicts on module registry
 * - Automatically discovers new modules
 * - Clean git history
 */

import { moduleRegistry } from "./moduleRegistry";

/**
 * Eagerly discover and register all modules in src/pages.
 *
 * Excludes test files using negative glob patterns at build time
 */
export function registerHostModulesEager(): void {
  // Eager loading - all modules loaded at build time
  // Use negative patterns to exclude test files at glob level
  const modules = import.meta.glob<Record<string, unknown>>(
    [
      "../pages/**/*.ts",
      "../pages/**/*.tsx",
      "!../pages/**/*.test.ts",
      "!../pages/**/*.test.tsx",
      "!../pages/**/*.spec.ts",
      "!../pages/**/*.spec.tsx",
      "!../pages/**/*.d.ts",
      "!../pages/**/__tests__/**",
      "!../pages/AigcStudio/components/DirectorStageNode/DirectorStageEditor.tsx",
    ],
    {
      eager: true,
      import: "*",
    },
  );

  let registeredCount = 0;
  for (const [path, module] of Object.entries(modules)) {
    try {
      const moduleKey = path
        .replace(/^\.\.\/pages\//, "")
        .replace(/\.(ts|tsx)$/, "");

      if (module && Object.keys(module).length > 0) {
        moduleRegistry.register(moduleKey, module);
        registeredCount++;
      }
    } catch (error) {
      console.warn(`[patchable] Failed to register module: ${path}`, error);
    }
  }

  console.log(`[patchable] Registered ${registeredCount} module(s)`);
}
