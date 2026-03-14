# DevGlobe Zed Extension — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Zed editor extension that sends DevGlobe heartbeats via an MCP context server so Zed users appear on the devglobe.xyz 3D globe.

**Architecture:** Rust WASM stub registers an MCP context server. The server is a Node.js process that monitors file changes via `fs.watch`, detects language by file extension, resolves geolocation, and POSTs heartbeats to Supabase every 30 seconds.

**Tech Stack:** Rust (zed_extension_api), Node.js 20+ (zero npm dependencies), Supabase RPC

**Spec:** `docs/superpowers/specs/2026-03-14-devglobe-zed-extension-design.md`

**Target repo:** Fork of github.com/Nako0/devglobe-extension (PR to upstream)

---

## Chunk 1: Project Setup + Language Map

### Task 1: Fork repo and create zed-extension directory

**Files:**
- Create: `zed-extension/extension.toml`
- Create: `zed-extension/Cargo.toml`
- Create: `zed-extension/src/lib.rs`

- [ ] **Step 1: Fork and clone the repo**

```bash
gh repo fork Nako0/devglobe-extension --clone
cd devglobe-extension
git checkout -b feat/zed-extension
```

- [ ] **Step 2: Create extension.toml**

```toml
id = "devglobe"
name = "DevGlobe"
version = "0.1.0"
schema_version = 1
authors = ["DevGlobe Contributors"]
description = "Show your live coding presence on the DevGlobe world map"
repository = "https://github.com/Nako0/devglobe-extension"

[capabilities]
process = true
```

- [ ] **Step 3: Create Cargo.toml**

```toml
[package]
name = "devglobe-zed"
version = "0.1.0"
edition = "2021"

[lib]
crate-type = ["cdylib"]

[dependencies]
zed_extension_api = "0.5"
```

- [ ] **Step 4: Create src/lib.rs**

```rust
use zed_extension_api as zed;

struct DevGlobeExtension;

impl zed::Extension for DevGlobeExtension {
    fn new() -> Self {
        Self
    }
}

zed::register_extension!(DevGlobeExtension);
```

- [ ] **Step 5: Commit**

```bash
git add zed-extension/
git commit -m "feat(zed): scaffold Rust WASM extension stub"
```

### Task 2: Create Node.js server scaffold + language map

**Files:**
- Create: `zed-extension/server/package.json`
- Create: `zed-extension/server/languages.js`

- [ ] **Step 1: Create package.json**

```json
{
  "name": "devglobe-zed-server",
  "version": "0.1.0",
  "private": true,
  "description": "DevGlobe MCP context server for Zed",
  "main": "devglobe-server.js",
  "engines": {
    "node": ">=20.0.0"
  }
}
```

- [ ] **Step 2: Create languages.js**

Build the language map from the VS Code extension's `language.ts`. The file exports a single function `getLanguageFromExt(ext)`.

```javascript
'use strict';

const LANG_MAP = {
  '.js': 'JavaScript', '.mjs': 'JavaScript', '.cjs': 'JavaScript',
  '.ts': 'TypeScript', '.tsx': 'TypeScript', '.mts': 'TypeScript',
  '.jsx': 'JavaScript',
  '.py': 'Python', '.pyw': 'Python', '.pyi': 'Python',
  '.rs': 'Rust',
  '.go': 'Go',
  '.java': 'Java',
  '.kt': 'Kotlin', '.kts': 'Kotlin',
  '.c': 'C', '.h': 'C',
  '.cpp': 'C++', '.cxx': 'C++', '.cc': 'C++', '.hpp': 'C++',
  '.cs': 'C#',
  '.rb': 'Ruby', '.erb': 'Ruby',
  '.php': 'PHP',
  '.swift': 'Swift',
  '.dart': 'Dart',
  '.lua': 'Lua',
  '.r': 'R', '.R': 'R',
  '.scala': 'Scala',
  '.zig': 'Zig',
  '.nim': 'Nim',
  '.ex': 'Elixir', '.exs': 'Elixir',
  '.erl': 'Erlang',
  '.hs': 'Haskell',
  '.ml': 'OCaml', '.mli': 'OCaml',
  '.clj': 'Clojure', '.cljs': 'Clojure',
  '.v': 'V',
  '.sol': 'Solidity',
  '.sql': 'SQL',
  '.sh': 'Shell', '.bash': 'Shell', '.zsh': 'Shell',
  '.ps1': 'PowerShell',
  '.html': 'HTML', '.htm': 'HTML',
  '.css': 'CSS', '.scss': 'SCSS', '.sass': 'Sass', '.less': 'Less',
  '.json': 'JSON', '.jsonc': 'JSON',
  '.yaml': 'YAML', '.yml': 'YAML',
  '.toml': 'TOML',
  '.xml': 'XML',
  '.md': 'Markdown', '.mdx': 'Markdown',
  '.vue': 'Vue',
  '.svelte': 'Svelte',
  '.astro': 'Astro',
  '.tf': 'Terraform', '.hcl': 'HCL',
  '.dockerfile': 'Docker', '.Dockerfile': 'Docker',
  '.graphql': 'GraphQL', '.gql': 'GraphQL',
  '.proto': 'Protocol Buffers',
  '.wasm': 'WebAssembly',
};

function getLanguageFromExt(ext) {
  if (!ext) return null;
  const lower = ext.toLowerCase();
  if (LANG_MAP[lower]) return LANG_MAP[lower];
  // Check original case (for .R vs .r)
  if (LANG_MAP[ext]) return LANG_MAP[ext];
  // Fallback: capitalize without dot
  if (lower.length > 1) return lower.slice(1).charAt(0).toUpperCase() + lower.slice(2);
  return null;
}

module.exports = { getLanguageFromExt, LANG_MAP };
```

