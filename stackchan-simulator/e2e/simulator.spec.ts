import { expect, test } from "@playwright/test";

test("renders a nonblank device and records API traffic", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const canvas = page.getByLabel("StackChan simulated display");
  await expect(canvas).toBeVisible();
  const colors = await canvas.evaluate((element: HTMLCanvasElement) => {
    const pixels = element.getContext("2d")!.getImageData(0, 0, element.width, element.height).data;
    const unique = new Set<string>();
    for (let offset = 0; offset < pixels.length; offset += 4000) unique.add(`${pixels[offset]}:${pixels[offset + 1]}:${pixels[offset + 2]}`);
    return unique.size;
  });
  expect(colors).toBeGreaterThan(3);

  await page.getByRole("button", { name: /APIs/ }).click();
  await page.getByRole("button", { name: /GET \/health Mock liveness/ }).first().click();
  await page.getByRole("button", { name: "Execute" }).click();
  await expect(page.locator(".response-meta")).toContainText("200");
  await page.getByRole("button", { name: /Logs/ }).click();
  await expect(page.locator(".log-row")).toHaveCount(2);
});

test("mobile device view has no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByLabel("StackChan simulated display")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  const subtitle = await page.locator(".subtitle").boundingBox();
  const controls = await page.locator(".control-rail").boundingBox();
  expect(subtitle && controls && subtitle.y + subtitle.height <= controls.y).toBeTruthy();
  const samples = page.getByLabel("Sample");
  await expect(samples).toHaveValue("en-greeting");
  await samples.selectOption("zh-greeting");
  await expect(page.getByText("ASR mismatch: server language is en")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send voice" })).toBeDisabled();
});

test("replaces the waiting notice when STT and TTS arrive", async ({ page }) => {
  let uiSocket: Parameters<Parameters<typeof page.routeWebSocket>[1]>[0] | undefined;
  await page.routeWebSocket(/\/ws\/ui$/, (socket) => {
    uiSocket = socket;
    socket.send(JSON.stringify({
      type: "snapshot",
      state: {
        connected: true, deviceId: "stackchan-sim-001", sessionId: "test-session", status: "idle",
        emotion: "neutral", subtitle: "", mouth: 0, yaw: 0, pitch: 45, speed: 250,
        volume: 65, mode: "idle", kidMode: true, smartMode: false, leds: Array(12).fill("#20252a"),
      },
      logs: [],
    }));
  });
  await page.route(/\/api\/device\/state$/, (route) => route.fulfill({
    json: {
      state: {
        connected: true, deviceId: "stackchan-sim-001", sessionId: "test-session", status: "idle",
        emotion: "neutral", subtitle: "", mouth: 0, yaw: 0, pitch: 45, speed: 250,
        volume: 65, mode: "idle", kidMode: true, smartMode: false, leds: Array(12).fill("#20252a"),
      },
      samples: ["en-greeting", "zh-question"], asrLanguage: "auto",
    },
  }));
  await page.route(/\/api\/device\/audio\/send$/, (route) => route.fulfill({ json: { ok: true } }));

  await page.goto("/");
  await expect.poll(() => Boolean(uiSocket)).toBe(true);
  await page.getByRole("button", { name: "Send voice" }).click();
  await expect(page.getByText("Voice uploaded; waiting for STT/TTS")).toBeVisible();

  uiSocket!.send(JSON.stringify({ type: "transcript", role: "user", text: "今天天气怎么样？", reset: true }));
  await expect(page.getByText("STT received; waiting for reply")).toBeVisible();
  await expect(page.locator("dt", { hasText: "Heard" }).locator("xpath=following-sibling::dd")).toHaveText("今天天气怎么样？");

  uiSocket!.send(JSON.stringify({ type: "transcript", role: "assistant", text: "Which city?", append: true }));
  await expect(page.getByText("Response received")).toBeVisible();
  await expect(page.locator("dt", { hasText: "Reply" }).locator("xpath=following-sibling::dd")).toHaveText("Which city?");
});
