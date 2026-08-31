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
    canUploadCourseSources: false,
    loading: false,
  });
  assert.equal(canManageDeployment(unavailable), false);

  const localAdmin = projectAuthStatus({
    enabled: false,
    authenticated: false,
  });
  assert.equal(localAdmin.known, true);
  assert.equal(localAdmin.canUploadCourseSources, true);
  assert.equal(canManageDeployment(localAdmin), true);

  const learner = projectAuthStatus({
    enabled: true,
    authenticated: true,
    role: "user",
  });
  assert.equal(learner.known, true);
  assert.equal(learner.isAdmin, false);
  assert.equal(learner.canUploadCourseSources, false);
  assert.equal(canManageDeployment(learner), false);

  const admittedLearner = projectAuthStatus({
    enabled: true,
    authenticated: true,
    role: "user",
    course_source_uploads: true,
  });
  assert.equal(admittedLearner.canUploadCourseSources, true);
  assert.equal(canManageDeployment(admittedLearner), false);

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
    course_source_uploads: true,
  });
  assert.equal(inconsistentAdmin.canUploadCourseSources, false);
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

test("controlled-beta learners can read assigned KBs but cannot start indexing work", () => {
  const page = source("components/knowledge/KnowledgePage.tsx");
  const home = source("components/knowledge/KnowledgeHome.tsx");
  const modal = source("components/knowledge/CreateKbModal.tsx");

  assert.match(page, /allowExternalConnectors=\{canManageKnowledgeInfrastructure\}/);
  assert.match(page, /onCreate=\{handleCreate\}/);
  assert.match(page, /isOpen=\{createOpen && canManageKnowledgeInfrastructure\}/);
  assert.match(home, /\{canManageInfrastructure \? \(/);
  assert.match(home, /\{canCreate && \(/);
  assert.match(home, /Knowledge bases assigned for your courses will appear here/);
  assert.match(modal, /allowLink=\{allowExternalConnectors\}/);
  assert.match(modal, /!allowExternalConnectors \|\|/);
  assert.match(modal, /item\.id !== LIGHTRAG_SERVER_PROVIDER/);
  assert.match(modal, /item\.id !== IMA_PROVIDER/);
  assert.match(modal, /provider: effectiveProvider/);
});

test("administrators can explicitly admit one learner to bounded Course uploads", () => {
  const editor = source("features/multi-user/components/GrantEditor.tsx");
  const courseMaterials = source("components/courses/CourseMaterials.tsx");

  assert.match(editor, /label="Allow Course material uploads"/);
  assert.match(editor, /checked=\{grant\.course_source_uploads\}/);
  assert.match(editor, /course_source_uploads: !current\.course_source_uploads/);
  assert.match(courseMaterials, /useAuthStatus\(\)\.canUploadCourseSources/);
  assert.doesNotMatch(courseMaterials, /canManageDeployment/);
});

test("administrators explicitly allow built-in tools and new grants deny them by default", () => {
  const editor = source("features/multi-user/components/GrantEditor.tsx");
  const types = source("features/multi-user/types.ts");

  assert.match(editor, /builtin_tools: \[\]/);
  assert.match(editor, /SectionTitle>Built-in tools/);
  assert.match(editor, /checked=\{grant\.builtin_tools\.includes\(tool\.name\)\}/);
  assert.match(editor, /toggleGrantTool\("builtin_tools", tool\.name\)/);
  assert.match(editor, /Built-in tools are denied by default/);
  assert.match(types, /builtin_tools: string\[\];/);
  assert.match(types, /builtin_tools: ToolOption\[\];/);
});