- [ ] **Step 3: Verify languages.js loads without error**

```bash
node -e "const l = require('./zed-extension/server/languages.js'); console.log(l.getLanguageFromExt('.rs'), l.getLanguageFromExt('.py'), l.getLanguageFromExt('.unknown'))"
```

Expected: `Rust Python Nknown`

- [ ] **Step 4: Commit**

```bash
git add zed-extension/server/
git commit -m "feat(zed): add Node.js server scaffold and language map"
```

---

## Chunk 2: Core Server Modules (geo, git, activity, heartbeat)

### Task 3: Geolocation module

**Files:**
- Create: `zed-extension/server/geo.js`

- [ ] **Step 1: Create geo.js**

```javascript
'use strict';

const GEO_CACHE_TTL = 60 * 60 * 1000; // 1 hour
const GEO_TIMEOUT = 10_000;

let _cache = null;
let _cacheTime = 0;

const GEO_APIS = [
  'https://free.freeipapi.com/api/json',
  'https://ipapi.co/json/',
];

async function fetchWithTimeout(url, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: controller.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

async function fetchGeolocation() {
  const now = Date.now();
  if (_cache && (now - _cacheTime) < GEO_CACHE_TTL) return _cache;

  for (const url of GEO_APIS) {
    try {
      const data = await fetchWithTimeout(url, GEO_TIMEOUT);
      const city = data.cityName || data.city || null;
      const lat = data.latitude || data.lat || null;
      const lng = data.longitude || data.lon || null;
      const country = data.countryCode || data.country_code || null;
      if (lat != null && lng != null) {
        _cache = { city, lat, lng, country };
        _cacheTime = now;
        return _cache;
      }
    } catch {
      // try next API
    }
  }
  return null;
}

module.exports = { fetchGeolocation };
```

- [ ] **Step 2: Smoke test**

```bash
node -e "const g = require('./zed-extension/server/geo.js'); g.fetchGeolocation().then(r => console.log(r)).catch(e => console.error(e))"
```

Expected: Object with city, lat, lng, country (or null if offline)

- [ ] **Step 3: Commit**

```bash
git add zed-extension/server/geo.js
git commit -m "feat(zed): add geolocation module with cache and fallback"
```

### Task 4: Git detection module

**Files:**
- Create: `zed-extension/server/git.js`

- [ ] **Step 1: Create git.js**

```javascript
'use strict';

const { execFile } = require('child_process');

const GIT_CACHE_TTL = 5 * 60 * 1000; // 5 minutes
let _cache = null;
let _cacheTime = 0;
let _cachedCwd = null;

function execFileAsync(cmd, args, opts) {
  return new Promise((resolve) => {
    execFile(cmd, args, { timeout: 5000, ...opts }, (err, stdout) => {
      if (err) resolve(null);
      else resolve(stdout.trim());
    });
  });
}

function parseRepoName(url) {
  if (!url) return null;
  // https://github.com/owner/repo.git or git@github.com:owner/repo.git
  const match = url.match(/[/:]([^/]+\/[^/]+?)(?:\.git)?$/);
  return match ? match[1] : null;
}

async function getRepoName(cwd) {
  const now = Date.now();
  if (_cache && _cachedCwd === cwd && (now - _cacheTime) < GIT_CACHE_TTL) {
    return _cache;
  }

  const url = await execFileAsync('git', ['remote', 'get-url', 'origin'], { cwd });
  const repo = parseRepoName(url);
  _cache = repo;
  _cacheTime = now;
  _cachedCwd = cwd;
  return repo;
}

module.exports = { getRepoName, parseRepoName };
```

