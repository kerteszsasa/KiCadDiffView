#!/usr/bin/env node
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
let compiler;
try {
  compiler = require.resolve('typescript', {paths: [path.join(root, 'frontend')]});
} catch {
  const editorCompiler = '/usr/share/code/resources/app/extensions/node_modules/typescript/lib/typescript.js';
  if (fs.existsSync(editorCompiler)) compiler = editorCompiler;
}
if (!compiler) {
  process.stderr.write('Install the compiler: npm --prefix frontend install\n');
  process.exit(1);
}
const ts = require(compiler);
const config = ts.readConfigFile(path.join(root, 'frontend/tsconfig.json'), ts.sys.readFile);
const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, path.join(root, 'frontend'));
const program = ts.createProgram(parsed.fileNames, parsed.options);
const diagnostics = [...parsed.errors, ...ts.getPreEmitDiagnostics(program)];
if (diagnostics.length) {
  process.stderr.write(ts.formatDiagnosticsWithColorAndContext(diagnostics, {
    getCanonicalFileName: value => value, getCurrentDirectory: () => root, getNewLine: () => '\n',
  }));
  process.exit(1);
}
process.stdout.write(`Strict TypeScript ${ts.version}: PASS\n`);
