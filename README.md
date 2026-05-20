# otter-mcp

Unofficial [Otter.ai](https://otter.ai) MCP server, because the [official one](https://help.otter.ai/hc/en-us/articles/35287607569687-Otter-MCP-Server) doesn't do what I need it to.

## Why not the official MCP server?

- **Auth is brittle.** Sessions started dying mid-use recently — whether the fault lies with the client or the server is unclear, but the result is the same.
- **Conversations are filtered.** Listing and search both work, but they don't return the same results as the web UI. Conversations shared with you through a workspace may not appear at all — even if you can see and access them in the browser.
- **Fetching by ID is blocked.** Even if you know the conversation ID, the server may refuse to return it. The permission model the API enforces doesn't match what the web UI grants you.

In short: if you can see it in the browser, you should be able to access it via MCP. The official server disagrees. This one uses the same web API that powers the Otter.ai frontend, so there's no mismatch.

## Tools

These are the tools I built for my own workflow. They cover what I need day-to-day:

| Tool | Description |
|---|---|
| `list_conversations` | Paginated homepage feed — everything you see in the web UI |
| `search` | Find conversations by title |
| `get_transcript` | Full speaker-attributed transcript with timestamps, identical to the web export |

### Adding more tools

Open Otter.ai, launch Chrome DevTools, capture the traffic for whatever action you want to automate, save it as a `.har` file, then bring up [Claude Code](https://claude.ai/code) from this repo, point it to the file, and tell it what you want. That's how every tool here was built.

## Setup

```bash
uv run otter-mcp
```

Requires three environment variables:

| Variable | Description |
|---|---|
| `OTTER_EMAIL` | Your Otter.ai email |
| `OTTER_PASSWORD` | Your Otter.ai password |
| `OTTER_TOTP_SECRET` | Your TOTP 2FA secret |

Session cookies are persisted to `$XDG_STATE_HOME/otter-mcp/cookies.json` (`~/.local/state` by default), so the login + 2FA dance only happens when the session actually expires.

## MCP configuration

```json
{
  "mcpServers": {
    "otter": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/otter-mcp", "otter-mcp"],
      "env": {
        "OTTER_EMAIL": "${OTTER_EMAIL}",
        "OTTER_PASSWORD": "${OTTER_PASSWORD}",
        "OTTER_TOTP_SECRET": "${OTTER_TOTP_SECRET}"
      }
    }
  }
}
```
