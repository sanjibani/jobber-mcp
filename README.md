# jobber-mcp

**Model Context Protocol (MCP) server for [Jobber](https://getjobber.com/)** — home service business management software (HVAC, plumbing, landscaping, etc.).

Talk to Jobber from Claude, Cursor, or any MCP client. Read clients, jobs, quotes, invoices; create new clients and add notes. GraphQL API via OAuth2 bearer token.

Built against the [Jobber Developer API](https://developer.getjobber.com/docs/). No existing MCP for Jobber — this is the first.

## What you can do with it

```
You:   "Show me every active job assigned to Alex."
Claude: *list_jobs(status="active") then filters by assignedTo*

You:   "Find every quote awaiting response for over 7 days."
Claude: *list_quotes(status="awaiting_response") then filters by createdAt*

You:   "Add a note to client 12345: 'Replaced capacitor, system running.'"
Claude: *add_client_note with body*

You:   "Create a new client: Sarah Chen, sarah@example.com, 555-0101."
Claude: *create_client*
```

## Install

```bash
pip install -e .
```

## Configure

You need an OAuth2 access token. Get one via the [Jobber OAuth flow](https://developer.getjobber.com/docs/) — register your app, complete the install dance, store the returned token.

```bash
export JOBBER_ACCESS_TOKEN="..."
```

For multi-tenant apps, run multiple MCP server instances — each with its own token. Jobber's tokens expire; you'll need to refresh on your backend and restart the MCP server.

## Use with Claude Desktop

```json
{
  "mcpServers": {
    "jobber_mcp": {
      "command": "jobber_mcp",
      "env": {
        "JOBBER_ACCESS_TOKEN": "..."
      }
    }
  }
}
```

## Tools

| Tool | Type | What it does |
| --- | --- | --- |
| `health_check` | Diagnostic | Verifies token |
| `list_clients` | Read | Homeowners / businesses |
| `list_jobs` | Read | Work orders (filterable by status) |
| `list_quotes` | Read | Quotes (filterable by status) |
| `list_invoices` | Read | Invoices (filterable by status) |
| `create_client` | Write | New client |
| `add_client_note` | Write | Note on client record |

## Why GraphQL, not REST?

Jobber's API is GraphQL-only. The advantage: one HTTP endpoint, ask for exactly the fields you need, no over-fetching, no under-fetching. The MCP tools use minimal field selections so the agent gets the data it needs without pagination churn.

## Development

```bash
pip install -e ".[dev]"
pytest
jobber_mcp
```

## License

MIT.

## Acknowledgements

- Jobber for the GraphQL API + OAuth2 flow
- Built using [mcp-vertical-template](https://github.com/sanjibani/mcp-vertical-template) (the GraphQL client is a small variation of the REST template)
- Inspired by [sanjibani/hawksoft-mcp](https://github.com/sanjibani/hawksoft-mcp) and [sanjibani/ezyvet-mcp](https://github.com/sanjibani/ezyvet-mcp)

## See also

- [Jobber API docs](https://developer.getjobber.com/docs/)
- [Jobber Developer Center](https://developer.getjobber.com/)
- [Model Context Protocol](https://modelcontextprotocol.io)
- [More vertical MCPs from sanjibani](https://github.com/sanjibani?q=-mcp)