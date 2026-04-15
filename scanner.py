#!/usr/bin/env python3
"""
Solana x402 Endpoint Scanner v1.0
Discovers and maps x402 payment endpoints on Solana mainnet.

Part of SmartFlow Agent Payment Intelligence infrastructure.
https://smartflowproai.com

Usage:
    export HELIUS_API_KEY="your-key"
    python3 scanner.py [--db PATH] [--output PATH]

MIT License - See LICENSE file.
"""

import json
import time
import os
import sys
import re
import argparse
import sqlite3
import requests
from datetime import datetime, timezone
from collections import defaultdict

# ================================================================
# Configuration
# ================================================================

HELIUS_API_KEY = os.environ.get("HELIUS_API_KEY", "")
HELIUS_RPC = "https://mainnet.helius-rpc.com/?api-key=" + HELIUS_API_KEY
HELIUS_API = "https://api.helius.xyz/v0"

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDC_DECIMALS = 6
MIN_AMOUNT_USD = 0.001
MAX_AMOUNT_USD = 10.0

REQUEST_DELAY = 1.0
MAX_RETRIES = 3

KNOWN_STABLES = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
    "2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo": "pyUSD",
    "USDSwr9ApdHk5bvJKMjzff41FfuX8bSxdKcR81vTwcA": "USDS",
    "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB": "USD1",
    "JuprjznTrTSp2UFa3ZBUFgwdAmtZCq4MQCwysN55USD": "jUSD",
    "CASHx9KJUStyftLFWGvEVf59SGeG9sh5FfcnZMVPCASH": "CASH",
}


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def safe_request(method, url, retries=MAX_RETRIES, **kwargs):
    kwargs.setdefault("timeout", 30)
    for attempt in range(retries):
        try:
            resp = requests.request(method, url, **kwargs)
            if resp.status_code == 429:
                wait = (attempt + 1) * 5
                log(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            return resp
        except requests.exceptions.ConnectionError:
            return None
        except requests.exceptions.Timeout:
            time.sleep(2)
        except Exception as e:
            log(f"  Error: {e}")
            time.sleep(2)
    return None


def helius_rpc(method, params):
    if not HELIUS_API_KEY:
        return None
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    resp = safe_request("POST", HELIUS_RPC, json=payload)
    if resp and resp.status_code == 200:
        data = resp.json()
        if "error" in data:
            log(f"  RPC error: {data['error'].get('message', '')}")
            return None
        return data.get("result")
    return None


def helius_enhanced_txs(signatures):
    if not signatures or not HELIUS_API_KEY:
        return []
    url = f"{HELIUS_API}/transactions?api-key={HELIUS_API_KEY}"
    resp = safe_request("POST", url, json={"transactions": signatures}, timeout=60)
    if resp and resp.status_code == 200:
        return resp.json()
    return []


# ================================================================
# Strategy 1: HTTP x402 Endpoint Probing
# ================================================================

def probe_endpoint(url):
    """Probe a URL for x402 payment headers."""
    try:
        resp = requests.get(url, headers={"Accept": "application/json"},
                            timeout=15, allow_redirects=True)
        result = {
            "url": url,
            "status_code": resp.status_code,
            "is_x402": resp.status_code == 402,
            "solana_wallets": [],
            "evm_wallets": [],
            "accepted_assets": [],
            "x402_version": None,
        }
        if resp.status_code == 402:
            try:
                body = resp.json()
                result["x402_version"] = body.get("x402Version")
                for accept in body.get("accepts", []):
                    network = accept.get("network", "")
                    pay_to = accept.get("payTo", "")
                    fee_payer = accept.get("extra", {}).get("feePayer", "")
                    if "solana" in network.lower():
                        if pay_to:
                            result["solana_wallets"].append(pay_to)
                        if fee_payer:
                            result["solana_wallets"].append(fee_payer)
                    elif network in ("base", "ethereum", "eip155:8453"):
                        if pay_to:
                            result["evm_wallets"].append(pay_to)
                    result["accepted_assets"].append({
                        "network": network,
                        "asset": accept.get("asset", ""),
                        "pay_to": pay_to,
                        "max_amount": accept.get("maxAmountRequired", accept.get("amount", "")),
                    })
            except json.JSONDecodeError:
                pass
        result["solana_wallets"] = list(set(result["solana_wallets"]))
        result["evm_wallets"] = list(set(result["evm_wallets"]))
        return result
    except Exception as e:
        return {"url": url, "status_code": None, "is_x402": False, "error": str(e)}


def discover_from_mapper_db(db_path):
    """Pull Solana endpoints from existing mapper database."""
    if not os.path.exists(db_path):
        log(f"Mapper DB not found at {db_path}")
        return []
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT url, raw_accepts FROM endpoints WHERE raw_accepts LIKE '%solana%'")
    endpoints = []
    for url, raw in c.fetchall():
        try:
            data = json.loads(raw)
            wallets = []
            for a in data.get("accepts", []):
                net = a.get("network", "")
                if "solana" in net.lower():
                    pt = a.get("payTo", "")
                    fp = a.get("extra", {}).get("feePayer", "")
                    if pt:
                        wallets.append(pt)
                    if fp:
                        wallets.append(fp)
            endpoints.append({
                "url": url,
                "solana_wallets": list(set(wallets)),
                "raw_accepts": data,
            })
        except json.JSONDecodeError:
            pass
    conn.close()
    log(f"Loaded {len(endpoints)} Solana endpoints from mapper DB")
    return endpoints


# ================================================================
# Strategy 2: On-chain Transaction Scanning
# ================================================================

def scan_wallet_transactions(address, label=""):
    """Scan a Solana wallet for x402-like micropayment patterns."""
    log(f"  Scanning {label} {address[:16]}...")
    time.sleep(REQUEST_DELAY)
    sigs = helius_rpc("getSignaturesForAddress", [address, {"limit": 100}])
    if not sigs:
        return [], {"address": address, "label": label, "tx_count": 0}

    sig_strings = [s["signature"] for s in sigs]
    time.sleep(REQUEST_DELAY)
    parsed = helius_enhanced_txs(sig_strings[:50])

    transfers = []
    for tx in parsed:
        if not tx:
            continue
        for tt in tx.get("tokenTransfers", []):
            mint = tt.get("mint", "")
            amount_raw = tt.get("tokenAmount", 0)
            if isinstance(amount_raw, (int, float)) and amount_raw > 0:
                amount = amount_raw / (10 ** 6) if amount_raw > 1000 else float(amount_raw)
            else:
                amount = 0
            if mint == USDC_MINT and MIN_AMOUNT_USD <= amount <= MAX_AMOUNT_USD:
                transfers.append({
                    "signature": tx.get("signature", ""),
                    "timestamp": tx.get("timestamp", 0),
                    "from": tt.get("fromUserAccount", ""),
                    "to": tt.get("toUserAccount", ""),
                    "amount": round(amount, 6),
                })

    summary = {
        "address": address,
        "label": label,
        "tx_count": len(sigs),
        "parsed_count": len(parsed),
        "usdc_micropayments": len(transfers),
    }
    log(f"  {len(sigs)} txs, {len(transfers)} USDC micropayments")
    return transfers, summary


# ================================================================
# Strategy 3: Well-Known x402 Discovery
# ================================================================

WELL_KNOWN_PATHS = [
    "/.well-known/x402",
    "/.well-known/x402.json",
    "/x402",
]

def discover_well_known(base_urls):
    """Check well-known paths for x402 configuration."""
    found = []
    for base in base_urls:
        base = base.rstrip("/")
        for path in WELL_KNOWN_PATHS:
            url = base + path
            try:
                resp = requests.get(url, timeout=10, allow_redirects=True)
                if resp.status_code in (200, 402):
                    try:
                        data = resp.json()
                        if "accepts" in data or "x402Version" in data:
                            found.append({"url": url, "data": data})
                            log(f"  Found x402 config at {url}")
                    except json.JSONDecodeError:
                        pass
            except Exception:
                pass
            time.sleep(0.3)
    return found


# ================================================================
# Output
# ================================================================

def save_results(output_path, endpoints, wallet_scans, transfers, scan_time):
    """Save scan results to JSON."""
    all_wallets = set()
    all_providers = set()
    for ep in endpoints:
        for w in ep.get("solana_wallets", []):
            all_wallets.add(w)
        m = re.match(r"https?://([^/]+)", ep.get("url", ""))
        if m:
            all_providers.add(m.group(1))

    results = {
        "scan_metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scanner_version": "1.0.0",
            "scan_duration_seconds": round(scan_time, 1),
        },
        "summary": {
            "total_solana_endpoints": len(endpoints),
            "unique_solana_wallets": len(all_wallets),
            "unique_providers": len(all_providers),
            "usdc_micropayments_found": len(transfers),
        },
        "wallets": sorted(all_wallets),
        "providers": sorted(all_providers),
        "wallet_scans": wallet_scans,
    }

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    log(f"Results saved to {output_path}")
    return results


