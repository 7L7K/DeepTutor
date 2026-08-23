import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  canManageDeployment,
  projectAuthStatus,
} from "../lib/auth-status";

function source(relativePath: string): string {
  return readFileSync(path.join(process.cwd(), relativePath), "utf8");
}

test("auth status keeps unavailable distinct from confirmed auth-disabled", () => {
  const unavailable = projectAuthStatus(null);
  assert.deepEqual(unavailable, {
    known: false,
    enabled: false,
    authenticated: false,
    isAdmin: false,
    loading: false,
  });
  assert.equal(canManageDeployment(unavailable), false);

  const localAdmin = projectAuthStatus({
    enabled: false,
    authenticated: false,
  });
  assert.equal(localAdmin.known, true);
  assert.equal(canManageDeployment(localAdmin), true);

  const learner = projectAuthStatus({
    enabled: true,
    authenticated: true,
    role: "user",
  });
  assert.equal(learner.known, true);
  assert.equal(learner.isAdmin, false);
  assert.equal(canManageDeployment(learner), false);

  const admin = projectAuthStatus({
    enabled: true,
    authenticated: true,
    role: "admin",
  });
  assert.equal(canManageDeployment(admin), true);

  const inconsistentAdmin = projectAuthStatus({
    enabled: true,
    authenticated: false,
    role: "admin",
  });
  assert.equal(canManageDeployment(inconsistentAdmin), false);
});

test("required administrator gates fail closed when auth status is unknown", () => {
  const gate = source("components/access/AdminGate.tsx");

  assert.match(gate, /\(!enabled \|\| \(authenticated && isAdmin\)\)/);
  assert.match(gate, /if \(!known\)/);
  assert.match(gate, /Administrator access could not be verified/);
  assert.match(
    gate,
    /enabled &&\s+\(!authenticated \|\| !isAdmin\)/,
  );
});

test("unknown auth never reveals deployment-owned navigation or settings", () => {
  for (const file of [
    "components/sidebar/SidebarShell.tsx",
    "components/settings/SettingsHub.tsx",
    "components/settings/SettingsSectionGrid.tsx",
    "components/space/SpaceDashboard.tsx",
  ]) {
    assert.match(source(file), /canManageDeployment\(authStatus\)/, file);
  }

  assert.match(
    source("components/cli-apps/CliAppsSection.tsx"),
    /adminKnown=\{authKnown && !authLoading\}/,
  );
  assert.match(
    source("components/space/McpStoreSection.tsx"),
    /authLoading \|\| !authKnown \? null/,
  );
});

test("failed learner Partner connection stays on the learner-safe surface", () => {
  const partners = source("app/(workspace)/partners/page.tsx");

  assert.doesNotMatch(partners, /router\.push\("\/agents"\)/);
  assert.match(partners, /role="alert"/);
  assert.match(partners, /We couldn't open this Partner/);
  assert.match(partners, /setOpenError/);
});

test("learners retain ordinary KB creation without host connector controls", () => {
  const page = source("components/knowledge/KnowledgePage.tsx");
  const home = source("components/knowledge/KnowledgeHome.tsx");
  const modal = source("components/knowledge/CreateKbModal.tsx");

  assert.match(page, /allowExternalConnectors=\{canManageKnowledgeInfrastructure\}/);
  assert.match(page, /onCreate=\{handleCreate\}/);
  assert.match(home, /\{canManageInfrastructure \? \(/);
  assert.match(home, /onClick=\{onCreate\}/);
  assert.match(modal, /allowLink=\{allowExternalConnectors\}/);
  assert.match(modal, /!allowExternalConnectors \|\|/);
  assert.match(modal, /item\.id !== LIGHTRAG_SERVER_PROVIDER/);
  assert.match(modal, /item\.id !== IMA_PROVIDER/);
  assert.match(modal, /provider: effectiveProvider/);
});
