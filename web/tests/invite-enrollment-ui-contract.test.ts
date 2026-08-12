import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = process.cwd();

function source(relativePath: string): string {
  return readFileSync(path.join(root, relativePath), "utf8");
}

test("registration renders bootstrap, invite, and closed modes with direct Classes entry", () => {
  const registerPage = source("app/(auth)/register/page.tsx");
  assert.match(registerPage, /registrationMode === "bootstrap"/);
  assert.match(registerPage, /registrationMode === "invite"/);
  assert.match(registerPage, /registrationMode === "closed"/);
  assert.match(registerPage, /router\.replace\("\/classes"\)/);
  assert.doesNotMatch(registerPage, /checkIsFirstUser/);

  const loginPage = source("app/(auth)/login/page.tsx");
  assert.match(loginPage, /registrationMode !== "closed"/);
});

test("one-time invite plaintext is removed from state and has no persistence sink", () => {
  const panel = source("components/auth/EnrollmentPanel.tsx");
  assert.match(panel, /setOneTimeCode\(null\)/);
  assert.match(panel, /oneTimeCode !== null/);
  for (const forbidden of [
    "localStorage",
    "sessionStorage",
    "history.pushState",
    "history.replaceState",
    "URLSearchParams",
    "console.log",
  ]) {
    assert.equal(panel.includes(forbidden), false, forbidden);
  }
});
