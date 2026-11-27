#!/usr/bin/env node
// Production uses Vite. The dependency-free OS Babel fallback permits offline
// local development on this workstation without downloading npm packages.
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const root = path.resolve(__dirname, '..');
const frontend = path.join(root, 'frontend');
if (fs.existsSync(path.join(frontend, 'node_modules/vite/bin/vite.js'))) {
  cp.execFileSync(process.execPath, [path.join(frontend, 'node_modules/vite/bin/vite.js'), 'build'], {cwd: frontend, stdio: 'inherit'});
} else {
  let babel, plugin;
  try {
    babel = require('@babel/core');
    plugin = require('@babel/plugin-transform-typescript');
  } catch {
    process.stderr.write('Install frontend build dependencies: npm --prefix frontend install\n');
    process.exit(1);
  }
  const output = path.join(frontend, 'dist');
  fs.mkdirSync(output, {recursive: true});
  fs.cpSync(path.join(frontend, 'public'), output, {recursive: true});
  const code = babel.transformFileSync(path.join(frontend, 'src/app.ts'), {
    configFile: false, babelrc: false, plugins: [plugin], sourceMaps: true,
  });
  fs.writeFileSync(path.join(output, 'app.js'), code.code);
  fs.writeFileSync(path.join(output, 'app.js.map'), JSON.stringify(code.map));
  fs.copyFileSync(path.join(frontend, 'src/style.css'), path.join(output, 'style.css'));
  const html = fs.readFileSync(path.join(frontend, 'index.html'), 'utf8')
    .replace('/src/app.ts', '/app.js').replace('/src/style.css', '/style.css');
  fs.writeFileSync(path.join(output, 'index.html'), html);
  process.stdout.write('Frontend built with local Babel (offline).\n');
}
