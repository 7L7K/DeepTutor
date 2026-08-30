import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

function source(relativePath: string): string {
  return readFileSync(path.join(process.cwd(), relativePath), "utf8");
}

test("logout stays on the current page until the server confirms it", () => {
  const auth = source("lib/auth.ts");
  const button = source("components/auth/LogoutButton.tsx");
  const profile = source("app/(utility)/profile/page.tsx");

  assert.match(auth, /skipAuthRedirect:\s*true/);
  assert.match(auth, /if \(!res\.ok\) return \{ ok: false \}/);
  assert.match(auth, /return \{ ok: true \}/);
  assert.match(button, /const result = await logout\(\);[\s\S]*if \(result\.ok\)[\s\S]*router\.replace\("\/login"\)/);
  assert.match(profile, /const result = await logout\(\);[\s\S]*if \(result\.ok\)[\s\S]*router\.replace\("\/login"\)/);
  assert.match(button, /Unable to sign out\. Please try again\./);
  assert.match(profile, /Unable to sign out\. Please try again\./);
});

test("account creation UI is available only during first-user bootstrap", () => {
  const login = source("app/(auth)/login/page.tsx");
  const register = source("app/(auth)/register/page.tsx");

  assert.match(login, /const \[isFirstUser, setIsFirstUser\] = useState\(false\)/);
  assert.match(login, /checkIsFirstUser\(\)\.then\(\(first\) => \{[\s\S]*setIsFirstUser\(first\)/);
  assert.match(login, /\{isFirstUser && \(/);
  assert.match(register, /if \(!isFirst\) \{[\s\S]*Account creation is by invitation only\./);
  assert.match(register, /checkingFirst \? \([\s\S]*\) : isFirst \? \([\s\S]*\) : \(/);
});

test("model HTML is non-executing and SVG references stay local", () => {
  const viewer = source("components/visualize/VisualizationViewer.tsx");

  assert.match(viewer, /function HtmlVisualizationUnavailable\(\)/);
  assert.match(viewer, /return <HtmlVisualizationUnavailable \/>/);
  assert.doesNotMatch(viewer, /prepareIframeHtml|iframe\.srcdoc|allow-scripts/);
  assert.match(viewer, /function isLocalSvgFragment/);
  assert.match(viewer, /!isLocalSvgFragment\(attr\.value\)/);
  assert.match(viewer, /function hasOnlyLocalSvgUrlReferences/);
  assert.match(viewer, /value\.includes\("\\\\"\)/);
  assert.match(viewer, /root\.querySelectorAll\("style"\)\.forEach\(\(style\) => style\.remove\(\)\)/);
  assert.match(viewer, /animatedAttribute === "href"/);
});

test("Markdown renderers block remote images and own link safety attributes", () => {
  for (const relativePath of [
    "components/common/RichMarkdownRenderer.tsx",
    "components/common/SimpleMarkdownRenderer.tsx",
  ]) {
    const renderer = source(relativePath);
    assert.match(renderer, /isRemoteMarkdownImageSource/);
    assert.match(renderer, /isRemoteMarkdownImageSource\(src\)/);
    assert.match(renderer, /isRemoteMarkdownImageSource\(srcSet\)/);
    assert.match(renderer, /video: \(\) => null/);
    assert.match(renderer, /audio: \(\) => null/);
    assert.match(renderer, /track: \(\) => null/);
    assert.match(
      renderer,
      /\{\.\.\.props\}\s*target=\{external \? "_blank" : undefined\}\s*rel=\{external \? "noopener noreferrer" : undefined\}/,
    );
  }
});
