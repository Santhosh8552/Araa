const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2
  });
  const page = await context.newPage();

  const consoleLogs = [];
  const errors = [];
  page.on('console', msg => {
    const text = msg.text();
    consoleLogs.push(`[${msg.type()}] ${text}`);
    if (msg.type() === 'error') {
      errors.push(text);
    }
  });
  page.on('pageerror', err => {
    errors.push(`PAGEERROR: ${err.message}\n${err.stack}`);
  });
  page.on('requestfailed', req => {
    errors.push(`REQ_FAILED: ${req.method()} ${req.url()} (${req.failure()?.errorText})`);
  });

  console.log('1. Navigating to http://127.0.0.1:5050/#terminal...');
  await page.goto('http://127.0.0.1:5050/#terminal', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);

  // Check if we are at landing or app
  const isLandingVisible = await page.evaluate(() => {
    const land = document.getElementById('landing_gate');
    return land ? window.getComputedStyle(land).display !== 'none' : false;
  });
  console.log('Landing gate visible:', isLandingVisible);

  // If landing or signin is active, let's auto-authenticate or enter terminal view
  console.log('2. Simulating authenticated terminal state...');
  await page.evaluate(async () => {
    localStorage.setItem('tp_token', 'test_token_123');
    if (window.S) {
      window.S.token = 'test_token_123';
      window.S.user = { email: 'santhosh@araabot.in', name: 'Santhosh' };
    }
    const land = document.getElementById('landing_gate');
    if (land) land.style.display = 'none';
    const auth = document.getElementById('auth');
    if (auth) auth.classList.add('hide');
    const app = document.getElementById('app');
    if (app) app.classList.remove('hide');
    document.documentElement.classList.add('in_app');

    // Trigger VT load and resize
    if (window.VT) {
      if (typeof window.VT.loadMarketData === 'function') {
        await window.VT.loadMarketData('BTCUSDT', '15m');
      }
      if (typeof window.VT.resizeCanvas === 'function') {
        window.VT.resizeCanvas();
      }
    }
  });

  await page.waitForTimeout(2000);

  // Check DOM state of #term, #chart, #smc_ov_canvas
  const domState = await page.evaluate(() => {
    const term = document.getElementById('term');
    const chart = document.getElementById('chart') || document.querySelector('#chartHost .smc-canvas:not(.smc-ov)');
    const ov = document.getElementById('smc_ov_canvas') || document.querySelector('#chartHost .smc-canvas.smc-ov');
    const chartHost = document.getElementById('chartHost');

    let chartPixelsNonZero = 0;
    if (chart) {
      try {
        const ctx = chart.getContext('2d');
        const img = ctx.getImageData(0, 0, Math.min(100, chart.width), Math.min(100, chart.height));
        for (let i = 0; i < img.data.length; i += 4) {
          if (img.data[i] !== 0 || img.data[i+1] !== 0 || img.data[i+2] !== 0) {
            chartPixelsNonZero++;
          }
        }
      } catch (e) {}
    }

    return {
      termFound: !!term,
      termDisplay: term ? window.getComputedStyle(term).display : null,
      termW: term ? term.offsetWidth : 0,
      termH: term ? term.offsetHeight : 0,
      chartHostW: chartHost ? chartHost.offsetWidth : 0,
      chartHostH: chartHost ? chartHost.offsetHeight : 0,
      chartFound: !!chart,
      chartW: chart ? chart.width : 0,
      chartH: chart ? chart.height : 0,
      chartStyleW: chart ? chart.style.width : null,
      chartStyleH: chart ? chart.style.height : null,
      chartCssDisplay: chart ? window.getComputedStyle(chart).display : null,
      chartCssBg: chart ? window.getComputedStyle(chart).backgroundColor : null,
      chartPixelsNonZero,
      ovFound: !!ov,
      ovW: ov ? ov.width : 0,
      ovH: ov ? ov.height : 0,
      ovCssBg: ov ? window.getComputedStyle(ov).backgroundColor : null,
      vtSymbol: window.VT?.symbol,
      vtTf: window.VT?.timeframe,
      vtCandlesLen: window.VT?.candles?.length || 0,
      vtIsLoading: window.VT?.isLoading,
      subSymbol: document.getElementById('t_symbol')?.textContent,
      subO: document.getElementById('t_sub_o')?.textContent,
      subC: document.getElementById('t_sub_c')?.textContent,
      buyStrength: document.getElementById('iva_buy_pct')?.textContent,
      sellStrength: document.getElementById('iva_sell_pct')?.textContent,
      marketBias: document.getElementById('iva_bias_badge')?.textContent,
      timelineRows: document.querySelectorAll('#iva_tl_tbody tr').length
    };
  });

  console.log('DOM & Canvas State:', JSON.stringify(domState, null, 2));

  // Take screenshot
  const screenshotPath = path.join(__dirname, '..', 'reports', 'playwright_terminal.png');
  await page.screenshot({ path: screenshotPath, fullPage: true });
  console.log(`Saved full screenshot to: ${screenshotPath}`);

  // Test timeframe switch to 5m
  console.log('3. Testing click on 5m timeframe button...');
  const tf5m = await page.$('.tfs button[data-tf="5M"], .tfs button[data-tf="5m"]');
  if (tf5m) {
    await tf5m.click();
    await page.waitForTimeout(1500);
  }

  // Test symbol switch to EURUSD
  console.log('4. Testing switch to EURUSD...');
  const eurusdRow = await page.$('.wl-row[data-sym="EURUSD"]');
  if (eurusdRow) {
    await eurusdRow.click();
    await page.waitForTimeout(1500);
  }

  const afterSwitchState = await page.evaluate(() => {
    return {
      vtSymbol: window.VT?.symbol,
      vtTf: window.VT?.timeframe,
      vtCandlesLen: window.VT?.candles?.length || 0,
      subSymbol: document.getElementById('t_symbol')?.textContent,
      subC: document.getElementById('t_sub_c')?.textContent
    };
  });
  console.log('After Symbol/TF switch:', JSON.stringify(afterSwitchState, null, 2));

  // Capture errors
  console.log('\n--- Console Errors Encountered (Total: ' + errors.length + ') ---');
  errors.forEach((e, idx) => console.log(`${idx + 1}: ${e}`));

  await browser.close();
  console.log('\nPlaywright verification completed.');
})();
