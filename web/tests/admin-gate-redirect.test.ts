import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

// Execute the actual component and then its queued effect. Checking only its
// rendered children misses redirects that happen after learner content renders.
function renderGate(
  auth: { enabled: boolean; isAdmin: boolean; loading: boolean },
  required?: boolean,
) {
  const redirects: string[] = [];
  const effects: Array<() => void> = [];
  const componentModule = { exports: {} as { default: (props: object) => unknown } };
  const jsx = (type: unknown, props: unknown) => ({ type, props });
  const dependencies: Record<string, unknown> = {
    react: { useEffect: (effect: () => void) => effects.push(effect) },
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
    "next/navigation": { useRouter: () => ({ replace: (url: string) => redirects.push(url) }) },
    "lucide-react": { ShieldCheck: "shield" },
    "@/hooks/useAuthStatus": { useAuthStatus: () => auth },
  };
  const source = readFileSync(
    path.join(process.cwd(), "components/access/AdminGate.tsx"), "utf8",
  );
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  vm.runInNewContext(compiled, {
    module: componentModule, exports: componentModule.exports,
    require: (name: string) => {
      assert.ok(name in dependencies, `Unexpected component dependency: ${name}`);
      return dependencies[name];
    },
  });
  const output = componentModule.exports.default({ children: "learner-content", required });
  effects.forEach((effect) => effect());
  return { redirects, output: JSON.stringify(output) };
}

for (const enabled of [false, true]) {
  for (const isAdmin of [false, true]) {
    for (const loading of [false, true]) {
      test(`optional gate keeps content without redirects: ${JSON.stringify({ enabled, isAdmin, loading })}`, () => {
        const result = renderGate({ enabled, isAdmin, loading }, false);
        assert.deepEqual(result.redirects, []);
        assert.match(result.output, /learner-content/);
      });
    }
  }
}

for (const required of [true, undefined]) {
  test(`admin gate denies a learner after auth settles (required=${required})`, () => {
    const result = renderGate({ enabled: true, isAdmin: false, loading: false }, required);
    assert.deepEqual(result.redirects, ["/home"]);
    assert.doesNotMatch(result.output, /learner-content/);
  });
}

test("admin gate waits for authentication without redirecting", () => {
  const result = renderGate({ enabled: true, isAdmin: false, loading: true }, true);
  assert.deepEqual(result.redirects, []);
  assert.doesNotMatch(result.output, /learner-content/);
});

test("admin gate allows administrators", () => {
  const result = renderGate({ enabled: true, isAdmin: true, loading: false }, true);
  assert.deepEqual(result.redirects, []);
  assert.match(result.output, /learner-content/);
});

test("auth-disabled local behavior is preserved", () => {
  const result = renderGate({ enabled: false, isAdmin: false, loading: false }, true);
  assert.deepEqual(result.redirects, []);
  assert.match(result.output, /learner-content/);
});
