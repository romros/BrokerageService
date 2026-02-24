#!/usr/bin/env node
/**
 * Find pair by name
 */

import { TradingSDK, SupportedChainId } from '@gainsnetwork/trading-sdk';

const SEARCH_TERM = (process.argv[2] || "BTC").toUpperCase();
const RPC_URL = process.env.RPC_URL || "https://sepolia-rollup.arbitrum.io/rpc";

async function main() {
  console.error(`\n🔍 Searching for pairs matching: ${SEARCH_TERM}\n`);

  const sdk = new TradingSDK({
    chainId: SupportedChainId.ArbitrumSepolia,
    rpcProviderUrl: RPC_URL
  });

  await sdk.initialize();
  const state = await sdk.getState();

  console.error(`Total pairs available: ${state.pairs.length}\n`);

  const matches = state.pairs.filter(pair =>
    pair.name.toUpperCase().includes(SEARCH_TERM) ||
    pair.from.toUpperCase().includes(SEARCH_TERM) ||
    pair.to.toUpperCase().includes(SEARCH_TERM)
  );

  console.error(`Found ${matches.length} matches:\n`);

  matches.forEach(pair => {
    console.error(`[${pair.pairIndex}] ${pair.name} (${pair.from}/${pair.to})`);
    console.error(`     Group: ${pair.groupIndex}, Spread: ${pair.spreadP}`);
    console.error(`     Max Leverage: ${state.maxPairLeverages[pair.pairIndex]}`);
    console.error();
  });

  const output = {
    success: true,
    searchTerm: SEARCH_TERM,
    matches: matches.map(p => ({
      index: p.pairIndex,
      name: p.name,
      from: p.from,
      to: p.to,
      maxLeverage: state.maxPairLeverages[p.pairIndex]
    }))
  };

  console.log(JSON.stringify(output, null, 2));
}

main().catch(err => {
  console.error("Error:", err.message);
  process.exit(1);
});