- [ ] **Step 2: Smoke test**

```bash
node -e "const g = require('./zed-extension/server/git.js'); console.log(g.parseRepoName('https://github.com/Nako0/devglobe-extension.git'))"
```

Expected: `Nako0/devglobe-extension`

- [ ] **Step 3: Commit**

```bash
git add zed-extension/server/git.js
git commit -m "feat(zed): add git remote detection module"
```

### Task 5: Activity tracker module

**Files:**
- Create: `zed-extension/server/activity.js`

- [ ] **Step 1: Create activity.js**

```javascript
'use strict';

const fs = require('fs');
const path = require('path');
const { getLanguageFromExt } = require('./languages');

const ACTIVITY_TIMEOUT = 60_000; // 1 minute

const IGNORE_DIRS = new Set([
  'node_modules', '.git', 'target', '__pycache__', '.next',
  'dist', 'build', '.cache', '.venv', 'venv',
]);

const IGNORE_EXTS = new Set([
  '.exe', '.dll', '.so', '.dylib', '.o', '.a',
  '.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg',
  '.woff', '.woff2', '.ttf', '.eot',
  '.zip', '.tar', '.gz', '.br',
  '.lock', '.map',
]);

let _lastActivityTime = 0;
let _lastExt = null;
let _watcher = null;

function shouldIgnore(filePath) {
  const parts = filePath.split(path.sep);
  for (const part of parts) {
    if (IGNORE_DIRS.has(part)) return true;
  }
  const ext = path.extname(filePath).toLowerCase();
  return IGNORE_EXTS.has(ext);
}

function startWatching(dir) {
  if (_watcher) return;
  try {
    _watcher = fs.watch(dir, { recursive: true }, (eventType, filename) => {
      if (!filename || shouldIgnore(filename)) return;
      _lastActivityTime = Date.now();
      const ext = path.extname(filename);
      if (ext) _lastExt = ext;
    });
    _watcher.on('error', () => {
      // watcher failed — activity detection disabled
      _watcher = null;
    });
  } catch {
    // fs.watch not supported or permission denied
  }
}

function stopWatching() {
  if (_watcher) {
    _watcher.close();
    _watcher = null;
  }
}

function isActive() {
  return (Date.now() - _lastActivityTime) < ACTIVITY_TIMEOUT;
}

function getLanguage() {
  return getLanguageFromExt(_lastExt);
}

module.exports = { startWatching, stopWatching, isActive, getLanguage };
```

- [ ] **Step 2: Commit**

```bash
git add zed-extension/server/activity.js
git commit -m "feat(zed): add fs.watch activity tracker with ignore patterns"
```

### Task 6: Heartbeat client module

**Files:**
- Create: `zed-extension/server/heartbeat.js`

- [ ] **Step 1: Create heartbeat.js**

```javascript
'use strict';

const SUPABASE_URL = 'https://kzcrtlbspkhlnjillhyz.supabase.co';
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imt6Y3J0bGJzcGtobG5qaWxsaHl6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzI2MzY3NTYsImV4cCI6MjA4ODIxMjc1Nn0.JvJraoxuffHe5VMQu763hROGXNot9XKFY54X6-Ko-bk';
const FETCH_TIMEOUT = 15_000;
const OFFLINE_THRESHOLD = 2;

let _consecutiveFailures = 0;

async function sendHeartbeat(apiKey, language, geo) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT);

  try {
    const res = await fetch(`${SUPABASE_URL}/rest/v1/rpc/heartbeat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'apikey': SUPABASE_ANON_KEY,
        'Authorization': `Bearer ${SUPABASE_ANON_KEY}`,
      },
      signal: controller.signal,
      body: JSON.stringify({
        p_key: apiKey,
        p_lang: language || 'Unknown',
        p_city: geo ? geo.city : null,
        p_lat: geo ? geo.lat : null,
        p_lng: geo ? geo.lng : null,
        p_editor: 'Zed',
        p_anonymous: false,
        p_share_repo: false,
        p_repo: null,
      }),
    });

    if (res.ok) {
      _consecutiveFailures = 0;
      const data = await res.json();
      return { ok: true, todaySeconds: data?.today_seconds ?? 0 };
    }
    _consecutiveFailures++;
    return { ok: false, error: `HTTP ${res.status}` };
  } catch (err) {
    _consecutiveFailures++;
    return { ok: false, error: err.message };
  } finally {
    clearTimeout(timer);
  }
}

