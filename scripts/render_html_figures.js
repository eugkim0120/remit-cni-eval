// Renders every docs/figures/src/<name>.html to docs/figures/<name>.png at 2x, cropped to its .page element.
// Needs playwright-core and a Chromium headless shell; both paths come from the environment so nothing
// machine-specific is committed: PLAYWRIGHT_CORE (module dir) and CHROMIUM (executable).
const fs = require("fs");
const path = require("path");
const { chromium } = require(process.env.PLAYWRIGHT_CORE);

const SRC = path.resolve(__dirname, "../docs/figures/src");
const OUT = path.resolve(__dirname, "../docs/figures");

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 2 });
  for (const file of fs.readdirSync(SRC).filter((f) => f.endsWith(".html"))) {
    await page.goto("file://" + path.join(SRC, file));
    // Every figure is 2400x3000 px (1200x1500 CSS px at 2x), the same as the matplotlib charts. Content that
    // overflows the fixed page would be cut off, so fail instead of rendering a clipped image.
    const size = await page.locator(".page").evaluate((el) => [el.offsetWidth, el.offsetHeight, el.scrollHeight]);
    if (size[0] !== 1200 || size[1] !== 1500 || size[2] > 1500) {
      throw new Error(`${file}: .page is ${size[0]}x${size[1]} (content ${size[2]} tall), expected 1200x1500`);
    }
    await page.locator(".page").screenshot({ path: path.join(OUT, file.replace(/\.html$/, ".png")) });
    console.log("rendered", file);
  }
  await browser.close();
})();
