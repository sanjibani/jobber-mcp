# Jobber MCP

**MCP server for Jobber MCP** — talk to your data from Claude, Cursor, or any MCP client.

## What you can do with it

```
You:   "Find every record updated this week and group them by status."
Claude: *calls the appropriate MCP tools, summarises the result*

You:   "Create a new record with these fields..."
Claude: *calls the create tool, confirms the result*
```

## Install

```bash
pip install -e .
```

## Configure

```bash
export JOBBER_USERNAME="..."
export JOBBER_PASSWORD="..."
```

### Who uses this?

1. **API Partners** building tools on top of Jobber MCP.
2. **Power users / agencies** doing their own custom integrations.

If you don't have credentials yet, contact Jobber MCP support to get set up.

## Use with Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "jobber_mcp": {
      "command": "jobber_mcp",
      "env": {
        "JOBBER_USERNAME": "your-username",
        "JOBBER_PASSWORD": "your-password"
      }
    }
  }
}
```

## Use with Claude Code

```bash
claude mcp add jobber_mcp -- jobber_mcp \
  --env JOBBER_USERNAME=your-user --env JOBBER_PASSWORD=your-pass
```

## Tools

| Tool | Type | What it does |
| --- | --- | --- |
| `health_check` | Diagnostic | Verifies credentials by hitting a known endpoint |

(TODO: list your actual tools here once defined)

## Development

```bash
pip install -e ".[dev]"
pytest
jobber_mcp
```

## License

MIT.

## See also

- [Model Context Protocol spec](https://modelcontextprotocol.io)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers)