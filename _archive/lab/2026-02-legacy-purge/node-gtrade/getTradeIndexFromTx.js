#!/usr/bin/env node
/**
 * Extract trade index from MarketExecuted event
 *
 * This is a workaround for SDK.getUserTrades() not working on testnet
 */

import { JsonRpcProvider, AbiCoder } from 'ethers';

const TX_HASH = process.argv[2];
const RPC_URL = process.env.RPC_URL || "https://sepolia-rollup.arbitrum.io/rpc";

// MarketExecuted event signature
const MARKET_EXECUTED_TOPIC = "0x170ae993ffa82f60cce26e128cf75e11b7deba03fe29685e5881a76c8452765c";

async function main() {
  if (!TX_HASH) {
    console.error("Usage: node getTradeIndexFromTx.js <TX_HASH>");
    process.exit(1);
  }

  console.error(`\n🔍 Extracting trade index from: ${TX_HASH}\n`);

  const provider = new JsonRpcProvider(RPC_URL);
  const receipt = await provider.getTransactionReceipt(TX_HASH);

  if (!receipt) {
    console.error("❌ Transaction not found");
    process.exit(1);
  }

  if (receipt.status !== 1) {
    console.error("❌ Transaction failed");
    process.exit(1);
  }

  // Find MarketExecuted event
  const marketExecutedLog = receipt.logs.find(log =>
    log.topics[0] === MARKET_EXECUTED_TOPIC
  );

  if (!marketExecutedLog) {
    console.error("❌ No MarketExecuted event found!");
    process.exit(1);
  }

  console.error("✅ Found MarketExecuted event\n");

  // The event data structure (from gTrade contracts):
  // event MarketExecuted(
  //   Id orderId,      // Request ID (bytes32, address, uint32)
  //   Trade trade,     // Trade struct with index, user, pairIndex, etc.
  //   bool open,
  //   uint64 price,
  //   uint64 priceImpactP,
  //   int256 percentProfit,
  //   uint256 amountSentToTrader,
  //   string orderType
  // )

  const data = marketExecutedLog.data;
  console.error(`Data length: ${data.length} bytes`);
  console.error(`Data (hex): ${data.substring(0, 200)}...\n`);

  // Try to decode as tuple
  const abiCoder = AbiCoder.defaultAbiCoder();

  try {
    // The data is ABI-encoded tuple
    // First 32 bytes offset, then actual data

    // Simple approach: Extract bytes that look like trade index
    // Trade struct usually has index as first or second field (uint32)

    // Skip first 32 bytes (offset pointer), then orderId (96 bytes)
    // Then trade struct starts

    const dataHex = data.substring(2); // Remove 0x

    // Parse as raw bytes and look for patterns
    console.error("Attempting to decode trade data...\n");

    // Log raw bytes in chunks for manual inspection
    for (let i = 0; i < Math.min(dataHex.length, 640); i += 64) {
      const chunk = dataHex.substring(i, i + 64);
      const decimal = parseInt(chunk, 16);
      console.error(`[${(i / 2).toString().padStart(3)}] ${chunk} = ${decimal}`);
    }

  } catch (error) {
    console.error(`Decode error: ${error.message}`);
  }

  console.error("\n⚠️  Trade index extraction requires ABI knowledge");
  console.error("    Check gTrade contracts for exact Trade struct layout");
  console.error("    Or use gTrade SDK's decodeMarketExecuted if available\n");

  const output = {
    success: true,
    txHash: TX_HASH,
    hasMarketExecuted: true,
    note: "Trade index extraction requires full ABI decoding",
    dataPreview: data.substring(0, 200)
  };

  console.log(JSON.stringify(output, null, 2));
}

main().catch(err => {
  console.error("Error:", err.message);
  process.exit(1);
});
