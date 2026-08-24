import asyncio
import json
import subprocess
import sys
import textwrap


async def test_server(server_path):
    print(f"Testing MCP server at: {server_path}")

    # Start the server process
    process = subprocess.Popen(
        [sys.executable, "-u", server_path],  # -u for unbuffered output
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,  # Line buffered
        env={"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
    )

    # Send an initialize message
    init_message = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        },
    }

    # Send the message to the server
    init_json = json.dumps(init_message) + "\n"
    print(f"Sending: {init_json.strip()}")
    process.stdin.write(init_json)
    process.stdin.flush()

    # Read the response
    response_line = process.stdout.readline()
    print(f"Raw response: {repr(response_line)}")

    # Check for invalid characters
    if response_line.strip():
        try:
            parsed = json.loads(response_line)
            print("Successfully parsed JSON response:")
            print(json.dumps(parsed, indent=2))
        except json.JSONDecodeError as e:
            print(f"JSON parse error: {e}")
            print("First 10 characters:", repr(response_line[:10]))

            # Examine the response in more detail
            for i, char in enumerate(response_line[:20]):
                print(f"Character {i}: {repr(char)} (ASCII: {ord(char)})")

    # Wait briefly and terminate the process
    await asyncio.sleep(1)
    process.terminate()
    process.wait()

    # Show stderr for debugging
    stderr_output = process.stderr.read()
    if stderr_output:
        print("\nServer stderr output:")
        print(textwrap.indent(stderr_output, "  "))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python debug_mcp_connection.py path/to/server.py")
        sys.exit(1)

    asyncio.run(test_server(sys.argv[1]))
