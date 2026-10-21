# Claw Desk — 20-second trading floor illustration

This is a marketing animation based on the project's original pixel room, not a recording of live trading. The video includes a visible **Illustrative animation** caption. It does not use the API, a wallet, market data, account balances or financial permissions. Scenario figures are local animation values only.

The continuous 1440 x 1080, 30 fps scene shows three crustacean agents walking between workstations, reviewing a setup, checking risk and counting illustrated profit. Six positive scenario outcomes animate realized PnL from $331.30 to $396.40, equity from $1,251.30 to $1,316.40 and the half-profit charity pool from $165.65 to $198.20. The pre-existing illustrative $80 sent amount stays fixed; no payment is depicted as newly sent.

To reproduce from the repository root after installing Node dependencies:

```powershell
node scripts/agent-floor-film.mjs
```

Open `http://127.0.0.1:8766/` in a modern Chromium browser, keep the tab active and choose **Record 20-second film**. The local renderer loads the same two font families as the app from installed packages. Only the canvas is recorded; page controls are excluded. The browser selects supported MP4/H.264 or WebM encoding. The result is written to ignored `artifacts/agent-floor-film/claw-desk-agents-20s.mp4` (or `.webm`). Stop the renderer with Ctrl+C afterward. No production service is started or changed.

The source is `scene.html`; drawing and movement are timed in seconds and independent of the trading application. The local save endpoint is loopback-only, checks its generated session token and exact origin, accepts only video MIME types and bounds the output to 64 MiB. No arbitrary upload destination is accepted.

The delivered `artifacts/agent-floor-film/Claw-Desk-20s.mp4` was normalized from the browser recording with FFmpeg to exactly 600 frames / 20 seconds, H.264/yuv420p at 30 fps, with fast-start metadata and no audio. All frames decoded without errors; beginning, middle, profit-burst and end frames were inspected. Local `verification.json` records the output properties. The optional FFmpeg tool was installed only in ignored `artifacts/video-tools`; it is not an application dependency.
