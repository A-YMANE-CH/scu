from __future__ import annotations

HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Entrance Counter</title>
  <style>
    :root {
      --bg: #0d1117;
      --bg2: #111823;
      --panel: rgba(22, 29, 39, 0.96);
      --panel2: rgba(15, 21, 29, 0.92);
      --field: rgba(255,255,255,0.055);
      --line: rgba(224,232,242,0.13);
      --line-strong: rgba(224,232,242,0.22);
      --text: #edf2f7;
      --muted: #a6b3c2;
      --soft: #687789;
      --accent: #35c2a9;
      --accent2: #6aa4f8;
      --warn: #e2b84f;
      --bad: #ee667a;
      --ok: #42d58a;
      --shadow: 0 18px 54px rgba(0,0,0,0.38);
      --r: 8px;
    }
    body.light {
      --bg: #eef3f8;
      --bg2: #f7f9fc;
      --panel: rgba(255,255,255,0.96);
      --panel2: rgba(245,248,252,0.94);
      --field: #f8fafc;
      --line: rgba(31,45,61,0.14);
      --line-strong: rgba(31,45,61,0.25);
      --text: #132033;
      --muted: #596b80;
      --soft: #7e8da0;
      --accent: #137f72;
      --accent2: #2766d8;
      --warn: #9a6a00;
      --bad: #c93655;
      --ok: #168454;
      --shadow: 0 18px 42px rgba(31,45,61,0.12);
    }
    * { box-sizing: border-box; }
    html, body { width: 100%; height: 100%; margin: 0; }
    body {
      overflow: hidden;
      background:
        linear-gradient(135deg, rgba(53,194,169,0.10), transparent 34%),
        linear-gradient(315deg, rgba(106,164,248,0.11), transparent 38%),
        var(--bg);
      color: var(--text);
      font: 13px/1.35 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    body.light {
      background:
        linear-gradient(135deg, rgba(19,127,114,0.08), transparent 32%),
        linear-gradient(315deg, rgba(39,102,216,0.08), transparent 38%),
        var(--bg);
    }
    button, select, input {
      font: inherit;
      color: inherit;
    }
    button {
      height: 34px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: var(--field);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 7px;
      padding: 0 11px;
    }
    button:hover { border-color: var(--line-strong); background: color-mix(in srgb, var(--field) 80%, var(--accent) 20%); }
    button.active { background: color-mix(in srgb, var(--accent) 18%, transparent); border-color: color-mix(in srgb, var(--accent) 62%, transparent); color: var(--text); }
    button.icon { width: 34px; padding: 0; }
    .app {
      height: 100%;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
    }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      padding: 10px 14px;
      border-bottom: 1px solid var(--line);
      background: color-mix(in srgb, var(--panel2) 92%, transparent);
      backdrop-filter: blur(16px);
      box-shadow: var(--shadow);
      z-index: 20;
      min-height: 62px;
    }
    .brand {
      min-width: 230px;
      display: flex;
      flex-direction: column;
      gap: 1px;
    }
    .brand strong {
      font-size: 16px;
      font-weight: 760;
    }
    .brand span { color: var(--muted); font-size: 12px; }
    .counters {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: center;
    }
    .counter {
      min-width: 132px;
      height: 40px;
      border: 1px solid var(--line);
      border-radius: var(--r);
      background: rgba(255,255,255,0.055);
      padding: 6px 10px;
      display: grid;
      grid-template-columns: 1fr auto;
      align-items: center;
      column-gap: 10px;
    }
    .counter span { color: var(--muted); font-size: 11px; text-transform: uppercase; font-weight: 720; }
    .counter b { font-size: 24px; line-height: 1; }
    .hidden-exits { display: none !important; }
    .top-actions { display: flex; gap: 8px; align-items: center; justify-content: flex-end; flex-wrap: wrap; }
    .main {
      min-height: 0;
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(360px, 420px);
      gap: 12px;
      padding: 12px;
      overflow: hidden;
    }
    .feeds {
      min-width: 0;
      min-height: 0;
      display: grid;
      grid-template-columns: 1fr;
      gap: 12px;
    }
    .feeds.two-up {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .feeds.selected-only .tile:not(.active) {
      display: none;
    }
    .tile {
      min-width: 0;
      min-height: 0;
      position: relative;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: var(--r);
      background: #05080d;
      box-shadow: var(--shadow);
    }
    body.light .tile { background: #101820; }
    .tile.active { border-color: rgba(41,199,184,0.78); }
    .tile img {
      width: 100%;
      height: 100%;
      display: block;
      object-fit: contain;
      background: #05080d;
    }
    .calibration {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      cursor: crosshair;
    }
    .tile-head {
      position: absolute;
      top: 10px;
      left: 10px;
      right: 10px;
      z-index: 4;
      display: flex;
      justify-content: space-between;
      gap: 8px;
      pointer-events: none;
    }
    .badge {
      min-height: 28px;
      padding: 5px 9px;
      border: 1px solid rgba(255,255,255,0.16);
      border-radius: 999px;
      background: rgba(7,10,15,0.72);
      backdrop-filter: blur(12px);
      color: var(--text);
      font-weight: 730;
      display: inline-flex;
      align-items: center;
      gap: 7px;
      white-space: nowrap;
    }
    body.light .badge {
      background: rgba(255,255,255,0.86);
      border-color: rgba(31,45,61,0.16);
      color: var(--text);
    }
    .badge small { color: var(--muted); font-weight: 680; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--soft); }
    .dot.run { background: var(--ok); box-shadow: 0 0 0 4px rgba(72,223,143,0.14); }
    .dot.err { background: var(--bad); box-shadow: 0 0 0 4px rgba(255,93,115,0.14); }
    .side {
      min-height: 0;
      display: grid;
      grid-template-rows: auto auto auto minmax(0, 1fr);
      gap: 12px;
      overflow-y: auto;
      padding-right: 4px;
      scrollbar-width: thin;
      scrollbar-color: var(--line-strong) transparent;
    }
    .panel {
      border: 1px solid var(--line);
      border-radius: var(--r);
      background: var(--panel);
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .panel h2 {
      margin: 0;
      padding: 12px 13px 10px;
      font-size: 12px;
      text-transform: uppercase;
      color: var(--muted);
      letter-spacing: 0;
      border-bottom: 1px solid var(--line);
    }
    .panel-body { padding: 12px; }
    .seg { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
    .seg.three { grid-template-columns: repeat(3, 1fr); }
    .field {
      display: grid;
      gap: 6px;
      margin-top: 11px;
    }
    label {
      color: var(--muted);
      font-size: 11px;
      font-weight: 760;
      text-transform: uppercase;
    }
    select, input {
      height: 34px;
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: var(--field);
      padding: 0 9px;
      outline: none;
    }
    input[type="range"] { padding: 0; accent-color: var(--accent); }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .events {
      overflow: hidden;
      display: grid;
      grid-template-rows: auto 1fr;
      min-height: 260px;
    }
    .event-list {
      overflow: auto;
      padding: 6px;
    }
    .event {
      padding: 9px 10px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 6px;
      border-radius: 7px;
      border: 1px solid transparent;
    }
    .event:nth-child(odd) { background: rgba(255,255,255,0.035); }
    .event strong { font-size: 13px; }
    .event span { color: var(--muted); font-size: 12px; }
    .empty {
      color: var(--soft);
      padding: 18px 10px;
      text-align: center;
    }
    .save-state {
      color: var(--muted);
      font-size: 12px;
      min-height: 16px;
      padding-top: 8px;
    }
    .modal-backdrop {
      position: fixed;
      inset: 0;
      z-index: 60;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 24px;
      background: rgba(2, 5, 9, 0.72);
      backdrop-filter: blur(10px);
    }
    body.light .modal-backdrop { background: rgba(20, 31, 45, 0.34); }
    .modal-backdrop.open { display: flex; }
    .modal {
      width: min(820px, 100%);
      max-height: min(760px, 92vh);
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
      border: 1px solid var(--line);
      border-radius: var(--r);
      background: var(--panel);
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .modal-head, .modal-actions {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 12px;
      border-bottom: 1px solid var(--line);
    }
    .modal-actions { border-top: 1px solid var(--line); border-bottom: 0; justify-content: flex-end; }
    .modal-head h2 { margin: 0; font-size: 15px; }
    .store-list {
      overflow: auto;
      display: grid;
      gap: 10px;
      padding: 12px;
    }
    .store-card {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: var(--panel2);
      display: grid;
      gap: 8px;
    }
    .store-card.active { border-color: color-mix(in srgb, var(--accent) 62%, transparent); background: color-mix(in srgb, var(--accent) 8%, var(--panel2)); }
    .store-card-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
    .store-card-head strong { font-size: 13px; }
    .metric-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .metric {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel2);
      padding: 9px 10px;
    }
    .metric span { display: block; color: var(--muted); font-size: 11px; font-weight: 760; text-transform: uppercase; }
    .metric b { display: block; margin-top: 4px; font-size: 22px; }
    .clean-modal {
      width: min(1280px, 100%);
      max-height: min(860px, 94vh);
    }
    .clean-view {
      min-height: 0;
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(240px, 300px);
      gap: 14px;
      padding: 14px;
      overflow: auto;
    }
    .clean-video {
      min-height: 420px;
      border: 1px solid var(--line);
      border-radius: var(--r);
      background: #05080d;
      overflow: hidden;
    }
    .clean-video img {
      width: 100%;
      height: 100%;
      display: block;
      object-fit: contain;
    }
    .clean-stats {
      display: grid;
      gap: 10px;
      align-content: start;
    }
    .count-editor-grid {
      display: grid;
      gap: 10px;
    }
    .count-editor-row {
      display: grid;
      grid-template-columns: 110px repeat(3, minmax(0, 1fr));
      gap: 10px;
      align-items: end;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: var(--r);
      background: var(--panel2);
    }
    .count-editor-row strong {
      align-self: center;
      font-size: 13px;
    }
    .clean-stat {
      border: 1px solid var(--line);
      border-radius: var(--r);
      background: var(--panel2);
      padding: 14px;
    }
    .clean-stat span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 760;
      text-transform: uppercase;
    }
    .clean-stat b {
      display: block;
      margin-top: 6px;
      font-size: 34px;
      line-height: 1;
    }
    @media (max-width: 1180px) {
      body { overflow: auto; }
      .app { height: auto; min-height: 100%; }
      .main { grid-template-columns: 1fr; overflow: visible; }
      .feeds { min-height: 560px; }
      .side { grid-template-columns: 1fr 1fr; grid-template-rows: auto auto; overflow: visible; padding-right: 0; }
      .events { grid-column: 1 / -1; min-height: 260px; }
      .clean-view { grid-template-columns: 1fr; }
    }
    @media (max-width: 780px) {
      body { overflow: auto; }
      .app { min-height: 100%; height: auto; }
      .topbar, .counters, .top-actions, .feeds, .side { flex-wrap: wrap; grid-template-columns: 1fr; }
      .topbar { align-items: flex-start; }
      .brand { min-width: 100%; }
      .main { min-height: 980px; }
    }

    /* Presentation dashboard redesign */
    :root {
      --bg: #090d13;
      --bg2: #0f1722;
      --panel: #141c28;
      --panel2: #101722;
      --field: #0d141e;
      --line: rgba(221, 230, 241, 0.13);
      --line-strong: rgba(221, 230, 241, 0.24);
      --text: #f3f6fa;
      --muted: #95a3b5;
      --soft: #667589;
      --accent: #2dd4bf;
      --accent2: #60a5fa;
      --bad: #fb7185;
      --ok: #34d399;
      --shadow: 0 18px 44px rgba(0, 0, 0, 0.30);
      --r: 8px;
    }
    body.light {
      --bg: #e9eef5;
      --bg2: #f8fafc;
      --panel: #ffffff;
      --panel2: #f4f7fb;
      --field: #f8fafc;
      --line: rgba(26, 42, 62, 0.14);
      --line-strong: rgba(26, 42, 62, 0.24);
      --text: #111827;
      --muted: #5b6878;
      --soft: #7b8794;
      --accent: #0f766e;
      --accent2: #2563eb;
      --bad: #be123c;
      --ok: #15803d;
      --shadow: 0 18px 38px rgba(26, 42, 62, 0.12);
    }
    html, body {
      overflow: hidden;
      background: var(--bg);
    }
    body {
      background:
        radial-gradient(circle at 18% 10%, rgba(45, 212, 191, 0.12), transparent 28%),
        radial-gradient(circle at 82% 0%, rgba(96, 165, 250, 0.10), transparent 30%),
        linear-gradient(180deg, var(--bg2), var(--bg));
    }
    body.light {
      background:
        radial-gradient(circle at 18% 10%, rgba(15, 118, 110, 0.08), transparent 28%),
        radial-gradient(circle at 82% 0%, rgba(37, 99, 235, 0.08), transparent 30%),
        linear-gradient(180deg, var(--bg2), var(--bg));
    }
    .app {
      height: 100vh;
      min-height: 0;
      grid-template-rows: 68px minmax(0, 1fr);
    }
    .topbar {
      min-height: 68px;
      padding: 12px 18px;
      background: color-mix(in srgb, var(--panel) 92%, transparent);
      border-bottom: 1px solid var(--line);
      box-shadow: 0 10px 30px rgba(0,0,0,0.16);
    }
    .brand strong {
      font-size: 18px;
      font-weight: 750;
    }
    .brand span {
      color: var(--muted);
    }
    .counter {
      min-width: 120px;
      height: 44px;
      background: var(--panel2);
      border-color: var(--line);
      box-shadow: none;
    }
    .counter b {
      font-size: 25px;
      color: var(--text);
    }
    button, select, input {
      border-radius: 8px;
    }
    button {
      background: var(--field);
      border-color: var(--line);
      color: var(--text);
      transition: border-color .15s, background .15s, transform .15s;
    }
    button:hover {
      border-color: var(--line-strong);
      background: color-mix(in srgb, var(--field) 84%, var(--accent2) 16%);
    }
    button.active {
      background: color-mix(in srgb, var(--accent) 18%, var(--field));
      border-color: color-mix(in srgb, var(--accent) 58%, var(--line));
    }
    select, input {
      background: var(--field);
      border-color: var(--line);
      color: var(--text);
    }
    select:focus, input:focus {
      border-color: color-mix(in srgb, var(--accent2) 70%, var(--line));
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent2) 18%, transparent);
    }
    .main {
      height: 100%;
      min-height: 0;
      grid-template-columns: minmax(620px, 1fr) 410px;
      gap: 16px;
      padding: 16px;
      overflow: hidden;
    }
    .feeds {
      min-height: 0;
      overflow: hidden;
    }
    .tile {
      border-radius: 10px;
      background: #05070b;
      border-color: var(--line);
      box-shadow: var(--shadow);
    }
    .tile.active {
      border-color: color-mix(in srgb, var(--accent) 64%, var(--line));
    }
    .tile img {
      background: #05070b;
    }
    .tile-head {
      top: 14px;
      left: 14px;
      right: 14px;
    }
    .badge {
      min-height: 31px;
      padding: 6px 11px;
      border-radius: 8px;
      background: rgba(5, 9, 14, 0.76);
      border-color: rgba(255,255,255,0.14);
      box-shadow: 0 8px 20px rgba(0,0,0,0.18);
    }
    body.light .badge {
      background: rgba(255,255,255,0.88);
      border-color: rgba(26,42,62,0.14);
      box-shadow: 0 8px 18px rgba(26,42,62,0.10);
    }
    .side {
      min-height: 0;
      overflow: hidden;
      display: grid;
      grid-template-rows:
        minmax(210px, 230px)
        minmax(220px, 255px)
        minmax(150px, 185px)
        minmax(220px, 1fr);
      gap: 12px;
      padding-right: 0;
    }
    .panel {
      min-height: 0;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      border-radius: 10px;
      background: var(--panel);
      border-color: var(--line);
      box-shadow: var(--shadow);
    }
    .panel h2 {
      padding: 12px 14px 11px;
      color: var(--muted);
      background: color-mix(in srgb, var(--panel2) 70%, transparent);
      border-bottom-color: var(--line);
      font-size: 11px;
      font-weight: 800;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    .collapse-panel-btn {
      width: 28px;
      height: 24px;
      padding: 0;
      border-radius: 6px;
      font-size: 13px;
      line-height: 1;
    }
    .panel.collapsed {
      grid-template-rows: auto;
      min-height: 0;
    }
    .panel.collapsed .panel-body,
    .panel.collapsed .event-list {
      display: none;
    }
    .panel-body {
      min-height: 0;
      overflow-y: auto;
      padding: 13px;
      scrollbar-width: thin;
      scrollbar-color: var(--line-strong) transparent;
    }
    .events {
      min-height: 0;
      overflow: hidden;
    }
    .event-list {
      min-height: 0;
      overflow-y: auto;
      padding: 8px;
      scrollbar-width: thin;
      scrollbar-color: var(--line-strong) transparent;
    }
    .event {
      background: var(--panel2);
      border-color: var(--line);
      margin-bottom: 6px;
    }
    .event:nth-child(odd) {
      background: var(--panel2);
    }
    .metric {
      background: var(--panel2);
      border-color: var(--line);
    }
    .metric b {
      color: var(--text);
    }
    .modal {
      background: var(--panel);
      border-radius: 10px;
      max-height: 86vh;
    }
    .store-list {
      min-height: 0;
      overflow-y: auto;
      scrollbar-width: thin;
      scrollbar-color: var(--line-strong) transparent;
    }
    .store-card {
      background: var(--panel2);
      border-color: var(--line);
    }
    @media (max-width: 1180px) {
      html, body {
        overflow: auto;
      }
      .app {
        height: auto;
        min-height: 100vh;
      }
      .topbar {
        min-height: 86px;
        align-items: flex-start;
      }
      .main {
        grid-template-columns: 1fr;
        grid-template-rows: minmax(420px, 52vh) auto;
        overflow: visible;
      }
      .feeds {
        min-height: 0;
      }
      .side {
        grid-template-columns: 1fr 1fr;
        grid-template-rows: auto auto;
        overflow: visible;
      }
      .events {
        grid-column: 1 / -1;
      }
    }
    @media (max-width: 780px) {
      html, body {
        overflow: auto;
      }
      .app {
        height: auto;
        min-height: 100vh;
      }
      .topbar {
        position: sticky;
        top: 0;
        z-index: 30;
      }
      .main {
        height: auto;
        min-height: 0;
        grid-template-rows: 420px auto;
        overflow: visible;
      }
      .side {
        display: grid;
        grid-template-columns: 1fr;
        grid-template-rows: none;
        overflow: visible;
      }
      .panel {
        min-height: 220px;
      }
      .events {
        min-height: 280px;
      }
    }

    /* Final presentation layout: global scroll + independently scrollable content */
    html,
    body {
      min-height: 100%;
      overflow-y: auto !important;
      overflow-x: hidden;
    }
    body {
      background:
        radial-gradient(circle at 18% 8%, rgba(45, 212, 191, 0.10), transparent 24%),
        radial-gradient(circle at 86% 4%, rgba(96, 165, 250, 0.12), transparent 28%),
        linear-gradient(180deg, #0b111a 0%, var(--bg) 52%, #070a0f 100%);
    }
    body.light {
      background:
        radial-gradient(circle at 18% 8%, rgba(15, 118, 110, 0.07), transparent 24%),
        radial-gradient(circle at 86% 4%, rgba(37, 99, 235, 0.08), transparent 28%),
        linear-gradient(180deg, #f8fafc 0%, var(--bg) 100%);
    }
    .app {
      height: auto !important;
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    .topbar {
      position: sticky;
      top: 0;
      z-index: 40;
      min-height: 70px;
      background: color-mix(in srgb, var(--panel) 94%, transparent);
      border-bottom: 1px solid var(--line);
    }
    .main {
      min-height: calc(100vh - 70px);
      height: auto !important;
      grid-template-columns: minmax(620px, 1fr) minmax(380px, 430px);
      align-items: start;
      overflow: visible !important;
      gap: 18px;
      padding: 18px;
    }
    .feeds {
      position: sticky;
      top: 88px;
      height: calc(100vh - 106px);
      min-height: 520px;
      overflow: visible;
    }
    .tile {
      height: 100%;
      border-radius: 12px;
      border: 1px solid color-mix(in srgb, var(--line) 82%, var(--accent) 18%);
    }
    .side {
      display: flex !important;
      flex-direction: column;
      gap: 14px;
      min-height: 0;
      overflow: visible !important;
      padding: 0;
    }
    .panel {
      display: block !important;
      min-height: 0 !important;
      overflow: hidden;
      border-radius: 12px;
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--panel) 94%, white 6%), var(--panel));
      border: 1px solid var(--line);
      box-shadow: 0 12px 32px rgba(0, 0, 0, 0.22);
    }
    body.light .panel {
      background: #ffffff;
      box-shadow: 0 12px 30px rgba(26, 42, 62, 0.10);
    }
    .panel h2 {
      min-height: 44px;
      padding: 11px 12px 10px 14px;
      background: var(--panel2);
      border-bottom: 1px solid var(--line);
      color: var(--muted);
    }
    .panel-body {
      display: block;
      max-height: 270px;
      overflow-y: auto;
      padding: 14px;
    }
    .panel[data-panel="performance"] .panel-body {
      max-height: 310px;
    }
    .panel[data-panel="camera"] .panel-body {
      max-height: 330px;
    }
    .panel[data-panel="calibration"] .panel-body {
      max-height: 230px;
    }
    .events {
      min-height: 0 !important;
      height: auto;
    }
    .events .event-list {
      max-height: 340px;
      min-height: 180px;
      overflow-y: auto;
    }
    .panel.collapsed {
      height: auto !important;
      min-height: 44px !important;
      flex: 0 0 auto;
    }
    .panel.collapsed h2 {
      border-bottom: 0;
    }
    .panel.collapsed .panel-body,
    .panel.collapsed .event-list {
      display: none !important;
    }
    .collapse-panel-btn {
      background: color-mix(in srgb, var(--field) 80%, transparent);
      border-color: var(--line);
      color: var(--muted);
    }
    .collapse-panel-btn:hover {
      color: var(--text);
      border-color: var(--line-strong);
    }
    .metric {
      border-radius: 10px;
      padding: 11px 12px;
    }
    .metric b {
      font-size: 26px;
    }
    .counter {
      background: var(--panel2);
      border-radius: 10px;
    }
    .event {
      grid-template-columns: 1fr auto;
      border-radius: 9px;
      padding: 10px 11px;
    }
    .modal {
      max-height: 88vh;
    }
    .store-list {
      max-height: calc(88vh - 118px);
      overflow-y: auto;
    }
    @media (max-width: 1180px) {
      .main {
        grid-template-columns: 1fr;
      }
      .feeds {
        position: relative;
        top: auto;
        height: min(62vh, 680px);
      }
      .side {
        display: grid !important;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        align-items: start;
      }
      .events {
        grid-column: 1 / -1;
      }
    }
    @media (max-width: 780px) {
      .topbar {
        position: sticky;
      }
      .main {
        padding: 12px;
      }
      .feeds {
        height: 430px;
        min-height: 360px;
      }
      .side {
        display: flex !important;
      }
      .panel-body,
      .events .event-list {
        max-height: none;
      }
    }
  </style>
</head>
<body>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <strong>Entrance Counter</strong>
        <span id="statusText">Connecting</span>
      </div>
      <div class="counters" id="counters"></div>
      <div class="top-actions">
        <button id="cleanViewBtn">Clean View</button>
        <button id="cameraModeBtn">Two Cameras</button>
        <button id="exitToggleBtn">Hide Exits</button>
        <button id="themeBtn">Light Mode</button>
        <button id="storesBtn">Stores</button>
        <button id="saveBtn">Save</button>
        <button id="resetBtn">Reset Counters</button>
      </div>
    </header>
    <main class="main">
      <section class="feeds" id="feeds"></section>
      <aside class="side">
        <section class="panel" data-panel="performance">
          <h2><span>Store Performance</span><button class="collapse-panel-btn" data-collapse="performance">-</button></h2>
          <div class="panel-body">
            <div class="field" style="margin-top:0">
              <label>Selected Store</label>
              <select id="storeSelect"></select>
            </div>
            <div class="row">
              <div class="field">
                <label>Sales Number</label>
                <input id="salesInput" type="number" min="0" step="1">
              </div>
              <div class="field">
                <label>Conversion Rate</label>
                <input id="conversionInput" type="text" disabled>
              </div>
            </div>
            <div class="metric-grid" style="margin-top:10px">
              <div class="metric"><span>Entrants</span><b id="entrantsMetric">0</b></div>
              <div class="metric exit-ui"><span>Exits</span><b id="exitsMetric">0</b></div>
              <div class="metric"><span>Purchases</span><b id="salesMetric">0</b></div>
            </div>
          </div>
        </section>
        <section class="panel" data-panel="camera">
          <h2><span>Camera</span><button class="collapse-panel-btn" data-collapse="camera">-</button></h2>
          <div class="panel-body">
            <div class="seg" id="cameraButtons"></div>
            <div class="field">
              <label>Crossing Point</label>
              <select id="footSource">
                <option value="center">Box center</option>
                <option value="pose">Pose ankles</option>
                <option value="box">Box bottom</option>
              </select>
            </div>
            <div class="field">
              <label>Stream Quality</label>
              <select id="qualitySelect">
                <option value="low">Lowest stream if available</option>
                <option value="sub">Low latency substream</option>
                <option value="main">Main stream</option>
              </select>
            </div>
            <div class="field">
              <label>Detection Model</label>
              <select id="modelSelect">
                <option value="x">YOLOX-Tiny - OpenVINO</option>
                <option value="n">YOLOv8n - PyTorch</option>
                <option value="ov">YOLOv8n - OpenVINO</option>
                <option value="s">YOLOv8s - more accurate</option>
              </select>
            </div>
            <div class="row">
              <div class="field">
                <label>Confidence</label>
                <input id="confInput" type="number" min="0.05" max="0.95" step="0.01">
              </div>
              <div class="field">
                <label>GPU Device</label>
                <input id="deviceInput" type="text" disabled>
              </div>
            </div>
          </div>
        </section>
        <section class="panel" data-panel="calibration">
          <h2><span>Calibration</span><button class="collapse-panel-btn" data-collapse="calibration">-</button></h2>
          <div class="panel-body">
            <div class="seg three">
              <button class="tool active" data-tool="line">Line</button>
              <button class="tool" data-tool="roi">ROI</button>
              <button class="tool" data-tool="reflection">Glass</button>
            </div>
            <div class="field">
              <label>Direction</label>
              <div class="seg">
                <button id="flipBtn">Flip Entry Side</button>
                <button id="clearGlassBtn">Clear Glass</button>
              </div>
            </div>
            <div class="save-state" id="saveState"></div>
          </div>
        </section>
        <section class="panel events" data-panel="events">
          <h2><span>Recent Events</span><button class="collapse-panel-btn" data-collapse="events">-</button></h2>
          <div class="event-list" id="eventList"></div>
        </section>
      </aside>
    </main>
    <div class="modal-backdrop" id="storesModal">
      <div class="modal">
        <div class="modal-head">
          <h2>Stores</h2>
          <button class="icon" id="closeStoresBtn">X</button>
        </div>
        <div class="store-list" id="storeList"></div>
        <div class="modal-actions">
          <button id="addStoreBtn">Add Store</button>
          <button id="saveStoresBtn" class="active">Save Stores</button>
        </div>
      </div>
    </div>
    <div class="modal-backdrop" id="cleanModal">
      <div class="modal clean-modal">
        <div class="modal-head">
          <h2>Live Store View</h2>
          <button class="icon" id="closeCleanBtn">X</button>
        </div>
        <div class="clean-view">
          <div class="clean-video">
            <img id="cleanFeed" alt="Clean live camera feed">
          </div>
          <div class="clean-stats">
            <div class="clean-stat"><span>Entries</span><b id="cleanEntries">0</b></div>
            <div class="clean-stat exit-ui"><span>Exits</span><b id="cleanExits">0</b></div>
            <div class="clean-stat exit-ui"><span>Net Inside</span><b id="cleanNet">0</b></div>
            <div class="clean-stat"><span>Sales</span><b id="cleanSales">0</b></div>
            <div class="clean-stat"><span>Conversion Rate</span><b id="cleanConversion">0.0%</b></div>
          </div>
        </div>
        <div class="modal-actions">
          <button id="closeCleanFooterBtn">Close</button>
        </div>
      </div>
    </div>
    <div class="modal-backdrop" id="countModal">
      <div class="modal">
        <div class="modal-head">
          <h2>Count Correction</h2>
          <button class="icon" id="closeCountBtn">X</button>
        </div>
        <div class="count-editor-grid" id="countFields"></div>
        <div class="save-state" id="countSaveState"></div>
        <div class="modal-actions">
          <button id="cancelCountBtn">Cancel</button>
          <button id="saveCountBtn" class="active">Apply Correction</button>
        </div>
      </div>
    </div>
  </div>
  <script>
    let cameras = ["cam_501"];
    let state = { cameras: {}, events: [], config: {} };
    let selected = "cam_501";
    let tool = "line";
    let dragging = null;
    let dirty = false;

    const feeds = document.getElementById("feeds");
    const counters = document.getElementById("counters");
    const cameraButtons = document.getElementById("cameraButtons");
    const eventList = document.getElementById("eventList");
    const statusText = document.getElementById("statusText");
    const saveState = document.getElementById("saveState");
    const footSource = document.getElementById("footSource");
    const modelSelect = document.getElementById("modelSelect");
    const qualitySelect = document.getElementById("qualitySelect");
    const confInput = document.getElementById("confInput");
    const deviceInput = document.getElementById("deviceInput");
    const storesModal = document.getElementById("storesModal");
    const cleanModal = document.getElementById("cleanModal");
    const countModal = document.getElementById("countModal");
    const cleanFeed = document.getElementById("cleanFeed");
    const countFields = document.getElementById("countFields");
    const countSaveState = document.getElementById("countSaveState");
    const storeList = document.getElementById("storeList");
    const storeSelect = document.getElementById("storeSelect");
    const salesInput = document.getElementById("salesInput");
    const conversionInput = document.getElementById("conversionInput");
    const entrantsMetric = document.getElementById("entrantsMetric");
    const exitsMetric = document.getElementById("exitsMetric");
    const salesMetric = document.getElementById("salesMetric");
    const themeBtn = document.getElementById("themeBtn");
    const exitToggleBtn = document.getElementById("exitToggleBtn");
    const cameraModeBtn = document.getElementById("cameraModeBtn");
    const cleanEntries = document.getElementById("cleanEntries");
    const cleanExits = document.getElementById("cleanExits");
    const cleanNet = document.getElementById("cleanNet");
    const cleanSales = document.getElementById("cleanSales");
    const cleanConversion = document.getElementById("cleanConversion");

    function applyTheme(theme) {
      document.body.classList.toggle("light", theme === "light");
      themeBtn.textContent = theme === "light" ? "Dark Mode" : "Light Mode";
      localStorage.setItem("entranceTheme", theme);
      drawAll();
    }

    function showExits() {
      return localStorage.getItem("entranceShowExits") !== "0";
    }

    function applyExitVisibility() {
      const visible = showExits();
      exitToggleBtn.textContent = visible ? "Hide Exits" : "Show Exits";
      exitToggleBtn.classList.toggle("active", !visible);
      document.querySelectorAll(".exit-ui").forEach(el => el.classList.toggle("hidden-exits", !visible));
      document.body.classList.toggle("exits-hidden", !visible);
    }

    function showAllCameras() {
      return localStorage.getItem("entranceShowAllCameras") !== "0";
    }

    function applyCameraMode() {
      const multi = cameras.length > 1;
      cameraModeBtn.style.display = multi ? "" : "none";
      const showAll = showAllCameras() && multi;
      cameraModeBtn.textContent = showAll ? "Single Camera" : "Two Cameras";
      cameraModeBtn.classList.toggle("active", showAll);
      feeds.classList.toggle("two-up", showAll);
      feeds.classList.toggle("selected-only", !showAll);
      drawAll();
    }

    function collapsedPanels() {
      try {
        return JSON.parse(localStorage.getItem("entranceCollapsedPanels") || "{}");
      } catch {
        return {};
      }
    }

    function applyCollapsedPanels() {
      const collapsed = collapsedPanels();
      document.querySelectorAll("[data-panel]").forEach(panel => {
        const key = panel.dataset.panel;
        const isCollapsed = !!collapsed[key];
        panel.classList.toggle("collapsed", isCollapsed);
        const btn = panel.querySelector(".collapse-panel-btn");
        if (btn) btn.textContent = isCollapsed ? "+" : "-";
      });
    }

    function togglePanel(key) {
      const collapsed = collapsedPanels();
      collapsed[key] = !collapsed[key];
      localStorage.setItem("entranceCollapsedPanels", JSON.stringify(collapsed));
      applyCollapsedPanels();
      drawAll();
    }

    function makeFeeds() {
      feeds.innerHTML = "";
      cameraButtons.innerHTML = "";
      if (!cameras.includes(selected)) selected = cameras[0] || "cam_501";
      for (const cam of cameras) {
        const tile = document.createElement("div");
        tile.className = "tile";
        tile.dataset.camera = cam;
        tile.innerHTML = `
          <img src="/video.mjpg?camera_id=${encodeURIComponent(cam)}">
          <canvas class="calibration"></canvas>
          <div class="tile-head">
            <div class="badge"><i class="dot"></i>${cam.replace("cam_", "Camera ")}</div>
            <div class="badge"><small>in</small><b class="tile-count">0</b><small class="tile-exit-label">out</small><b class="tile-exit-count">0</b></div>
          </div>`;
        tile.addEventListener("click", () => selectCamera(cam));
        feeds.appendChild(tile);
        bindCanvas(tile.querySelector(".calibration"));

        const btn = document.createElement("button");
        btn.dataset.camera = cam;
        btn.textContent = cam.replace("cam_", "Camera ");
        btn.onclick = () => selectCamera(cam);
        cameraButtons.appendChild(btn);
      }
      selectCamera(selected);
      applyCameraMode();
    }

    function selectCamera(cam) {
      selected = cam;
      document.querySelectorAll(".tile").forEach(el => el.classList.toggle("active", el.dataset.camera === cam));
      [...cameraButtons.children].forEach(btn => btn.classList.toggle("active", btn.dataset.camera === cam));
      if (cleanModal.classList.contains("open")) {
        cleanFeed.src = `/video.mjpg?camera_id=${encodeURIComponent(selected)}&overlay=0&view=${Date.now()}`;
      }
      drawAll();
    }

    function openCleanView() {
      cleanFeed.src = `/video.mjpg?camera_id=${encodeURIComponent(selected)}&overlay=0&view=${Date.now()}`;
      cleanModal.classList.add("open");
      updateCleanStats();
    }

    function closeCleanView() {
      cleanModal.classList.remove("open");
      cleanFeed.removeAttribute("src");
    }

    function imageRect(canvas) {
      const tileRect = canvas.getBoundingClientRect();
      const img = canvas.closest(".tile").querySelector("img");
      const nw = img.naturalWidth || tileRect.width;
      const nh = img.naturalHeight || tileRect.height;
      const tileAspect = tileRect.width / Math.max(1, tileRect.height);
      const imageAspect = nw / Math.max(1, nh);
      if (imageAspect > tileAspect) {
        const h = tileRect.width / imageAspect;
        return { left: tileRect.left, top: tileRect.top + (tileRect.height - h) / 2, width: tileRect.width, height: h };
      }
      const w = tileRect.height * imageAspect;
      return { left: tileRect.left + (tileRect.width - w) / 2, top: tileRect.top, width: w, height: tileRect.height };
    }

    function normFromEvent(canvas, event) {
      const rect = imageRect(canvas);
      return [
        Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
        Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))
      ];
    }

    function geom(cam) {
      return state.config.geometries?.[cam] || null;
    }

    function defaultGeom(cam, p) {
      return {
        camera_id: cam,
        roi: [0, 0, 1, 1],
        line: [p[0], p[1], p[0], p[1]],
        direction_axis: "line",
        enter_direction: 1,
        min_box_height_ratio: cam === "cam_501" ? 0.11 : 0.08,
        min_box_area_ratio: cam === "cam_501" ? 0.003 : 0.002,
        reflection_zone: null
      };
    }

    function setGeom(cam, next) {
      state.config.geometries = state.config.geometries || {};
      state.config.geometries[cam] = next;
      dirty = true;
      drawAll();
    }

    function nearestHandle(g, p) {
      const handles = [];
      if (tool === "line") {
        handles.push(["line0", g.line[0], g.line[1]], ["line1", g.line[2], g.line[3]]);
      } else {
        const key = tool === "reflection" ? "reflection_zone" : "roi";
        const b = g[key] || [0.62, 0.1, 0.95, 0.95];
        handles.push([`${key}0`, b[0], b[1]], [`${key}1`, b[2], b[3]]);
      }
      let best = null;
      let bestD = 0.05;
      for (const h of handles) {
        const d = Math.hypot(h[1] - p[0], h[2] - p[1]);
        if (d < bestD) { bestD = d; best = h[0]; }
      }
      return best;
    }

    function bindCanvas(canvas) {
      canvas.addEventListener("pointerdown", event => {
        const cam = canvas.closest(".tile").dataset.camera;
        if (cam !== selected) selectCamera(cam);
        const p = normFromEvent(canvas, event);
        const existing = geom(cam);
        const g = structuredClone(existing || defaultGeom(cam, p));
        dragging = { cam, handle: existing ? (nearestHandle(g, p) || "new") : "new", start: p };
        if (dragging.handle === "new") {
          if (tool === "line") g.line = [p[0], p[1], p[0], p[1]];
          if (tool === "roi") g.roi = [p[0], p[1], p[0], p[1]];
          if (tool === "reflection") g.reflection_zone = [p[0], p[1], p[0], p[1]];
          setGeom(cam, g);
        }
        canvas.setPointerCapture(event.pointerId);
      });
      canvas.addEventListener("pointermove", event => {
        if (!dragging) return;
        const cam = dragging.cam;
        const g = structuredClone(geom(cam));
        if (!g) return;
        const p = normFromEvent(canvas, event);
        if (tool === "line" || dragging.handle.startsWith("line")) {
          const idx = dragging.handle === "line0" ? 0 : 2;
          g.line[idx] = p[0]; g.line[idx + 1] = p[1];
        } else {
          const key = dragging.handle.startsWith("reflection") || tool === "reflection" ? "reflection_zone" : "roi";
          const idx = dragging.handle.endsWith("0") ? 0 : 2;
          const box = g[key] || [dragging.start[0], dragging.start[1], p[0], p[1]];
          box[idx] = p[0]; box[idx + 1] = p[1];
          g[key] = [Math.min(box[0], box[2]), Math.min(box[1], box[3]), Math.max(box[0], box[2]), Math.max(box[1], box[3])];
        }
        setGeom(cam, g);
      });
      canvas.addEventListener("pointerup", async () => {
        dragging = null;
        await saveGeometry();
      });
    }

    function drawAll() {
      document.querySelectorAll(".calibration").forEach(canvas => {
        const tile = canvas.closest(".tile");
        const cam = tile.dataset.camera;
        const tileRect = canvas.getBoundingClientRect();
        const imgRect = imageRect(canvas);
        const rect = { width: imgRect.width, height: imgRect.height };
        const dpr = window.devicePixelRatio || 1;
        canvas.width = Math.max(1, Math.round(tileRect.width * dpr));
        canvas.height = Math.max(1, Math.round(tileRect.height * dpr));
        const ctx = canvas.getContext("2d");
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, tileRect.width, tileRect.height);
        ctx.translate(imgRect.left - tileRect.left, imgRect.top - tileRect.top);
        const g = geom(cam);
        if (!g) return;
        drawBox(ctx, g.roi, rect, "rgba(91,167,255,0.95)", "rgba(91,167,255,0.10)");
        if (g.reflection_zone) drawBox(ctx, g.reflection_zone, rect, "rgba(255,93,115,0.85)", "rgba(255,93,115,0.10)");
        drawLine(ctx, g.line, rect, cam === selected ? "#29c7b8" : "rgba(41,199,184,0.62)", g.enter_direction || 1);
      });
    }

    function drawBox(ctx, b, rect, stroke, fill) {
      const x = b[0] * rect.width, y = b[1] * rect.height;
      const w = (b[2] - b[0]) * rect.width, h = (b[3] - b[1]) * rect.height;
      ctx.fillStyle = fill; ctx.strokeStyle = stroke; ctx.lineWidth = 2;
      ctx.fillRect(x, y, w, h); ctx.strokeRect(x, y, w, h);
      drawHandle(ctx, x, y, stroke); drawHandle(ctx, x + w, y + h, stroke);
    }

    function drawLine(ctx, l, rect, stroke, enterDirection = 1) {
      const x1 = l[0] * rect.width, y1 = l[1] * rect.height;
      const x2 = l[2] * rect.width, y2 = l[3] * rect.height;
      ctx.strokeStyle = stroke; ctx.lineWidth = 3; ctx.lineCap = "round";
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      drawHandle(ctx, x1, y1, stroke); drawHandle(ctx, x2, y2, stroke);
      drawEntryArrow(ctx, x1, y1, x2, y2, enterDirection, stroke);
    }

    function drawEntryArrow(ctx, x1, y1, x2, y2, enterDirection, stroke) {
      const dx = x2 - x1, dy = y2 - y1;
      const len = Math.hypot(dx, dy);
      if (len < 8) return;
      const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
      const dir = enterDirection >= 0 ? 1 : -1;
      const nx = (-dy / len) * dir;
      const ny = (dx / len) * dir;
      const size = Math.max(22, Math.min(42, len * 0.18));
      const sx = mx - nx * size * 0.35, sy = my - ny * size * 0.35;
      const ex = mx + nx * size, ey = my + ny * size;
      ctx.save();
      ctx.strokeStyle = stroke;
      ctx.fillStyle = stroke;
      ctx.lineWidth = 3;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.lineTo(ex, ey);
      ctx.stroke();
      const angle = Math.atan2(ey - sy, ex - sx);
      const head = 10;
      ctx.beginPath();
      ctx.moveTo(ex, ey);
      ctx.lineTo(ex - head * Math.cos(angle - Math.PI / 6), ey - head * Math.sin(angle - Math.PI / 6));
      ctx.lineTo(ex - head * Math.cos(angle + Math.PI / 6), ey - head * Math.sin(angle + Math.PI / 6));
      ctx.closePath();
      ctx.fill();
      ctx.restore();
    }

    function drawHandle(ctx, x, y, color) {
      ctx.fillStyle = "#0b1017"; ctx.strokeStyle = color; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    }

    async function poll() {
      try {
        const res = await fetch("/api/state", { cache: "no-store" });
        const next = await res.json();
        const nextCameras = Object.keys(next.cameras || {}).sort();
        const changedCameras = nextCameras.length && nextCameras.join("|") !== cameras.join("|");
        if (dirty || dragging) {
          next.config = state.config;
        }
        state = next;
        if (!state.config.geometries) state.config.geometries = {};
        if (changedCameras) {
          cameras = nextCameras;
          makeFeeds();
        }
        updateUi();
      } catch (err) {
        statusText.textContent = "Disconnected";
      }
    }

    function updateUi() {
      const cams = state.cameras || {};
      const exitsVisible = showExits();
      const modelLabel = state.model_size === "x" ? "YOLOX-Tiny OpenVINO" : `YOLOv8${state.model_size || "n"}`;
      statusText.textContent = `GPU ${state.device || "0"} - ${modelLabel} - ${state.foot_source || "center"} - ${state.quality || "sub"}`;
      footSource.value = state.foot_source || "center";
      modelSelect.value = state.model_size || "x";
      qualitySelect.value = state.quality || "sub";
      confInput.value = state.confidence ?? "";
      deviceInput.value = state.device || "0";
      renderStoreSelect();
      counters.innerHTML = "";
      let total = 0;
      let totalExits = 0;
      for (const cam of cameras) {
        const c = cams[cam] || {};
        total += c.entry_count || 0;
        totalExits += c.exit_count || 0;
        const div = document.createElement("div");
        div.className = "counter";
        div.innerHTML = exitsVisible
          ? `<span>${cam.replace("cam_", "Camera ")} in/out</span><b>${c.entry_count || 0}/${c.exit_count || 0}</b>`
          : `<span>${cam.replace("cam_", "Camera ")} entries</span><b>${c.entry_count || 0}</b>`;
        counters.appendChild(div);
        const tile = document.querySelector(`.tile[data-camera="${cam}"]`);
        if (tile) {
          tile.querySelector(".tile-count").textContent = c.entry_count || 0;
          tile.querySelector(".tile-exit-count").textContent = c.exit_count || 0;
          tile.querySelectorAll(".tile-exit-count").forEach(el => el.classList.toggle("hidden-exits", !exitsVisible));
          tile.querySelectorAll(".tile-exit-label").forEach(el => el.classList.toggle("hidden-exits", !exitsVisible));
          const dot = tile.querySelector(".dot");
          dot.className = `dot ${c.running ? "run" : "err"}`;
          const badge = tile.querySelector(".tile-head .badge");
          if (badge && !c.calibrated) badge.title = "Draw and save a line plus ROI to enable counting.";
        }
      }
      const totalDiv = document.createElement("div");
      totalDiv.className = "counter";
      totalDiv.innerHTML = exitsVisible
        ? `<span>Total in/out</span><b>${total}/${totalExits}</b>`
        : `<span>Total entries</span><b>${total}</b>`;
      counters.prepend(totalDiv);
      if (exitsVisible) {
        const netDiv = document.createElement("div");
        netDiv.className = "counter exit-ui";
        netDiv.innerHTML = `<span>Net inside</span><b>${Math.max(0, total - totalExits)}</b>`;
        counters.appendChild(netDiv);
      }
      const sales = Number(state.sales_count || 0);
      const conversion = total > 0 ? (sales / total) * 100 : 0;
      salesInput.value = sales;
      conversionInput.value = `${conversion.toFixed(1)}%`;
      entrantsMetric.textContent = total;
      exitsMetric.textContent = totalExits;
      salesMetric.textContent = sales;
      updateCleanStats(total, totalExits, sales, conversion);
      applyExitVisibility();
      const events = (state.events || []).filter(event => exitsVisible || (event.direction || "entry") !== "exit").slice(-80).reverse();
      eventList.innerHTML = events.length ? "" : `<div class="empty">No events yet</div>`;
      for (const event of events) {
        const row = document.createElement("div");
        row.className = "event";
        const direction = event.direction || "entry";
        const count = direction === "exit" ? event.exit_count_camera : event.entry_count_camera;
        const cameraLabel = String(event.camera_id || "all").startsWith("cam_") ? String(event.camera_id).replace("cam_", "Camera ") : String(event.camera_id || "all");
        row.innerHTML = `<strong>${direction.toUpperCase()}</strong><span>${cameraLabel} #${count || 0}</span><span>track ${event.tracker_id}</span><span>${Number(event.time_seconds).toFixed(1)}s</span>`;
        eventList.appendChild(row);
      }
      drawAll();
    }

    function updateCleanStats(totalEntries, totalExits, sales, conversion) {
      if (!cleanModal.classList.contains("open")) return;
      if (totalEntries === undefined || totalExits === undefined || sales === undefined || conversion === undefined) {
        const cams = state.cameras || {};
        totalEntries = cameras.reduce((sum, cam) => sum + (cams[cam]?.entry_count || 0), 0);
        totalExits = cameras.reduce((sum, cam) => sum + (cams[cam]?.exit_count || 0), 0);
        sales = Number(state.sales_count || 0);
        conversion = totalEntries > 0 ? (sales / totalEntries) * 100 : 0;
      }
      cleanEntries.textContent = totalEntries;
      cleanExits.textContent = totalExits;
      cleanNet.textContent = Math.max(0, totalEntries - totalExits);
      cleanSales.textContent = sales;
      cleanConversion.textContent = `${conversion.toFixed(1)}%`;
    }

    async function saveGeometry() {
      saveState.textContent = "Saving";
      const body = {
        geometries: state.config.geometries,
        foot_source: footSource.value,
        model_size: modelSelect.value,
        confidence: Number(confInput.value || state.confidence || 0.42),
        quality: qualitySelect.value
      };
      const res = await fetch("/api/geometry", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      const data = await res.json();
      if (data.ok) dirty = false;
      saveState.textContent = data.ok ? "Saved" : (data.error || "Save failed");
      setTimeout(() => saveState.textContent = "", 1800);
      await poll();
    }

    async function resetCounters() {
      await fetch("/api/reset", { method: "POST" });
      await poll();
    }

    function openCountEditor() {
      const cams = state.cameras || {};
      countSaveState.textContent = "";
      countFields.innerHTML = cameras.map(cam => {
        const c = cams[cam] || {};
        const entries = Number(c.entry_count || 0);
        const exits = Number(c.exit_count || 0);
        const net = Math.max(0, entries - exits);
        return `
          <div class="count-editor-row" data-camera="${escapeAttr(cam)}">
            <strong>${escapeHtml(cam.replace("cam_", "Camera "))}</strong>
            <div class="field"><label>Entries</label><input data-field="entry_count" type="number" min="0" step="1" value="${entries}"></div>
            <div class="field"><label>Exits</label><input data-field="exit_count" type="number" min="0" step="1" value="${exits}"></div>
            <div class="field"><label>Net Inside</label><input data-field="net_inside" type="number" min="0" step="1" value="${net}"></div>
          </div>`;
      }).join("");
      countModal.classList.add("open");
    }

    function closeCountEditor() {
      countModal.classList.remove("open");
    }

    async function saveCountEditor() {
      const payload = { cameras: {} };
      countFields.querySelectorAll(".count-editor-row").forEach(row => {
        const cam = row.dataset.camera;
        payload.cameras[cam] = {};
        row.querySelectorAll("input").forEach(input => {
          payload.cameras[cam][input.dataset.field] = Number(input.value || 0);
        });
      });
      countSaveState.textContent = "Applying";
      const res = await fetch("/api/counts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!data.ok) {
        countSaveState.textContent = data.error || "Correction failed";
        return;
      }
      closeCountEditor();
      await poll();
    }

    async function saveSettings() {
      const body = {
        foot_source: footSource.value,
        model_size: modelSelect.value,
        confidence: Number(confInput.value || state.confidence || 0.42),
        quality: qualitySelect.value,
        sales_count: Number(salesInput.value || 0),
        selected_store_id: storeSelect.value || state.selected_store_id || "store_1",
        stores: normalizedStores()
      };
      await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      await poll();
    }

    function currentStores() {
      const stores = Array.isArray(state.stores) && state.stores.length ? state.stores : [{
        store_id: "store_1",
        name: "Main Store",
        location: "",
        manager: "",
        camera_id: "cam_501"
      }];
      state.stores = stores;
      if (!state.selected_store_id) state.selected_store_id = stores[0].store_id;
      return stores;
    }

    function normalizedStores() {
      return currentStores().map((store, idx) => ({
        store_id: String(store.store_id || `store_${idx + 1}`),
        name: String(store.name || `Store ${idx + 1}`),
        location: String(store.location || ""),
        manager: String(store.manager || ""),
        camera_id: String(store.camera_id || "cam_501")
      }));
    }

    function renderStoreSelect() {
      const stores = currentStores();
      const selectedValue = storeSelect.value || state.selected_store_id || stores[0].store_id;
      storeSelect.innerHTML = stores.map(store => `<option value="${escapeHtml(store.store_id)}">${escapeHtml(store.name || store.store_id)}</option>`).join("");
      storeSelect.value = stores.some(store => store.store_id === selectedValue) ? selectedValue : stores[0].store_id;
    }

    function renderStoreModal() {
      const stores = currentStores();
      storeList.innerHTML = "";
      for (const [idx, store] of stores.entries()) {
        const card = document.createElement("div");
        card.className = `store-card ${store.store_id === state.selected_store_id ? "active" : ""}`;
        card.innerHTML = `
          <div class="store-card-head">
            <strong>${escapeHtml(store.name || `Store ${idx + 1}`)}</strong>
            <button data-action="select">Use Store</button>
          </div>
          <div class="row">
            <div class="field"><label>Store Name</label><input data-field="name" value="${escapeAttr(store.name || "")}"></div>
            <div class="field"><label>Store ID</label><input data-field="store_id" value="${escapeAttr(store.store_id || `store_${idx + 1}`)}"></div>
          </div>
          <div class="row">
            <div class="field"><label>Location</label><input data-field="location" value="${escapeAttr(store.location || "")}"></div>
            <div class="field"><label>Manager</label><input data-field="manager" value="${escapeAttr(store.manager || "")}"></div>
          </div>
          <div class="row">
            <div class="field"><label>Camera</label><input data-field="camera_id" value="${escapeAttr(store.camera_id || "cam_501")}"></div>
            <div class="field"><label>Action</label><button data-action="remove">Remove</button></div>
          </div>`;
        card.querySelectorAll("input").forEach(input => {
          const previousStoreId = store.store_id;
          input.oninput = () => {
            const field = input.dataset.field;
            const wasSelected = state.selected_store_id === previousStoreId || state.selected_store_id === store.store_id;
            store[field] = input.value;
            if (field === "store_id" && wasSelected) {
              state.selected_store_id = input.value;
            }
          };
        });
        card.querySelector('[data-action="select"]').onclick = () => {
          state.selected_store_id = store.store_id;
          renderStoreModal();
        };
        card.querySelector('[data-action="remove"]').onclick = () => {
          if (stores.length <= 1) return;
          stores.splice(idx, 1);
          if (!stores.some(item => item.store_id === state.selected_store_id)) state.selected_store_id = stores[0].store_id;
          renderStoreModal();
        };
        storeList.appendChild(card);
      }
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
    }

    function escapeAttr(value) {
      return escapeHtml(value);
    }

    document.querySelectorAll(".tool").forEach(btn => {
      btn.onclick = () => {
        tool = btn.dataset.tool;
        document.querySelectorAll(".tool").forEach(x => x.classList.toggle("active", x === btn));
      };
    });
    document.querySelectorAll(".collapse-panel-btn").forEach(btn => {
      btn.onclick = event => {
        event.stopPropagation();
        togglePanel(btn.dataset.collapse);
      };
    });
    document.getElementById("saveBtn").onclick = saveGeometry;
    document.getElementById("resetBtn").onclick = resetCounters;
    document.getElementById("cleanViewBtn").onclick = openCleanView;
    document.getElementById("closeCleanBtn").onclick = closeCleanView;
    document.getElementById("closeCleanFooterBtn").onclick = closeCleanView;
    cameraModeBtn.onclick = () => {
      localStorage.setItem("entranceShowAllCameras", showAllCameras() ? "0" : "1");
      applyCameraMode();
    };
    exitToggleBtn.onclick = () => {
      localStorage.setItem("entranceShowExits", showExits() ? "0" : "1");
      applyExitVisibility();
      updateUi();
    };
    themeBtn.onclick = () => applyTheme(document.body.classList.contains("light") ? "dark" : "light");
    document.getElementById("storesBtn").onclick = () => {
      renderStoreModal();
      storesModal.classList.add("open");
    };
    document.getElementById("closeStoresBtn").onclick = () => storesModal.classList.remove("open");
    document.getElementById("closeCountBtn").onclick = closeCountEditor;
    document.getElementById("cancelCountBtn").onclick = closeCountEditor;
    document.getElementById("saveCountBtn").onclick = saveCountEditor;
    document.getElementById("addStoreBtn").onclick = () => {
      const stores = currentStores();
      stores.push({
        store_id: `store_${stores.length + 1}`,
        name: `Store ${stores.length + 1}`,
        location: "",
        manager: "",
        camera_id: "cam_501"
      });
      renderStoreModal();
    };
    document.getElementById("saveStoresBtn").onclick = async () => {
      state.stores = normalizedStores();
      if (!state.stores.some(store => store.store_id === state.selected_store_id)) state.selected_store_id = state.stores[0].store_id;
      storesModal.classList.remove("open");
      await saveSettings();
    };
    document.getElementById("flipBtn").onclick = async () => {
      const g = structuredClone(geom(selected));
      if (!g) return;
      g.enter_direction = -(g.enter_direction || 1);
      setGeom(selected, g);
      await saveGeometry();
    };
    document.getElementById("clearGlassBtn").onclick = () => {
      const g = structuredClone(geom(selected));
      if (!g) return;
      g.reflection_zone = null;
      setGeom(selected, g);
    };
    footSource.onchange = saveSettings;
    modelSelect.onchange = saveSettings;
    qualitySelect.onchange = saveSettings;
    confInput.onchange = saveSettings;
    salesInput.onchange = saveSettings;
    storeSelect.onchange = saveSettings;
    window.addEventListener("resize", drawAll);
    window.addEventListener("keydown", event => {
      if (event.ctrlKey && event.altKey && event.code === "KeyC") {
        event.preventDefault();
        openCountEditor();
      }
    });

    applyTheme(localStorage.getItem("entranceTheme") || "dark");
    applyExitVisibility();
    applyCollapsedPanels();
    makeFeeds();
    poll();
    setInterval(poll, 650);
  </script>
</body>
</html>
"""
