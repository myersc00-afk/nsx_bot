#!/usr/bin/env python3
"""NSX Troubleshooting Bot — performs API GET lookups based on a problem description."""

import json
import os
import sys

import anthropic
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from nsx_client import NSXClient

load_dotenv()

console = Console()

SYSTEM_PROMPT = """You are an expert VMware NSX network engineer and troubleshooter. Your job is \
to diagnose network issues by performing targeted NSX Manager REST API GET lookups.

When given a problem description:
1. Identify the likely affected NSX components
2. Perform systematic GET lookups, starting broad then narrowing to specific objects
3. Analyze the returned data for anomalies, errors, or misconfigurations
4. Present a clear diagnosis with supporting evidence from the API data

You have access to the `nsx_get` tool to query any NSX REST API GET endpoint.

## Common NSX API Endpoints

### Health & Status
- /api/v1/cluster/status               — NSX Manager cluster health
- /api/v1/alarms                       — Active alarms
- /api/v1/fabric/nodes                 — Fabric nodes (ESXi/KVM hosts)
- /api/v1/fabric/nodes/{id}/status     — Node connectivity/config status
- /api/v1/transport-nodes              — Transport nodes
- /api/v1/transport-nodes/{id}/status  — Transport node state

### Logical Networking (Manager API)
- /api/v1/logical-switches             — Logical switches (overlay segments)
- /api/v1/logical-switches/{id}        — Specific switch
- /api/v1/logical-ports                — Logical ports
- /api/v1/logical-ports/{id}/status    — Port operational status (admin/link state)
- /api/v1/logical-routers              — Logical routers (type: TIER0, TIER1)
- /api/v1/logical-routers/{id}         — Specific router
- /api/v1/logical-router-ports         — All logical router ports
- /api/v1/logical-router-ports?logical_router_id={id}  — Ports on a specific router

### Routing (Manager API)
- /api/v1/logical-routers/{id}/routing/forwarding-table  — Effective forwarding table
- /api/v1/logical-routers/{id}/routing/routing-table     — RIB (all learned routes)
- /api/v1/logical-routers/{id}/routing/bgp/neighbors     — BGP neighbor state
- /api/v1/logical-routers/{id}/routing/bgp/neighbors/status — BGP neighbor status

### Security (Manager API)
- /api/v1/ns-groups                          — NS Groups
- /api/v1/firewall/sections                  — DFW sections
- /api/v1/firewall/sections/{id}/rules       — Rules within a DFW section
- /api/v1/virtual-machines                   — VMs tracked by NSX (for DFW membership)

### Services
- /api/v1/dhcp/servers                       — DHCP servers
- /api/v1/dhcp/servers/{id}/status           — DHCP server status
- /api/v1/loadbalancer/services              — Load balancer services
- /api/v1/loadbalancer/virtual-servers       — LB virtual servers
- /api/v1/loadbalancer/pools                 — LB backend pools
- /api/v1/ipam/ip-pools                      — IP pools

### Policy API (newer NSX-T / NSX 4.x)
- /policy/api/v1/infra/segments                                           — Segments
- /policy/api/v1/infra/tier-0s                                            — T0 gateways
- /policy/api/v1/infra/tier-1s                                            — T1 gateways
- /policy/api/v1/infra/domains/default/groups                             — Security groups
- /policy/api/v1/infra/domains/default/security-policies                  — Security policies
- /policy/api/v1/infra/domains/default/security-policies/{id}/rules       — Policy rules
- /policy/api/v1/infra/services                                           — Policy services
- /policy/api/v1/infra/lb-services                                        — LB services (Policy)

## Tips
- Use `page_size=100` param to get more results per page
- When you find an object ID, query its detail and status endpoints
- Check alarm descriptions — they often directly name the problem
- Transport node status "degraded" or "failed" is critical for connectivity issues
- For VM connectivity: check logical port status, then the switch, then the router
"""

