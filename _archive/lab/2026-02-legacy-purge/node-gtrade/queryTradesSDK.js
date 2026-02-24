#!/usr/bin/env node
/**
 * Query trades using @gainsnetwork/sdk (general SDK)
 *
 * This SDK has better utilities for querying trades than trading-sdk
 */

import { JsonRpcProvider } from 'ethers';
import { fetchOpenPairTrades, getContractsForChain, ChainId } from '@gainsnetwork/sdk';

const WALLET_ADDRESS = process.argv[2] || "0xD9fC17C093614D20976EFb1535A7142081A031b2";
const RPC_URL = process.env.RPC_URL || "https://sepolia-rollup.arbitrum.io/rpc";
const CHAIN_ID = ChainId.ARBITRUM_SEPOLIA; // Use ChainId enum from SDK

async function main() {
  console.error(`\n📡 Querying trades using @gainsnetwork/sdk\n`);
  console.error(`Wallet: ${WALLET_ADDRESS}`);
  console.error(`Chain: Arbitrum Sepolia (${CHAIN_ID})\n`);

  try {
    const provider = new JsonRpcProvider(RPC_URL);

    // Create contracts object using SDK helper
    console.error("Creating contracts...");
    const contracts = getContractsForChain(CHAIN_ID, provider);
    console.error("✅ Contracts created\n");

    console.error("Fetching open trades...\n");

    const trades = await fetchOpenPairTrades(contracts, {
      traders: [WALLET_ADDRESS],
      // includeOrders: true,  // Optional
      // blockTag: 'latest'
    });

    console.error(`✅ Found ${trades.length} trades\n`);

    trades.forEach((tradeContainer, idx) => {
      console.error(`Trade ${idx}:`);
      console.error(`  Index: ${tradeContainer.trade?.index || 'N/A'}`);
      console.error(`  Pair: ${tradeContainer.trade?.pairIndex || 'N/A'}`);
      console.error(`  Open: ${tradeContainer.trade?.isOpen || 'N/A'}`);
      console.error(`  Long: ${tradeContainer.trade?.long || 'N/A'}`);
      console.error();
    });

    const output = {
      success: true,
      totalTrades: trades.length,
      trades: trades.map(tc => ({
        index: tc.trade?.index,
        pairIndex: tc.trade?.pairIndex,
        isOpen: tc.trade?.isOpen,
        long: tc.trade?.long,
        collateral: tc.trade?.collateralAmount?.toString(),
        leverage: tc.trade?.leverage
      }))
    };

    console.log(JSON.stringify(output, null, 2));

  } catch (error) {
    console.error("❌ Error:", error.message);
    console.error(error.stack);

    const output = {
      success: false,
      error: error.message
    };
    console.log(JSON.stringify(output, null, 2));
    process.exit(1);
  }
}

main();
