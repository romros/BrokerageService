#!/usr/bin/env node
/**
 * Check pair information to see if it's available/tradable
 */

import { TradingSDK, SupportedChainId } from '@gainsnetwork/trading-sdk';

const PAIR_INDEX = parseInt(process.argv[2] || "0");
const RPC_URL = process.env.RPC_URL || "https://sepolia-rollup.arbitrum.io/rpc";

async function main() {
  console.error(`\n📊 Checking pair index ${PAIR_INDEX}\n`);

  const sdk = new TradingSDK({
    chainId: SupportedChainId.ArbitrumSepolia,
    rpcProviderUrl: RPC_URL
  });

  await sdk.initialize();
  console.error("✅ SDK initialized\n");

  // Try to get pair info
  try {
    const state = await sdk.getState();

    // Check if we can access pair data
    console.error("SDK State keys:", Object.keys(state));
    console.error();

    // Try to find pair info
    if (state.pairs) {
      console.error(`Total pairs: ${state.pairs.length}`);

      if (PAIR_INDEX < state.pairs.length) {
        const pair = state.pairs[PAIR_INDEX];
        console.error(`\nPair ${PAIR_INDEX}:`);
        console.error(`  Name: ${pair.from}/${pair.to}`);
        console.error(`  Feed: ${pair.feed}`);
        console.error(`  Group: ${pair.groupIndex}`);
        console.error(JSON.stringify(pair, null, 2));
      } else {
        console.error(`❌ Pair index ${PAIR_INDEX} out of range (max: ${state.pairs.length - 1})`);
      }
    }

    // Check groups
    if (state.groups) {
      console.error(`\nTotal groups: ${state.groups.length}`);
    }

    const output = {
      success: true,
      pairIndex: PAIR_INDEX,
      pairsAvailable: state.pairs ? state.pairs.length : 0
    };

    console.log(JSON.stringify(output, null, 2));

  } catch (error) {
    console.error("Error accessing pair:", error.message);

    const output = {
      success: false,
      error: error.message
    };
    console.log(JSON.stringify(output, null, 2));
  }
}

main().catch(err => {
  console.error("Error:", err.message);
  process.exit(1);
});
