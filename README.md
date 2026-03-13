# NSX Troubleshooting Bot

An AI-powered CLI tool that diagnoses VMware NSX network issues by autonomously querying the NSX Manager REST API. You describe a problem in plain English — the bot figures out which API endpoints to call, interprets the results, and delivers a diagnosis with supporting evidence.

## How It Works

The bot runs an agentic loop powered by **Claude claude-opus-4-6** (with adaptive thinking enabled):

1. You describe a network problem
2. Claude identifies the relevant NSX components
3. The bot issues targeted `GET` requests to the NSX Manager API
4. Claude analyzes the responses, drills into specifics, and produces a diagnosis

All API access is **read-only** — the bot only performs `GET` requests and never modifies your environment.

## Requirements

- Python 3.8+
- Access to an NSX Manager instance (NSX-T or NSX 4.x)
- An [Anthropic API key](https://console.anthropic.com/)

## Installation

```bash
git clone git@github.com:myersc00-afk/nsx_bot.git
cd nsx_bot
pip install -r requirements.txt --break-system-packages
cp .env.example .env
```

Edit `.env` with your credentials:

```ini
ANTHROPIC_API_KEY=your-anthropic-api-key
NSX_HOST=https://your-nsx-manager.example.com
NSX_USERNAME=admin
NSX_PASSWORD=your-password
NSX_VERIFY_SSL=true   # set to false for self-signed certs (labs only)
```

## Usage

```bash
python3 main.py
```

At the prompt, describe your problem in plain English and press Enter.

---

## Example Sessions

### VM Connectivity Issue

```
🔍 Problem: VM "web-01" lost connectivity to the database subnet 10.10.20.0/24 after a maintenance window

  → GET /api/v1/virtual-machines
  → GET /api/v1/logical-ports
  → GET /api/v1/logical-ports/a3f1bc29-xxxx/status
  → GET /api/v1/logical-routers
  → GET /api/v1/logical-routers/e7d4-xxxx/routing/forwarding-table

Diagnosis:
The logical port attached to web-01 is in admin state DOWN — it was likely left
disabled after the maintenance window. The forwarding table on the T1 router
shows the 10.10.20.0/24 route is still present, so routing is intact.

Recommended fix: re-enable the logical port for the web-01 VIF.
```

---

### BGP Peering Down

```
🔍 Problem: BGP session to upstream router 192.168.100.1 is flapping on T0 gateway

  → GET /api/v1/logical-routers?router_type=TIER0
  → GET /api/v1/logical-routers/t0-xxxx/routing/bgp/neighbors
  → GET /api/v1/logical-routers/t0-xxxx/routing/bgp/neighbors/status
  → GET /api/v1/transport-nodes
  → GET /api/v1/transport-nodes/edge-node-1/status

Diagnosis:
The BGP neighbor 192.168.100.1 shows state ACTIVE (not ESTABLISHED) with
"Hold timer expired" errors. The edge transport node reports its datapath
status as DEGRADED. One of the edge node's uplink interfaces lost its kernel
route, causing BGP keepalives to drop.

Recommended fix: check physical NIC connectivity on the edge node and
verify the uplink MTU matches the upstream switch.
```

---

### DFW Rule Blocking Traffic

```
🔍 Problem: Application team says traffic on port 8443 is being blocked — worked fine last week

  → GET /api/v1/firewall/sections
  → GET /api/v1/firewall/sections/block-section-xxxx/rules
  → GET /api/v1/ns-groups
  → GET /api/v1/virtual-machines

Diagnosis:
A new DFW rule "block-untrusted-egress" was added to the top of the
"Block" section with destination ANY and service HTTPS (443, 8443). It was
inserted above the existing allow rule and is shadowing it. The rule was
created 6 days ago by user "nsxadmin".

Recommended fix: reorder the allow rule above the block rule, or scope
the block rule's destination to exclude the application subnet.
```

---

## Covered API Areas

| Area | Endpoints |
|------|-----------|
| Cluster & Health | `/api/v1/cluster/status`, alarms, fabric nodes |
| Transport Nodes | Status, configuration, connectivity |
| Logical Networking | Switches, ports, routers (Manager API) |
| Routing | Forwarding table, RIB, BGP neighbors |
| Distributed Firewall | Sections, rules, NS Groups |
| Load Balancing | Services, virtual servers, pools |
| DHCP / IPAM | DHCP servers, IP pools |
| Policy API (NSX 4.x) | Segments, T0/T1 gateways, security policies |

## Project Structure

```
nsx_bot/
├── main.py          # CLI entry point and agentic loop
├── nsx_client.py    # NSX Manager HTTP client (session auth)
├── requirements.txt
└── .env.example     # Environment variable template
```

## Notes

- API responses larger than 40,000 characters are automatically truncated to protect the context window; use `page_size` and cursor parameters to paginate if needed.
- `NSX_VERIFY_SSL=false` disables TLS verification — only use this in lab environments with self-signed certificates.
