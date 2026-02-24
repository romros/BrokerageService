#!/usr/bin/env node
/**
 * List all tradable pairs (maxLeverage > 1)
 */

import { TradingSDK, SupportedChainId } from '@gainsnetwork/trading-sdk';

const RPC_URL = process.env.RPC_URL || "https://sepolia-rollup.arbitrum.io/rpc";

async function main() {
  console.error(`\n📋 Finding all tradable pairs on Arbitrum Sepolia\n`);

  const sdk = new TradingSDK({
    chainId: SupportedChainId.ArbitrumSepolia,
    rpcProviderUrl: RPC_URL
  });

  await sdk.initialize();
  const state = await sdk.getState();

  console.error(`Total pairs: ${state.pairs.length}\n`);

  const tradable = state.pairs
    .filter(pair => state.maxPairLeverages[pair.pairIndex] > 1)
    .sort((a, b) => state.maxPairLeverages[b.pairIndex] - state.maxPairLeverages[a.pairIndex]);

  console.error(`Tradable pairs (leverage > 1): ${tradable.length}\n`);

  tradable.forEach((pair, idx) => {
    if (idx < 30) {  // Show first 30
      const maxLev = state.maxPairLeverages[pair.pairIndex];
      console.error(`[${pair.pairIndex.toString().padStart(3)}] ${pair.name.padEnd(20)} | Max: ${maxLev}x | Group: ${pair.groupIndex}`);
    }
  });

  if (tradable.length > 30) {
    console.error(`\n... and ${tradable.length - 30} more`);
  }

  const output = {
    success: true,
    totalPairs: state.pairs.length,
    tradablePairs: tradable.length,
    topPairs: tradable.slice(0, 20).map(p => ({
      index: p.pairIndex,
      name: p.name,
      maxLeverage: state.maxPairLeverages[p.pairIndex],
      group: p.groupIndex
    }))
  };

  console.log(JSON.stringify(output, null, 2));
}

main().catch(err => {
  console.error("Error:", err.message);
  process.exit(1);
});
