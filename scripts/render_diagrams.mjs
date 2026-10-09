// Run from frontend: node ../scripts/render_diagrams.mjs
import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
import path from 'node:path';
const require = createRequire(path.resolve('package.json'));
const {chromium} = require('@playwright/test');
const browser = await chromium.launch({headless: true});
try {
  const page = await browser.newPage({viewport: {width: 1600, height: 1200}, deviceScaleFactor: 1});
  await page.setContent('<html><body style="margin:24px;background:#fff"><div id="diagram"></div></body></html>');
  await page.addScriptTag({path: path.resolve('node_modules/mermaid/dist/mermaid.min.js')});
  await page.evaluate(() => window.mermaid.initialize({startOnLoad: false, theme: 'base', securityLevel: 'strict',
    themeVariables: {fontFamily: 'Arial, Microsoft YaHei, sans-serif', primaryColor: '#fff1e7', primaryTextColor: '#343b45', primaryBorderColor: '#d6ae95', lineColor: '#9ba9b6', secondaryColor: '#eef4f7', tertiaryColor: '#f5f6f8'},
    flowchart: {htmlLabels: false, curve: 'basis', padding: 18, rankSpacing: 55, nodeSpacing: 32}}));
  for (const name of ['architecture', 'workflow']) {
    const markdown = await fs.readFile(path.resolve(`../docs/${name}.md`), 'utf8');
    const source = markdown.match(/```mermaid\n([\s\S]*?)```/)[1];
    const svg = await page.evaluate(async ({source, name}) => {
      const result = await window.mermaid.render(`graph_${name}`, source);
      document.getElementById('diagram').innerHTML = result.svg;
      return result.svg;
    }, {source, name});
    await fs.writeFile(path.resolve(`../docs/${name}.svg`), svg);
    await page.locator('#diagram').screenshot({path: path.resolve(`../docs/${name}.png`)});
    console.log(`Rendered ${name}.svg and .png`);
  }
} finally {await browser.close();}
