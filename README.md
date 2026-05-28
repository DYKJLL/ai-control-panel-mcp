# AI Control Panel MCP

MCP server for AI Control Panel. Lets any AI use browser image generation & vision via remote API.

## Usage

Add to your AI client's MCP config:

```json
{
  "mcpServers": {
    "ai-control-panel": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/DYKJLL/ai-control-panel-mcp", "ai-control-panel-mcp"],
      "env": {
        "AI_PANEL_URL": "http://your-server:1984"
      }
    }
  }
}
```

Set `AI_PANEL_URL` to your deployed AI Control Panel server address.
