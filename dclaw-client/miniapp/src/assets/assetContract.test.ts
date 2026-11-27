import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { inflateSync } from "node:zlib";
import { describe, expect, it } from "vitest";

function readVisiblePixels(relativePath: string) {
  const filePath = fileURLToPath(new URL(relativePath, import.meta.url));
  const png = readFileSync(filePath);
  const signature = png.subarray(0, 8).toString("hex");
  expect(signature).toBe("89504e470d0a1a0a");

  let width = 0;
  let height = 0;
  let bitDepth = 0;
  let colorType = 0;
  const idatChunks: Buffer[] = [];
  let offset = 8;

  while (offset < png.length) {
    const length = png.readUInt32BE(offset);
    const type = png.toString("ascii", offset + 4, offset + 8);
    const start = offset + 8;
    const end = start + length;

    if (type === "IHDR") {
      width = png.readUInt32BE(start);
      height = png.readUInt32BE(start + 4);
      bitDepth = png[start + 8];
      colorType = png[start + 9];
    }
    if (type === "IDAT") {
      idatChunks.push(png.subarray(start, end));
    }
    if (type === "IEND") {
      break;
    }
    offset = end + 4;
  }

  expect(bitDepth).toBe(8);
  expect([2, 6]).toContain(colorType);

  const raw = inflateSync(Buffer.concat(idatChunks));
  const bytesPerPixel = colorType === 6 ? 4 : 3;
  const rowLength = width * bytesPerPixel;
  let rawOffset = 0;
  let previous = new Uint8Array(rowLength);
  const cornerAlphas = new Map<string, number>();
  let maxVisibleX = -1;
  let maxVisibleY = -1;
  let minVisibleX = width;
  let minVisibleY = height;
  let visiblePixels = 0;

  for (let y = 0; y < height; y += 1) {
    const filter = raw[rawOffset];
    rawOffset += 1;
    const row = new Uint8Array(rowLength);

    for (let i = 0; i < rowLength; i += 1) {
      const value = raw[rawOffset];
      rawOffset += 1;
      const left = i >= bytesPerPixel ? row[i - bytesPerPixel] : 0;
      const up = previous[i] || 0;
      const upLeft = i >= bytesPerPixel ? previous[i - bytesPerPixel] : 0;
      const pa = Math.abs(up - upLeft);
      const pb = Math.abs(left - upLeft);
      const pc = Math.abs(left + up - 2 * upLeft);
      const predictor = pa <= pb && pa <= pc ? left : pb <= pc ? up : upLeft;

      if (filter === 0) row[i] = value;
      if (filter === 1) row[i] = (value + left) & 255;
      if (filter === 2) row[i] = (value + up) & 255;
      if (filter === 3) row[i] = (value + Math.floor((left + up) / 2)) & 255;
      if (filter === 4) row[i] = (value + predictor) & 255;
    }

    for (let x = 0; x < width; x += 1) {
      const pixelOffset = x * bytesPerPixel;
      const red = row[pixelOffset];
      const green = row[pixelOffset + 1];
      const blue = row[pixelOffset + 2];
      const alpha = colorType === 6 ? row[pixelOffset + 3] : 255;
      const isWhite = red > 246 && green > 246 && blue > 246;
      const isCorner =
        (x === 0 || x === width - 1) && (y === 0 || y === height - 1);

      if (isCorner) {
        cornerAlphas.set(`${x},${y}`, alpha);
      }
      if (alpha > 0 && !isWhite) {
        visiblePixels += 1;
        minVisibleX = Math.min(minVisibleX, x);
        maxVisibleX = Math.max(maxVisibleX, x);
        minVisibleY = Math.min(minVisibleY, y);
        maxVisibleY = Math.max(maxVisibleY, y);
      }
    }
    previous = row;
  }

  return {
    byteLength: png.length,
    colorType,
    cornerAlphas,
    height,
    maxVisibleX,
    maxVisibleY,
    minVisibleX,
    minVisibleY,
    visiblePixels,
    width,
  };
}

