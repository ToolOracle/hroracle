# HROracle MCP Server v1.0.0

**AI Workforce & HR Compliance MCP Server — 12 tools for German labor law. Brutto-Netto, Minijob/Midijob, Kündigungsfristen (§622 BGB), Arbeitszeitgesetz, Elternzeit (BEEG), NachwG contracts, DSGVO offboarding.**

Port 12301 | Part of [ToolOracle](https://tooloracle.io) & [FeedOracle](https://feedoracle.io) Infrastructure

## Quick Connect

```bash
# Claude Desktop / Claude Code
claude mcp add hroracle https://tooloracle.io/hr/mcp

# Or use directly
curl -X POST https://tooloracle.io/hr/mcp/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## 12 Tools

| `gross_to_net` | Tool 1 |
| `employer_cost` | Tool 2 |
| `minijob_check` | Tool 3 |
| `leave_calculate` | Tool 4 |
| `notice_period` | Tool 5 |
| `working_time_check` | Tool 6 |
| `parental_leave_check` | Tool 7 |
| `contract_clauses` | Tool 8 |
| `onboarding_checklist` | Tool 9 |
| `offboarding_checklist` | Tool 10 |
| `skills_gap_analyze` | Tool 11 |
| `headcount_forecast` | Tool 12 |

## Endpoints

| Endpoint | URL |
|----------|-----|
| MCP (StreamableHTTP) | `https://tooloracle.io/hr/mcp/` |
| MCP (FeedOracle) | `https://feedoracle.io/hr/mcp/` |
| Health | `https://tooloracle.io/hr/health` |

## Architecture

- **Transport**: StreamableHTTP + SSE (MCP Protocol 2025-03-26)
- **Auth**: x402 micropayments (USDC on Base) + Stripe subscriptions
- **Signing**: ECDSA ES256K — every response cryptographically signed
- **Platform**: Whitelabel MCP Platform v1.0

## Part of the ToolOracle Ecosystem

ToolOracle operates 81+ MCP servers with 824+ tools across:
- **Compliance & Regulation** — DORA, MiCA, NIS2, AMLR, GDPR, EU AI Act
- **Finance & Tax** — CFOCoPilot, TaxOracle, ISO20022Oracle
- **Legal** — LawOracle, LegalTechOracle, ContractOracle
- **Healthcare** — HealthGuard
- **Supply Chain** — SupplyChainOracle
- **Cybersecurity** — CyberShield, DORAOracle, TLPTOracle
- **HR** — HROracle
- **Blockchain** — 13 chains (ETH, BTC, Solana, Arbitrum, etc.)
- **Business Intelligence** — SEO, Leads, Reviews, E-Commerce

## License

Proprietary — © 2026 ToolOracle / FeedOracle. All rights reserved.
Contact: enterprise@feedoracle.io
