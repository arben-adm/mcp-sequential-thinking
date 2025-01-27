# Enhanced Sequential Thinking MCP Server

[![smithery badge](https://smithery.ai/badge/sequential-thinking)](https://smithery.ai/server/sequential-thinking)
This project implements an advanced Sequential Thinking server using the Model Context Protocol (MCP). It provides a structured and flexible approach to problem-solving and decision-making through a series of thought steps, incorporating stages, scoring, and tagging.

<a href="https://glama.ai/mcp/servers/m83dfy8feg"><img width="380" height="200" src="https://glama.ai/mcp/servers/m83dfy8feg/badge" alt="Sequential Thinking Server MCP server" /></a>

## Features

- 🧠 **Structured Problem Solving**: Break down complex problems into defined stages
- 📊 **Progress Tracking**: Monitor thought sequences, branches, and revisions
- 🏷️ **Thought Categorization**: Tag and score thoughts for better organization
- 📈 **Dynamic Adaptation**: Adjust the thinking process as new insights emerge
- 📝 **Summary Generation**: Get an overview of the entire thinking process

## Prerequisites

- Python 3.11 or higher
- UV package manager ([Install Guide](https://github.com/astral-sh/uv))

## Project Structure

```
mcp-sequential-thinking/
├── mcp_sequential_thinking/
│   ├── server.py
│   └── __init__.py
├── README.md
└── pyproject.toml
```

## Quick Start

1. **Set Up Project**
   ```bash
   # Create and activate virtual environment
   uv venv
   .venv\Scripts\activate  # Windows
   source .venv/bin/activate  # Unix
   
   # Install package and dependencies
   uv pip install -e .
   ```

2. **Run the Server**
   ```bash
   cd mcp_sequential_thinking
   uv run server.py
   ```

## Claude Desktop Integration

Add to your Claude Desktop configuration (`%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "sequential-thinking": {
      "command": "uv",
      "args": [
        "--directory",
        "C:\\path\\to\\your\\mcp-sequential-thinking\\mcp_sequential_thinking",
        "run",
        "server.py"
      ]
    }
  }
}
```

## API

The server exposes two main tools:

### 1. `sequential_thinking`

This tool processes individual thoughts in the sequential thinking process.

Parameters:
- `thought` (str): The content of the current thought
- `thought_number` (int): The sequence number of the current thought
- `total_thoughts` (int): The total number of thoughts expected
- `next_thought_needed` (bool): Whether another thought is needed
- `stage` (str): The current stage of thinking (Problem Definition, Analysis, Ideation, Evaluation, Conclusion)
- `is_revision` (bool, optional): Whether this revises previous thinking
- `revises_thought` (int, optional): Which thought is being reconsidered
- `branch_from_thought` (int, optional): Branching point thought number
- `branch_id` (str, optional): Branch identifier
- `needs_more_thoughts` (bool, optional): If more thoughts are needed
- `score` (float, optional): Score for the thought (0.0 to 1.0)
- `tags` (List[str], optional): List of tags for categorizing the thought

### 2. `get_thinking_summary`

This tool generates a summary of the entire thinking process.

## Troubleshooting

Common issues:

- **Server Connection Issues**
  - Verify paths in claude_desktop_config.json
  - Check Claude Desktop logs: `%APPDATA%\Claude\logs`
  - Test manual server start

## License

MIT License

## Acknowledgments

- Model Context Protocol framework
- Claude Desktop team