# ================================================================
# Main
# ================================================================

def main():
    parser = argparse.ArgumentParser(description="Solana x402 Endpoint Scanner")
    parser.add_argument("--db", default="/root/x402-network-mapper/mapper.db",
                        help="Path to mapper SQLite database")
    parser.add_argument("--output", default="scan-results.json",
                        help="Output JSON file path")
    parser.add_argument("--probe-only", action="store_true",
                        help="Only probe endpoints, skip on-chain scanning")
    parser.add_argument("--scan-wallets", action="store_true",
                        help="Scan discovered wallets on-chain (requires HELIUS_API_KEY)")
    args = parser.parse_args()

    log("=" * 60)
    log("Solana x402 Endpoint Scanner v1.0.0")
    log("SmartFlow Agent Payment Intelligence")
    log("=" * 60)

    start = time.time()
    all_endpoints = []
    all_transfers = []
    wallet_scans = []

    # Strategy 1: Load from mapper DB
    if os.path.exists(args.db):
        db_endpoints = discover_from_mapper_db(args.db)
        all_endpoints.extend(db_endpoints)

    # Strategy 2: Probe known endpoints for fresh data
    log("\n--- Probing known x402 endpoints ---")
    known_urls = [
        "https://helius.api.corbits.dev/",
        "https://api.logos.readia.io",
        "https://x402.alchemy.com",
        "https://x402.quicknode.com",
    ]
    for url in known_urls:
        result = probe_endpoint(url)
        if result.get("is_x402") and result.get("solana_wallets"):
            log(f"  CONFIRMED: {url} (Solana wallets: {len(result['solana_wallets'])})")
        time.sleep(0.5)

    # Strategy 3: On-chain scanning (if requested)
    if args.scan_wallets and HELIUS_API_KEY:
        log("\n--- On-chain wallet scanning ---")
        seen_wallets = set()
        for ep in all_endpoints:
            for w in ep.get("solana_wallets", []):
                if w not in seen_wallets:
                    seen_wallets.add(w)
                    transfers, summary = scan_wallet_transactions(w)
                    all_transfers.extend(transfers)
                    wallet_scans.append(summary)
    elif args.scan_wallets:
        log("WARNING: HELIUS_API_KEY not set, skipping on-chain scanning")

    duration = time.time() - start
    results = save_results(args.output, all_endpoints, wallet_scans, all_transfers, duration)

    # Summary
    log("")
    log("=" * 60)
    log(f"SCAN COMPLETE in {round(duration, 1)}s")
    log("=" * 60)
    log(f"Solana x402 endpoints:  {results['summary']['total_solana_endpoints']}")
    log(f"Unique Solana wallets:  {results['summary']['unique_solana_wallets']}")
    log(f"Unique providers:       {results['summary']['unique_providers']}")
    log(f"USDC micropayments:     {results['summary']['usdc_micropayments_found']}")
    log(f"Output: {args.output}")


if __name__ == "__main__":
    main()