function isOffline() {
  return _consecutiveFailures >= OFFLINE_THRESHOLD;
}

module.exports = { sendHeartbeat, isOffline };
```

- [ ] **Step 2: Commit**

```bash
git add zed-extension/server/heartbeat.js
git commit -m "feat(zed): add Supabase heartbeat client with offline detection"
```

---

## Chunk 3: Main Server + README + PR

### Task 7: Main server entry point

**Files:**
- Create: `zed-extension/server/devglobe-server.js`

- [ ] **Step 1: Create devglobe-server.js**

```javascript
'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');
const { startWatching, stopWatching, isActive, getLanguage } = require('./activity');
const { sendHeartbeat, isOffline } = require('./heartbeat');
const { fetchGeolocation } = require('./geo');

const HEARTBEAT_INTERVAL = 30_000;

function readApiKey() {
  // 1. Environment variable
  const envKey = process.env.DEVGLOBE_API_KEY;
  if (envKey && envKey.startsWith('devglobe_')) return envKey.trim();

  // 2. File ~/.devglobe/api_key
  const keyPath = path.join(os.homedir(), '.devglobe', 'api_key');
  try {
    const key = fs.readFileSync(keyPath, 'utf-8').trim();
    if (key.startsWith('devglobe_')) return key;
  } catch {
    // file not found
  }
  return null;
}

async function main() {
  const apiKey = readApiKey();
  if (!apiKey) {
    console.error('[DevGlobe] No API key found. Set DEVGLOBE_API_KEY or create ~/.devglobe/api_key');
    // Keep process alive but don't send heartbeats — Zed expects the MCP server to stay running
    return;
  }

  const cwd = process.cwd();
  console.error(`[DevGlobe] Starting heartbeat tracker for ${cwd}`);

  // Start file watcher
  startWatching(cwd);

  // Initial geolocation fetch
  let geo = await fetchGeolocation();
  if (geo) {
    console.error(`[DevGlobe] Location: ${geo.city} (${geo.lat}, ${geo.lng})`);
  } else {
    console.error('[DevGlobe] Geolocation failed — heartbeats will be skipped until resolved');
  }

  // Heartbeat loop
  const timer = setInterval(async () => {
    if (!isActive()) return;

    // Refresh geo if cache expired
    if (!geo) geo = await fetchGeolocation();
    if (!geo) return; // still no location — skip

    const language = getLanguage();
    const result = await sendHeartbeat(apiKey, language, geo);

    if (result.ok) {
      console.error(`[DevGlobe] Heartbeat sent: ${language || 'Unknown'} (${Math.floor(result.todaySeconds / 60)}min today)`);
    } else if (isOffline()) {
      console.error(`[DevGlobe] Offline: ${result.error}`);
    }
  }, HEARTBEAT_INTERVAL);

  // Graceful shutdown
  const shutdown = () => {
    clearInterval(timer);
    stopWatching();
    console.error('[DevGlobe] Shutdown.');
    process.exit(0);
  };
  process.on('SIGTERM', shutdown);
  process.on('SIGINT', shutdown);

  // MCP server: read stdin to keep process alive (Zed expects stdio communication)
  // We don't implement MCP protocol — just keep the process running
  process.stdin.resume();
  process.stdin.on('end', shutdown);
}

main().catch((err) => {
  console.error(`[DevGlobe] Fatal: ${err.message}`);
  process.exit(1);
});
```

- [ ] **Step 2: Verify server starts and reads API key**

```bash
cd devglobe-extension
DEVGLOBE_API_KEY=devglobe_test node zed-extension/server/devglobe-server.js &
sleep 2
kill %1
```

Expected: `[DevGlobe] Starting heartbeat tracker for ...` then `[DevGlobe] Shutdown.`

- [ ] **Step 3: Commit**

```bash
git add zed-extension/server/devglobe-server.js
git commit -m "feat(zed): add main server entry point with heartbeat loop"
```

### Task 8: Update extension.toml to register MCP server

**Files:**
- Modify: `zed-extension/extension.toml`

- [ ] **Step 1: Add context_server declaration**

Add to extension.toml:

```toml
[[context_servers]]
id = "devglobe-heartbeat"
```

And update `src/lib.rs` to provide the server command:

```rust
use zed_extension_api as zed;

