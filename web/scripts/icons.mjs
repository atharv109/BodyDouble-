// Renders public/favicon.svg into the PNG favicon set (run once after changing the emblem).
import { chromium } from 'playwright'
import { readFileSync, writeFileSync } from 'node:fs'
const svg = readFileSync(new URL('../public/favicon.svg', import.meta.url), 'utf8')
const b = await chromium.launch()
const p = await b.newPage()
for (const [name, size] of [['apple-touch-icon.png', 180], ['icon-192.png', 192], ['icon-512.png', 512], ['favicon-32.png', 32]]) {
  await p.setViewportSize({ width: size, height: size })
  // apple-touch-icon is masked by iOS: fill the square, no own rounded corners
  const bg = name.startsWith('apple') ? '#0b0d0f' : 'transparent'
  await p.setContent(`<style>html,body{margin:0;background:${bg}}svg{display:block;width:${size}px;height:${size}px}</style>${svg}`)
  writeFileSync(new URL(`../public/${name}`, import.meta.url), await p.screenshot({ omitBackground: bg === 'transparent' }))
}
await b.close()
