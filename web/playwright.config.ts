import { defineConfig, devices } from "@playwright/test";

const BASE_URL =
  process.env.WEB_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE ||
  "http://localhost:3000";
const SERIAL_MODE = process.env.PW_SERIAL === "1";
const OUTPUT_DIR = process.env.PW_OUTPUT_DIR;
const HTML_REPORT_DIR = process.env.PW_HTML_REPORT_DIR;

export default defineConfig({
  testDir: "./tests",
  ...(OUTPUT_DIR ? { outputDir: OUTPUT_DIR } : {}),
  fullyParallel: !SERIAL_MODE,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: SERIAL_MODE ? 1 : undefined,
  reporter: [
    [
      "html",
      {
        open: "never",
        ...(HTML_REPORT_DIR ? { outputFolder: HTML_REPORT_DIR } : {}),
      },
    ],
    ["list"],
  ],
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "ui-audit",
      testMatch: "**/*.audit.ts",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "phase4-authenticated",
      testMatch: [
        "**/phase4-authenticated.spec.ts",
        "**/phase5-flashcards-ux.spec.ts",
        "**/blueway-launch-b2.spec.ts",
        "**/course-chat-c1.spec.ts",
        "**/content-quality-c3-h2.spec.ts",
      ],
      use: { ...devices["Desktop Chrome"], channel: "chrome" },
    },
    {
      // This authenticated proof generates temporary credentials. Keep every
      // browser artifact off so no trace, video, screenshot, or HAR can retain
      // a session cookie or typed password in the evidence directory.
      name: "day2-learner-admin",
      testMatch: "**/day2-learner-admin.spec.ts",
      retries: 0,
      use: {
        ...devices["Desktop Chrome"],
        channel: "chrome",
        trace: "off",
        video: "off",
        screenshot: "off",
      },
    },
  ],
});
