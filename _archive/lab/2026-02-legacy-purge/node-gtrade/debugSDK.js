#!/usr/bin/env node
/**
 * Debug SDK initialization and state
 */

import { TradingSDK, SupportedChainId } from '@gainsnetwork/trading-sdk';

const RPC_URL = process.env.RPC_URL || "https://sepolia-rollup.arbitrum.io/rpc";

async function main() {
  console.error(`\n🔍 Debugging SDK initialization\n`);

  const sdk = new TradingSDK({
    chainId: SupportedChainId.ArbitrumSepolia,
    rpcProviderUrl: RPC_URL
  });

  console.error("SDK created, initializing...");

  await sdk.initialize();

  console.error("✅ SDK initialized\n");

  // Wait a bit for state to populate
  await new Promise(r => setTimeout(r, 2000));

  console.error("After 2 second wait:\n");

  const state = sdk.getState();

  console.error("State keys:", Object.keys(state));
  console.error("State type:", typeof state);
  console.error("State:", state);
  console.error();

  // Try to access different SDK properties
  console.error("SDK methods:", Object.getOwnPropertyNames(Object.getPrototypeOf(sdk)));
  console.error();

  // Check if there's a read interface
  if (sdk.read) {
    console.error("SDK.read exists");
    console.error("SDK.read methods:", Object.keys(sdk.read));
  }

  if (sdk.write) {
    console.error("SDK.write exists");
    console.error("SDK.write methods:", Object.keys(sdk.write));
  }

  console.log(JSON.stringify({ success: true, stateKeys: Object.keys(state) }, null, 2));
}

main().catch(err => {
  console.error("Error:", err.message);
  console.error(err.stack);
  process.exit(1);
});
