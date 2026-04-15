# Solana x402 Endpoint Scanner

Open-source scanner that discovers and maps x402 machine-to-machine payment endpoints on Solana mainnet. Part of the [SmartFlow](https://smartflowproai.com) Agent Payment Intelligence infrastructure.

## What it does

- **Discovers** x402 endpoints that accept Solana payments (USDC, USDT, pyUSD, and more)
- **Extracts** Solana wallet addresses (payTo, feePayer) from x402 payment headers
- **Maps** the Solana x402 ecosystem: providers, wallets, facilitators, stablecoins
- **Scans** on-chain transactions for micropayment patterns (optional, requires Helius API key)
- **Integrates** with the SmartFlow network mapper database for cross-chain analysis

## Current Solana x402 Stats

| Metric | Count |
|--------|-------|
| Solana x402 endpoints | 186 |
| Unique Solana wallets | 17 |
| Unique providers | 27 |
| Stablecoins accepted | 7 (USDC, USDT, pyUSD, USDS, USD1, jUSD, CASH) |

> Data as of April 15, 2026. Updated by continuous 4x daily scanning.

## Quick Start

```bash
# Clone
git clone https://github.com/smartflowproai-lang/solana-x402-scanner.git
cd solana-x402-scanner

# Install dependencies
pip install -r requirements.txt

# Run (probe mode — no API key needed if you have a mapper DB)
python3 scanner.py --db /path/to/mapper.db --output results.json

# Run with on-chain scanning (requires free Helius API key)
export HELIUS_API_KEY="your-key-here"
python3 scanner.py --scan-wallets --output results.json
```

## How it works

### Three-strategy approach

1. **Mapper DB Integration** — Loads Solana endpoints from the SmartFlow x402 network mapper database (21,792+ endpoints across chains, filtered for Solana)
2. **HTTP Probing** — Sends requests to known/suspected endpoints, parses HTTP 402 responses for x402 payment schemas
3. **On-chain Scanning** — Uses Helius RPC to trace USDC micropayment patterns on discovered wallet addresses

### Detection methodology

The scanner identifies x402 endpoints by:
- HTTP 402 status code with valid `x402Version` field
- `accepts` array containing `solana-mainnet-beta` or `solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp` network
- Valid Solana `payTo` address and optional `feePayer` for gasless transactions
- Stablecoin mint addresses matching known tokens (USDC, USDT, pyUSD, etc.)

## Output

```json
{
  "summary": {
    "total_solana_endpoints": 186,
    "unique_solana_wallets": 17,
    "unique_providers": 27,
    "usdc_micropayments_found": 0
  },
  "wallets": ["2wKupLR9q6...", "..."],
  "providers": ["agent1-gateway.aurracloud.com", "..."]
}
```

## Integration

This scanner feeds data into the SmartFlow ecosystem:
- **Dashboard**: [smartflowproai.com/solana](https://smartflowproai.com/solana/)
- **Main mapper**: 21,792+ endpoints across Base, Solana, and other chains
- **Quality scoring**: Endpoint health, payment validity, uptime monitoring

## Requirements

- Python 3.8+
- `requests` library
- Optional: [Helius](https://helius.dev) API key (free tier) for on-chain scanning
- Optional: SmartFlow mapper database for cross-chain data

## License

MIT — see [LICENSE](LICENSE) file.

## Author

**Tom Smart** — [SmartFlow Intelligence](https://smartflowproai.com)
- GitHub: [@smartflowproai-lang](https://github.com/smartflowproai-lang)
- X: [@TomSmart_ai](https://x.com/TomSmart_ai)

---

*Built as part of SmartFlow Agent Payment Intelligence — mapping every x402 endpoint, every chain, every protocol.*