struct DevGlobeExtension;

impl zed::Extension for DevGlobeExtension {
    fn new() -> Self {
        Self
    }

    fn context_server_command(
        &mut self,
        _server_id: &zed::ContextServerId,
        _project: &zed::Project,
    ) -> zed::Result<zed::Command> {
        Ok(zed::Command {
            command: "node".to_string(),
            args: vec![
                format!("{}/server/devglobe-server.js", env!("CARGO_MANIFEST_DIR")),
            ],
            env: Default::default(),
        })
    }
}

zed::register_extension!(DevGlobeExtension);
```

- [ ] **Step 2: Commit**

```bash
git add zed-extension/extension.toml zed-extension/src/lib.rs
git commit -m "feat(zed): register MCP context server in extension manifest"
```

### Task 9: Create README

**Files:**
- Create: `zed-extension/README.md`

- [ ] **Step 1: Create README.md**

```markdown
# DevGlobe — Zed Extension

Show your live coding presence on the [DevGlobe](https://devglobe.xyz) world map from Zed.

## Requirements

- [Zed](https://zed.dev) editor
- [Node.js](https://nodejs.org) 20 or later
- A DevGlobe account and API key from [devglobe.xyz](https://devglobe.xyz)

## Setup

1. Install the DevGlobe extension from the Zed extensions marketplace
2. Save your API key:

```bash
mkdir -p ~/.devglobe
echo "devglobe_YOUR_KEY_HERE" > ~/.devglobe/api_key
```

3. Open a project in Zed and start coding — you'll appear on the globe within 30 seconds

## How It Works

The extension launches a lightweight Node.js process that:
- Monitors file changes in your workspace to detect coding activity
- Detects programming language from file extensions
- Sends a heartbeat every 30 seconds while you're actively coding
- Pauses after 60 seconds of inactivity

## Privacy

- No source code, file contents, or keystrokes are collected
- Only language name, city-level location, and editor name are sent
- Geolocation is resolved via your IP using third-party APIs (freeipapi.com, ipapi.co)
- See [PRIVACY.md](../PRIVACY.md) for full details

## Configuration

| Method | Description |
|--------|-------------|
| `~/.devglobe/api_key` | Plain text file with your API key |
| `DEVGLOBE_API_KEY` env var | Alternative: set in your shell profile |
```

- [ ] **Step 2: Commit**

```bash
git add zed-extension/README.md
git commit -m "docs(zed): add setup and usage README"
```

### Task 10: Push and create PR

- [ ] **Step 1: Push branch**

```bash
git push -u origin feat/zed-extension
```

- [ ] **Step 2: Create PR**

```bash
gh pr create --repo Nako0/devglobe-extension \
  --title "feat: add Zed editor extension" \
  --body "$(cat <<'EOF'
## Summary

Adds a DevGlobe extension for the Zed editor, resolving #1.

**Architecture:** Since Zed extensions are Rust/WASM sandboxed (no HTTP, timers, or file events), this uses Zed's MCP context server feature to launch a Node.js process that handles heartbeat tracking outside the sandbox.

**Components:**
- Rust WASM stub (registers MCP server with Zed)
- Node.js heartbeat server with:
  - `fs.watch` activity detection + language inference by file extension
  - Supabase RPC heartbeat client (same endpoint/payload as VS Code extension)
  - Geolocation with 1h cache (freeipapi.com + ipapi.co fallback)
  - Git remote detection for future repo sharing

**Scope (MVP):**
- Heartbeat + language detection + geolocation
- API key via `~/.devglobe/api_key` or `DEVGLOBE_API_KEY` env var
- Zero npm dependencies, Node.js 20+ required

**Not included (future PRs):**
- Anonymous mode, status messages, share repo toggle
- UI (sidebar, notifications)
- Retry/backoff on network errors

## Test plan
- [ ] Install as dev extension in Zed
- [ ] Set API key in `~/.devglobe/api_key`
- [ ] Open a project, edit files
- [ ] Verify user appears on devglobe.xyz within 30 seconds
- [ ] Stop editing, verify disappears after ~90 seconds (60s timeout + 30s interval)
- [ ] Verify correct language shown for .rs, .py, .ts files

Closes #1
EOF
)"
```

- [ ] **Step 3: Post result**

Return the PR URL to the user.
