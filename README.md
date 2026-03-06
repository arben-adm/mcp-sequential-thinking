[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/arben-adm-mcp-sequential-thinking-badge.png)](https://mseep.ai/app/arben-adm-mcp-sequential-thinking)

# Sequential Thinking MCP Server

A Model Context Protocol (MCP) server that facilitates structured, progressive thinking through defined stages. This tool helps break down complex problems into sequential thoughts, track the progression of your thinking process, and generate summaries.

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code Style: Black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

<a href="https://glama.ai/mcp/servers/m83dfy8feg"><img width="380" height="200" src="https://glama.ai/mcp/servers/m83dfy8feg/badge" alt="Sequential Thinking Server MCP server" /></a>

## Features

- **Structured Thinking Framework**: Organizes thoughts through standard cognitive stages (Problem Definition, Research, Analysis, Synthesis, Conclusion)
- **Thought Tracking**: Records and manages sequential thoughts with metadata
- **Related Thought Analysis**: Identifies connections between similar thoughts
- **Progress Monitoring**: Tracks your position in the overall thinking sequence
- **Summary Generation**: Creates concise overviews of the entire thought process
- **Persistent Storage**: Automatically saves your thinking sessions with thread-safety
- **Data Import/Export**: Share and reuse thinking sessions
- **Extensible Architecture**: Easily customize and extend functionality
- **Robust Error Handling**: Graceful handling of edge cases and corrupted data
- **Type Safety**: Comprehensive type annotations and validation

## Prerequisites

- Python 3.10 or higher
- UV package manager ([Install Guide](https://github.com/astral-sh/uv))

## Key Technologies

- **Pydantic**: For data validation and serialization
- **Portalocker**: For thread-safe file access
- **FastMCP**: For Model Context Protocol integration
- **Rich**: For enhanced console output
- **PyYAML**: For configuration management

## Project Structure

```
mcp-sequential-thinking/
├── mcp_sequential_thinking/
│   ├── server.py       # Main server implementation and MCP tools
│   ├── models.py       # Data models with Pydantic validation
│   ├── storage.py      # Thread-safe persistence layer
│   ├── storage_utils.py # Shared utilities for storage operations
│   ├── analysis.py     # Thought analysis and pattern detection
│   ├── utils.py        # Common utilities and helper functions
│   ├── logging_conf.py # Centralized logging configuration
│   └── __init__.py     # Package initialization
├── tests/              
│   ├── test_analysis.py # Tests for analysis functionality
│   ├── test_models.py   # Tests for data models
│   ├── test_storage.py  # Tests for persistence layer
│   └── __init__.py
├── run_server.py       # Server entry point script
├── debug_mcp_connection.py # Utility for debugging connections
├── README.md           # Main documentation
├── CHANGELOG.md        # Version history and changes
├── example.md          # Customization examples
├── LICENSE             # MIT License
└── pyproject.toml      # Project configuration and dependencies
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

   # For development with testing tools
   uv pip install -e ".[dev]"

   # For all optional dependencies
   uv pip install -e ".[all]"
   ```

2. **Run the Server**
   ```bash
   # Run directly
   uv run -m mcp_sequential_thinking.server

   # Or use the installed script
   mcp-sequential-thinking
   ```

3. **Run Tests**
   ```bash
   # Run all tests
   pytest

   # Run with coverage report
   pytest --cov=mcp_sequential_thinking
   ```

## Claude Desktop Integration

Add to your Claude Desktop configuration:
- **Linux**: `~/.config/Claude/claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

### Option 1: Using the virtual environment (recommended for Linux/macOS)

If you have set up the project with `uv venv && uv pip install -e .`, point directly to the venv Python interpreter. This avoids dependency resolution issues (e.g., on systems with Python 3.14+):

```json
{
  "mcpServers": {
    "sequential-thinking": {
      "command": "/path/to/mcp-sequential-thinking/.venv/bin/python",
      "args": [
        "-m",
        "mcp_sequential_thinking.server"
      ],
      "cwd": "/path/to/mcp-sequential-thinking"
    }
  }
}
```

### Option 2: Using uv run

```json
{
  "mcpServers": {
    "sequential-thinking": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/mcp-sequential-thinking",
        "-m",
        "mcp_sequential_thinking.server"
      ]
    }
  }
}
```

### Option 3: Using the installed entry point

If you've installed the package globally with `pip install -e .`:

```json
{
  "mcpServers": {
    "sequential-thinking": {
      "command": "mcp-sequential-thinking"
    }
  }
}
```

### Option 4: Using uvx (no local install needed)

```json
{
  "mcpServers": {
    "sequential-thinking": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/arben-adm/mcp-sequential-thinking",
        "--with",
        "portalocker",
        "mcp-sequential-thinking"
      ]
    }
  }
}
```

## Editor & IDE Integration

### Cursor

Add to your Cursor MCP configuration at `.cursor/mcp.json` in your project root (or globally at `~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "sequential-thinking": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/mcp-sequential-thinking",
        "-m",
        "mcp_sequential_thinking.server"
      ]
    }
  }
}
```

### VS Code (Copilot MCP)

VS Code supports MCP servers since version 1.99+. Add to `.vscode/mcp.json` in your workspace or to your user `settings.json`:

```json
{
  "servers": {
    "sequential-thinking": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/mcp-sequential-thinking",
        "-m",
        "mcp_sequential_thinking.server"
      ]
    }
  }
}
```

> **Note:** Enable MCP support in VS Code via `"chat.mcp.enabled": true` in your settings.

### Zed

Add to your Zed settings (`~/.config/zed/settings.json`):

```json
{
  "context_servers": {
    "sequential-thinking": {
      "command": {
        "path": "uv",
        "args": [
          "run",
          "--directory",
          "/path/to/mcp-sequential-thinking",
          "-m",
          "mcp_sequential_thinking.server"
        ]
      }
    }
  }
}
```

### Claude Code (CLI)

Add the server using the CLI:

```bash
claude mcp add sequential-thinking -- uv run --directory /path/to/mcp-sequential-thinking -m mcp_sequential_thinking.server
```

Or manually create/edit `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "sequential-thinking": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/mcp-sequential-thinking",
        "-m",
        "mcp_sequential_thinking.server"
      ]
    }
  }
}
```

### Windsurf

Add to your Windsurf MCP configuration at `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "sequential-thinking": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/mcp-sequential-thinking",
        "-m",
        "mcp_sequential_thinking.server"
      ]
    }
  }
}
```

### Gemini CLI

Add to your Gemini CLI settings at `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "sequential-thinking": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/arben-adm/mcp-sequential-thinking",
        "--with",
        "portalocker",
        "mcp-sequential-thinking"
      ],
      "env": {}
    }
  }
}
```

> **Tip:** All editor configurations above use `uv run` or `uvx`. You can also point directly to the venv Python interpreter (see [Claude Desktop Option 1](#option-1-using-the-virtual-environment-recommended-for-linuxmacos)) or use `uvx` (see [Option 4](#option-4-using-uvx-no-local-install-needed)) if you prefer not to clone the repository.

# How It Works

The server maintains a history of thoughts and processes them through a structured workflow. Each thought is validated using Pydantic models, categorized into thinking stages, and stored with relevant metadata in a thread-safe storage system. The server automatically handles data persistence, backup creation, and provides tools for analyzing relationships between thoughts.

## Usage Guide

The Sequential Thinking server exposes five main tools:

### 1. `process_thought`

Records and analyzes a new thought in your sequential thinking process.

**Parameters:**

- `thought` (string): The content of your thought
- `thought_number` (integer): Position in your sequence (e.g., 1 for first thought)
- `total_thoughts` (integer): Expected total thoughts in the sequence
- `next_thought_needed` (boolean): Whether more thoughts are needed after this one
- `stage` (string): The thinking stage - must be one of:
  - "Problem Definition"
  - "Research"
  - "Analysis"
  - "Synthesis"
  - "Conclusion"
- `tags` (list of strings, optional): Keywords or categories for your thought
- `axioms_used` (list of strings, optional): Principles or axioms applied in your thought
- `assumptions_challenged` (list of strings, optional): Assumptions your thought questions or challenges

**Example:**

```python
# First thought in a 5-thought sequence
process_thought(
    thought="The problem of climate change requires analysis of multiple factors including emissions, policy, and technology adoption.",
    thought_number=1,
    total_thoughts=5,
    next_thought_needed=True,
    stage="Problem Definition",
    tags=["climate", "global policy", "systems thinking"],
    axioms_used=["Complex problems require multifaceted solutions"],
    assumptions_challenged=["Technology alone can solve climate change"]
)
```

### 2. `generate_summary`

Generates a summary of your entire thinking process.

**Example output:**

```json
{
  "summary": {
    "totalThoughts": 5,
    "stages": {
      "Problem Definition": 1,
      "Research": 1,
      "Analysis": 1,
      "Synthesis": 1,
      "Conclusion": 1
    },
    "timeline": [
      {"number": 1, "stage": "Problem Definition"},
      {"number": 2, "stage": "Research"},
      {"number": 3, "stage": "Analysis"},
      {"number": 4, "stage": "Synthesis"},
      {"number": 5, "stage": "Conclusion"}
    ]
  }
}
```

### 3. `clear_history`

Resets the thinking process by clearing all recorded thoughts.

### 4. `export_session`

Exports the current thinking session to a JSON file for sharing or backup.

**Parameters:**

- `file_path` (string): Path to the output JSON file (parent directories are created automatically)

**Example:**

```python
export_session(file_path="/home/user/exports/my-analysis.json")
```

### 5. `import_session`

Imports a previously exported thinking session from a JSON file.

**Parameters:**

- `file_path` (string): Path to the JSON file to import

## Practical Applications

- **Decision Making**: Work through important decisions methodically
- **Problem Solving**: Break complex problems into manageable components
- **Research Planning**: Structure your research approach with clear stages
- **Writing Organization**: Develop ideas progressively before writing
- **Project Analysis**: Evaluate projects through defined analytical stages


## Getting Started

With the proper MCP setup, simply use the `process_thought` tool to begin working through your thoughts in sequence. As you progress, you can get an overview with `generate_summary` and reset when needed with `clear_history`.



# Customizing the Sequential Thinking Server

For detailed examples of how to customize and extend the Sequential Thinking server, see [example.md](example.md). It includes code samples for:

- Modifying thinking stages
- Enhancing thought data structures with Pydantic
- Adding persistence with databases
- Implementing enhanced analysis with NLP
- Creating custom prompts
- Setting up advanced configurations
- Building web UI integrations
- Implementing visualization tools
- Connecting to external services
- Creating collaborative environments
- Separating test code
- Building reusable utilities




## License

MIT License



