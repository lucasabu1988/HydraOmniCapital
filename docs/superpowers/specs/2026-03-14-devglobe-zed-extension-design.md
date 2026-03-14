# DevGlobe Extension for Zed — Design Spec

**Date:** 2026-03-14
**Status:** Approved
**Target repo:** github.com/Nako0/devglobe-extension
**Issue:** #1 (Extension for Zed)

## Problem

Zed is a fast-growing editor with no DevGlobe support. Issue #1 requests a Zed extension so Zed users can appear on the DevGlobe 3D globe while coding.

## Constraints

Zed extensions are Rust compiled to WASM and sandboxed. The sandbox does NOT support:
- Editor activity events (no onDidChangeTextDocument)
- Timers/intervals (no setInterval)
- Arbitrary HTTP requests
- Custom UI (no sidebars, no webviews)

This makes a direct port of the VS Code extension impossible.

## Solution: MCP Context Server

Zed supports MCP (Model Context Protocol) servers — external processes launched by the extension that run outside the WASM sandbox. The DevGlobe Zed extension uses this mechanism:

1. **Rust extension** (~20 lines) — registers the MCP context server in extension.toml
2. **Node.js MCP server** (~300 lines) — runs all heartbeat logic as a long-running process

### Architecture

```
Zed Editor
  extension.toml (declares MCP context server)
    Launches: node devglobe-server.js
      fs.watch(cwd) detects activity + language by file extension
      setInterval(30s) POST heartbeat to Supabase RPC
      Geolocation (freeipapi.com, cached 1h)
      Git remote detection (execFile: git remote get-url origin)
```

### Data Flow

```
File saved in Zed
  fs.watch fires event
  activity.js records timestamp + file extension
  language map resolves extension to language name
  heartbeat timer fires (every 30s)
  checks: last_activity < 60s ago?
    YES: POST /rest/v1/rpc/heartbeat to Supabase
    NO: skip (user idle, no heartbeat sent)
```

## Components

### 1. Rust Extension (stub)

- extension.toml: declares MCP context server pointing to node server/devglobe-server.js
- Cargo.toml: minimal Rust WASM boilerplate
- src/lib.rs: empty Extension trait implementation

The Rust side does nothing — it exists only to register the MCP server with Zed.

### 2. Activity Tracker (server/activity.js)

- fs.watch(process.cwd(), { recursive: true }) monitors workspace
- Ignore patterns: node_modules/, .git/, target/, __pycache__/, binary extensions
- Records lastActivityTime and lastFileExtension on each change
- Exports: isActive() (activity within 60s), getLanguage() (from last extension)

### 3. Language Detection (server/languages.js)

- Map of file extension to display name (reuse from VS Code extension's language.ts)
- Examples: .rs = Rust, .py = Python, .ts = TypeScript
- Fallback: capitalize extension (.zig = Zig)
- ~50 most common languages, expandable

### 4. Heartbeat Client (server/heartbeat.js)

- POST to `SUPABASE_URL/rest/v1/rpc/heartbeat`
- Headers:
  - `Content-Type: application/json`
  - `apikey: SUPABASE_ANON_KEY`
  - `Authorization: Bearer SUPABASE_ANON_KEY`
- Payload (exact Supabase RPC parameter names):
  - `p_key`: user API key (from ~/.devglobe/api_key)
  - `p_lang`: language name (from languages.js)
  - `p_city`: city name (from geo.js)
  - `p_lat`: latitude (from geo.js)
  - `p_lng`: longitude (from geo.js)
  - `p_editor`: "Zed"
  - `p_anonymous`: false (not configurable in MVP)
  - `p_share_repo`: false (not configurable in MVP)
  - `p_repo`: null (not sent in MVP)
- Timeout: 15s (matches VS Code)
- No retry in MVP (consistent with current VS Code implementation)
- Track consecutive failures; log warning after OFFLINE_THRESHOLD (2) failures

### 5. Geolocation (server/geo.js)

- Fetch https://free.freeipapi.com/api/json on startup
- Cache result in memory for 1 hour
- Extract: city, latitude, longitude, countryCode
- Fallback API: https://ipapi.co/json/
- If both fail: skip heartbeats until next cache expiry

### 6. Git Detection (server/git.js)

- Uses execFile (not exec) to run: git remote get-url origin (timeout 5s)
- Parse GitHub/GitLab URL to owner/repo format
- Cache 5 minutes
- Returns null if not a git repo or no remote
- NOT sent in MVP (share repo is off by default)

### 7. Configuration

- API key: read from `~/.devglobe/api_key` as plain text (same format as Claude Code plugin)
- Fallback: `DEVGLOBE_API_KEY` environment variable (same as Claude Code plugin)
- Supabase anon key: hardcoded in source (public client-side key, RLS-protected — same as VS Code)
- No UI configuration in MVP
- User creates file manually: writes their devglobe_ key to ~/.devglobe/api_key

### 8. Process Lifecycle

- Zed launches the MCP server when the extension activates
- The Node.js process runs independently with its own setInterval timer
- Handle SIGTERM/SIGINT: clear timers, close fs.watch, exit cleanly
- Known limitation: if Zed kills MCP servers when the assistant panel is closed,
  heartbeats will stop. This will be tested during development and documented.
- If the process crashes, Zed may or may not restart it — no auto-restart in MVP

## File Structure

```
zed-extension/
  extension.toml          Manifest: declares MCP context server
  Cargo.toml              Rust WASM boilerplate
  src/
    lib.rs                Stub (registers extension, no logic)
  server/
    package.json          Node.js (zero external dependencies)
    devglobe-server.js    Entry point: init + heartbeat loop
    activity.js           fs.watch + activity tracking
    heartbeat.js          Supabase RPC client (native fetch)
    geo.js                Geolocation fetch + cache
    git.js                Git remote extraction (execFile, no shell)
    languages.js          File extension to language name map
  README.md               Setup: install extension, set API key
```

## Constants (from existing codebase)

- SUPABASE_URL: 'https://kzcrtlbspkhlnjillhyz.supabase.co' (from constants.ts)
- SUPABASE_ANON_KEY: (JWT from constants.ts — hardcoded, public client key, RLS-protected)
- OFFLINE_THRESHOLD: 2 consecutive failures
- HEARTBEAT_INTERVAL: 30000ms
- ACTIVITY_TIMEOUT: 60000ms
- GEO_CACHE_TTL: 3600000ms (1 hour)
- GIT_CACHE_TTL: 300000ms (5 minutes)
- FETCH_TIMEOUT: 15000ms

## What is NOT included (future PRs)

- Anonymous mode (random city in same country)
- Status messages
- Share repo toggle (always off)
- Sidebar UI
- User notifications
- Retry/exponential backoff on network errors
- Zed settings integration
- Streak tracking display

## Testing

- Manual: install as dev extension in Zed, verify heartbeat appears on devglobe.xyz
- Unit: heartbeat payload construction, language map, geo cache, git URL parsing
- No CI in MVP (follow repo's existing pattern — no CI configured)

## Dependencies

- Runtime: Node.js 20+ (fs.watch recursive on Linux requires 20+; native fetch requires 18+)
- npm packages: zero (all functionality via Node.js built-ins)
- Rust crates: zed_extension_api only

## Success Criteria

1. User installs extension in Zed
2. Creates ~/.devglobe/api_key with their key
3. Opens a project and starts coding
4. Appears on devglobe.xyz globe within 30 seconds
5. Disappears after 60 seconds of inactivity
6. Correct language shown based on file being edited
