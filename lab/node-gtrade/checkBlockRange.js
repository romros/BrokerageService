#!/usr/bin/env node
/**
 * Check if position was auto-closed by looking at block range
 */

import { JsonRpcProvider } from 'ethers';

const START_BLOCK = parseInt(process.argv[2]);
const END_BLOCK = parseInt(process.argv[3] || START_BLOCK + 10);
const RPC_URL = process.env.RPC_URL || "https://sepolia-rollup.arbitrum.io/rpc";

// gTrade Diamond address
const GTRADE_DIAMOND = "0xd659a15812064C79E189fd950A189b15c75d3186";

async function main() {
  const provider = new JsonRpcProvider(RPC_URL);

  console.error(`\n🔍 Checking blocks ${START_BLOCK} to ${END_BLOCK} for gTrade events\n`);

  for (let block = START_BLOCK; block <= END_BLOCK; block++) {
    const blockData = await provider.getBlock(block, true);

    if (!blockData || !blockData.transactions) continue;

    const gtradeTxs = blockData.transactions.filter(tx =>
      tx.to && tx.to.toLowerCase() === GTRADE_DIAMOND.toLowerCase()
    );

    if (gtradeTxs.length > 0) {
      console.error(`Block ${block}: ${gtradeTxs.length} gTrade tx(s)`);

      for (const tx of gtradeTxs) {
        const receipt = await provider.getTransactionReceipt(tx.hash);
        console.error(`  Tx: ${tx.hash.substring(0, 10)}...`);
        console.error(`  From: ${tx.from}`);
        console.error(`  Logs: ${receipt.logs.length}`);
      }
      console.error();
    }
  }

  console.log(JSON.stringify({ success: true, checked: `${START_BLOCK}-${END_BLOCK}` }));
}

main().catch(err => {
  console.error("Error:", err.message);
  process.exit(1);
});
