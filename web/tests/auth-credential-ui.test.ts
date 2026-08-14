import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import path from "node:path";

function source(relativePath: string): string {
  return readFileSync(path.join(process.cwd(), relativePath), "utf8");
}

test("login form keeps mobile username entry safe and supports password visibility", () => {
  const login = source("app/(auth)/login/page.tsx");

  assert.match(login, /autoCapitalize="none"/);
  assert.match(login, /autoCorrect="off"/);
  assert.match(login, /spellCheck=\{false\}/);
  assert.match(login, /inputMode="email"/);
  assert.match(login, /type=\{showPassword \? "text" : "password"\}/);
  assert.match(login, /autoComplete="current-password"/);
  assert.match(login, /Show password/);
  assert.match(login, /Hide password/);
  assert.match(login, /type="button"/);
  assert.match(login, /EyeOff/);
  assert.match(login, /Eye/);
});

test("registration password fields have independent hidden-by-default toggles", () => {
  const register = source("app/(auth)/register/page.tsx");

  assert.match(register, /showPassword/);
  assert.match(register, /showConfirmPassword/);
  assert.match(register, /type=\{showPassword \? "text" : "password"\}/);
  assert.match(register, /type=\{showConfirmPassword \? "text" : "password"\}/);
  assert.equal((register.match(/autoComplete="new-password"/g) ?? []).length, 2);
  assert.equal((register.match(/Show password/g) ?? []).length, 2);
  assert.equal((register.match(/Hide password/g) ?? []).length, 2);
});

test("visibility controls do not add credential fields to auth request bodies", () => {
  const auth = source("lib/auth.ts");

  assert.match(auth, /JSON\.stringify\(\{ username, password \}\)/);
  assert.doesNotMatch(auth, /showPassword|confirmPassword|visibility/);
});
