#!/usr/bin/env node
/**
 * Check transaction events to debug why position isn't found
 */

import { JsonRpcProvider } from 'ethers';

const TX_HASH = process.argv[2];
const RPC_URL = process.env.RPC_URL || "https://sepolia-rollup.arbitrum.io/rpc";

if (!TX_HASH) {
  console.error("Usage: node checkTransaction.js <TX_HASH>");
  process.exit(1);
}

async function main() {
  const provider = new JsonRpcProvider(RPC_URL);

  console.error(`\n🔍 Checking transaction: ${TX_HASH}\n`);

  const receipt = await provider.getTransactionReceipt(TX_HASH);

  if (!receipt) {
    console.error("❌ Transaction not found");
    process.exit(1);
  }

  console.error(`Status: ${receipt.status === 1 ? '✅ SUCCESS' : '❌ FAILED'}`);
  console.error(`Block: ${receipt.blockNumber}`);
  console.error(`Gas used: ${receipt.gasUsed.toString()}`);
  console.error(`\nEvents (${receipt.logs.length} logs):\n`);

  receipt.logs.forEach((log, idx) => {
    console.error(`Log ${idx}:`);
    console.error(`  Address: ${log.address}`);
    console.error(`  Topics: ${log.topics.length}`);
    log.topics.forEach((topic, i) => {
      console.error(`    [${i}] ${topic}`);
    });
    console.error(`  Data: ${log.data.substring(0, 66)}...`);
    console.error();
  });

  // Output JSON
  const output = {
    success: receipt.status === 1,
    blockNumber: receipt.blockNumber,
    gasUsed: receipt.gasUsed.toString(),
    logs: receipt.logs.map(log => ({
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