NSX_GET_TOOL = {
    "name": "nsx_get",
    "description": (
        "Perform an HTTP GET request to the NSX Manager REST API. "
        "Returns the parsed JSON response or an error object."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "API path to query. Examples: '/api/v1/logical-switches', "
                    "'/api/v1/logical-routers/{id}/routing/forwarding-table', "
                    "'/policy/api/v1/infra/segments'"
                ),
            },
            "params": {
                "type": "object",
                "description": "Optional query parameters, e.g. {'page_size': 100, 'logical_router_id': 'abc-123'}",
                "additionalProperties": True,
            },
        },
        "required": ["path"],
    },
}

# Truncate large API responses to avoid blowing out the context window
MAX_RESULT_CHARS = 40_000


def truncate_result(data: dict) -> str:
    text = json.dumps(data, indent=2)
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return text[:MAX_RESULT_CHARS] + "\n\n... [response truncated — use page_size/cursor params to paginate]"


def run_bot(nsx_client: NSXClient, anthropic_client: anthropic.Anthropic) -> None:
    console.print(Panel.fit(
        "[bold cyan]NSX Troubleshooting Bot[/bold cyan]\n"
        "Describe your NSX problem and I'll perform API lookups to diagnose it.\n"
        "Type [bold]exit[/bold] to quit.",
        border_style="cyan",
    ))

    while True:
        console.print()
        try:
            problem = input("🔍 Problem: ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Goodbye![/yellow]")
            break

        if problem.lower() in ("exit", "quit", "q"):
            console.print("[yellow]Goodbye![/yellow]")
            break

        if not problem:
            continue

        console.print()
        messages = [{"role": "user", "content": problem}]

        # Agentic loop: keep going until Claude finishes (no more tool calls)
        while True:
            with console.status("[cyan]Analyzing...[/cyan]"):
                response = anthropic_client.messages.create(
                    model="claude-opus-4-6",
                    max_tokens=8096,
                    thinking={"type": "adaptive"},
                    system=SYSTEM_PROMPT,
                    tools=[NSX_GET_TOOL],
                    messages=messages,
                )

            # Print any text blocks Claude produces
            tool_use_blocks = []
            for block in response.content:
                if block.type == "text" and block.text.strip():
                    console.print(Markdown(block.text))
                elif block.type == "tool_use":
                    tool_use_blocks.append(block)

            if response.stop_reason == "end_turn":
                break

            if response.stop_reason != "tool_use":
                break

            # Execute each tool call and collect results
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []

            for tb in tool_use_blocks:
                path = tb.input.get("path", "")
                params = tb.input.get("params") or {}

                param_str = f" {params}" if params else ""
                console.print(f"  [dim]→ GET {path}{param_str}[/dim]")

                result = nsx_client.get(path, params if params else None)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tb.id,
                    "content": truncate_result(result),
                })

            messages.append({"role": "user", "content": tool_results})


def main() -> None:
    missing = []
    for var in ("ANTHROPIC_API_KEY", "NSX_HOST", "NSX_USERNAME", "NSX_PASSWORD"):
        if not os.getenv(var):
            missing.append(var)

    if missing:
        console.print(f"[red]Error: missing required environment variables: {', '.join(missing)}[/red]")
        console.print("[yellow]Copy .env.example to .env and fill in your values.[/yellow]")
        sys.exit(1)

    try:
        nsx_client = NSXClient(
            host=os.environ["NSX_HOST"],
            username=os.environ["NSX_USERNAME"],
            password=os.environ["NSX_PASSWORD"],
            verify_ssl=os.getenv("NSX_VERIFY_SSL", "true").lower() == "true",
        )
    except ValueError as e:
        console.print(f"[red]Configuration error: {e}[/red]")
        sys.exit(1)

    anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    run_bot(nsx_client, anthropic_client)


if __name__ == "__main__":
    main()
