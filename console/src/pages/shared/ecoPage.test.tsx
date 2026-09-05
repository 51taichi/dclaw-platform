import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import styles from "./ecoPage.module.less";

describe("eco page card layout", () => {
  it("keeps every card footer pinned to the card bottom", () => {
    const { container } = render(
      <article className={styles.card}>
        <div>Variable card content</div>
        <footer className={styles.cardFooter}>Card actions</footer>
      </article>,
    );

    const footer = container.querySelector(`.${styles.cardFooter}`);
    expect(footer).not.toBeNull();
    expect(window.getComputedStyle(footer!).marginTop).toBe("auto");
  });
});