function countOrangeAccentPixels(relativePath: string) {
  const filePath = fileURLToPath(new URL(relativePath, import.meta.url));
  const png = readFileSync(filePath);
  const idatChunks: Buffer[] = [];
  let width = 0;
  let bitDepth = 0;
  let colorType = 0;
  let offset = 8;

  while (offset < png.length) {
    const length = png.readUInt32BE(offset);
    const type = png.toString("ascii", offset + 4, offset + 8);
    const start = offset + 8;
    const end = start + length;

    if (type === "IHDR") {
      width = png.readUInt32BE(start);
      bitDepth = png[start + 8];
      colorType = png[start + 9];
    }
    if (type === "IDAT") {
      idatChunks.push(png.subarray(start, end));
    }
    if (type === "IEND") {
      break;
    }
    offset = end + 4;
  }

  expect(bitDepth).toBe(8);
  expect(colorType).toBe(6);

  const raw = inflateSync(Buffer.concat(idatChunks));
  const bytesPerPixel = 4;
  const rowLength = width * bytesPerPixel;
  let rawOffset = 0;
  let previous = new Uint8Array(rowLength);
  let orangePixels = 0;

  for (let y = 0; rawOffset < raw.length; y += 1) {
    const filter = raw[rawOffset];
    rawOffset += 1;
    const row = new Uint8Array(rowLength);

    for (let i = 0; i < rowLength; i += 1) {
      const value = raw[rawOffset];
      rawOffset += 1;
      const left = i >= bytesPerPixel ? row[i - bytesPerPixel] : 0;
      const up = previous[i] || 0;
      const upLeft = i >= bytesPerPixel ? previous[i - bytesPerPixel] : 0;
      const pa = Math.abs(up - upLeft);
      const pb = Math.abs(left - upLeft);
      const pc = Math.abs(left + up - 2 * upLeft);
      const predictor = pa <= pb && pa <= pc ? left : pb <= pc ? up : upLeft;

      if (filter === 0) row[i] = value;
      if (filter === 1) row[i] = (value + left) & 255;
      if (filter === 2) row[i] = (value + up) & 255;
      if (filter === 3) row[i] = (value + Math.floor((left + up) / 2)) & 255;
      if (filter === 4) row[i] = (value + predictor) & 255;
    }

    for (let x = 0; x < width; x += 1) {
      const pixelOffset = x * bytesPerPixel;
      const red = row[pixelOffset];
      const green = row[pixelOffset + 1];
      const blue = row[pixelOffset + 2];
      const alpha = row[pixelOffset + 3];
      const isDclawOrange =
        alpha > 80 && red > 220 && green >= 55 && green < 165 && blue < 95;

      if (isDclawOrange) {
        orangePixels += 1;
      }
    }
    previous = row;
  }

  return orangePixels;
}

describe("mini-program visual assets", () => {
  it("ships a visible horizontal DClaw logo", () => {
    const logo = readVisiblePixels("./dclaw-logo.png");

    expect(logo.width / logo.height).toBeGreaterThan(3);
    expect(logo.visiblePixels).toBeGreaterThan(100);
  });

  it("ships the login mascot as a transparent cutout", () => {
    const mascot = readVisiblePixels("./mascot-login.png");

    expect(mascot.colorType).toBe(6);
    expect([...mascot.cornerAlphas.values()]).toEqual([0, 0, 0, 0]);
    expect(mascot.maxVisibleX).toBeGreaterThan(450);
    expect(mascot.visiblePixels).toBeGreaterThan(100);
  });

  it("ships the task queue mascot at a crisp source resolution", () => {
    const mascot = readVisiblePixels("./mascot-task.png");

    expect(mascot.width).toBeGreaterThanOrEqual(512);
    expect(mascot.height).toBeGreaterThanOrEqual(512);
    expect(mascot.byteLength).toBeGreaterThan(120_000);
    expect(mascot.visiblePixels).toBeGreaterThan(100);
  });

  it("ships image-generated UI icons for the employee mini-program", () => {
    const imageGeneratedIconFiles = [
      "./icon-shortcut-tasks.png",
      "./icon-shortcut-knowledge.png",
      "./icon-shortcut-ai.png",
      "./icon-shortcut-confirm.png",
      "./icon-task-file.png",
      "./icon-tab-workbench.png",
      "./icon-tab-tasks.png",
      "./icon-tab-confirm.png",
      "./icon-tab-me.png",
      "./icon-tab-workbench-active.png",
      "./icon-tab-workbench-inactive.png",
      "./icon-tab-tasks-active.png",
      "./icon-tab-tasks-inactive.png",
      "./icon-tab-confirm-active.png",
      "./icon-tab-confirm-inactive.png",
      "./icon-tab-me-active.png",
      "./icon-tab-me-inactive.png",
    ];

    for (const file of imageGeneratedIconFiles) {
      const icon = readVisiblePixels(file);

      expect(icon.width).toBeGreaterThanOrEqual(96);
      expect(icon.height).toBeGreaterThanOrEqual(96);
      expect(icon.visiblePixels).toBeGreaterThan(100);
    }
  });

  it("keeps tab state icon artwork centered inside its png canvas", () => {
    const tabStateIconFiles = [
      "./icon-tab-workbench-active.png",
      "./icon-tab-workbench-inactive.png",
      "./icon-tab-tasks-active.png",
      "./icon-tab-tasks-inactive.png",
      "./icon-tab-confirm-active.png",
      "./icon-tab-confirm-inactive.png",
      "./icon-tab-me-active.png",
      "./icon-tab-me-inactive.png",
    ];

    for (const file of tabStateIconFiles) {
      const icon = readVisiblePixels(file);
      const visibleCenterX = (icon.minVisibleX + icon.maxVisibleX) / 2;
      const visibleCenterY = (icon.minVisibleY + icon.maxVisibleY) / 2;

      expect(Math.abs(visibleCenterX - icon.width / 2)).toBeLessThanOrEqual(8);
      expect(Math.abs(visibleCenterY - icon.height / 2)).toBeLessThanOrEqual(8);
    }
  });

  it("uses shortcut icons with DClaw orange accents", () => {
    expect(countOrangeAccentPixels("./icon-shortcut-tasks.png")).toBeGreaterThan(
      500,
    );
    expect(
      countOrangeAccentPixels("./icon-shortcut-knowledge.png"),
    ).toBeGreaterThan(500);
    expect(countOrangeAccentPixels("./icon-shortcut-ai.png")).toBeGreaterThan(
      500,
    );
    expect(
      countOrangeAccentPixels("./icon-shortcut-confirm.png"),
    ).toBeGreaterThan(500);
  });
});
