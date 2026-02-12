#!/usr/bin/env node
/**
 * Decode MarketExecuted event from transaction to get trade index
 */

import { JsonRpcProvider, Interface } from 'ethers';

const TX_HASH = process.argv[2];
const RPC_URL = process.env.RPC_URL || "https://sepolia-rollup.arbitrum.io/rpc";

// MarketExecuted event signature from gTrade
// event MarketExecuted(ITradingStorage.Id orderId, IOrdersProcessor.Trade trade, ...)
const MARKET_EXECUTED_TOPIC = "0x170ae993ffa82f60cce26e128cf75e11b7deba03fe29685e5881a76c8452765c";

async function main() {
  if (!TX_HASH) {
    console.error("Usage: node decodeMarketExecuted.js <TX_HASH>");
    process.exit(1);
  }

  console.error(`\n🔍 Decoding events from: ${TX_HASH}\n`);

  const provider = new JsonRpcProvider(RPC_URL);
  const receipt = await provider.getTransactionReceipt(TX_HASH);

  if (!receipt) {
    console.error("❌ Transaction not found");
    process.exit(1);
  }

  console.error(`Status: ${receipt.status === 1 ? '✅ SUCCESS' : '❌ FAILED'}`);
  console.error(`Logs: ${receipt.logs.length}\n`);

  // Find MarketExecuted event
  const marketExecutedLogs = receipt.logs.filter(log =>
    log.topics[0] === MARKET_EXECUTED_TOPIC
  );

  console.error(`MarketExecuted events found: ${marketExecutedLogs.length}\n`);

  if (marketExecutedLogs.length === 0) {
    console.error("❌ No MarketExecuted event found!");
    console.error("\nAll topics:");
    receipt.logs.forEach((log, idx) => {
      console.error(`Log ${idx}: ${log.topics[0]}`);
    });
    process.exit(1);
  }

  marketExecutedLogs.forEach((log, idx) => {
    console.error(`\nMarketExecuted Event ${idx}:`);
    console.error(`  Topics: ${log.topics.length}`);
    log.topics.forEach((topic, i) => {
      console.error(`    [${i}] ${topic}`);
    });
    console.error(`  Data length: ${log.data.length} bytes`);
    console.error(`  Data: ${log.data.substring(0, 200)}...`);
  });

  const output = {
    success: receipt.status === 1,
    txHash: TX_HASH,
    marketExecutedEvents: marketExecutedLogs.length,
    logs: marketExecutedLogs.map(log => ({
      address: log.address,
      topics: log.topics,
      data: log.data
    }))
  };

  console.log(JSON.stringify(output, null, 2));
}

main().catch(err => {
  console.error("Error:", err.message);
  process.exit(1);
});
