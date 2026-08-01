const [major = 0] = process.versions.node.split(".").map(Number);

if (![22, 24].includes(major)) {
  console.error(
    `Unsupported Node.js ${process.versions.node}. ` +
      "Use Node.js 22 LTS (see web/.nvmrc); supported majors are 22 and 24.",
  );
  process.exit(1);
}
