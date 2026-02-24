#!/usr/bin/env node
/**
 * Query trades DIRECTLY from contract (bypass SDK)
 *
 * This bypasses SDK.getUserTrades() to see if positions exist on-chain
 */

import { JsonRpcProvider, Contract } from 'ethers';

const WALLET_ADDRESS = process.argv[2] || "0xD9fC17C093614D20976EFb1535A7142081A031b2";
const RPC_URL = process.env.RPC_URL || "https://sepolia-rollup.arbitrum.io/rpc";

// gTrade Diamond contract address
const DIAMOND_ADDRESS = "0xd659a15812064C79E189fd950A189b15c75d3186";

// Minimal ABI for getUserTrades function
// Based on ITradingStorage interface
const MINIMAL_ABI = [
  "function getTrades(address) external view returns (tuple(address user, uint32 index, uint16 pairIndex, uint24 leverage, bool long, bool isOpen, uint8 collateralIndex, uint8 tradeType, uint120 collateralAmount, uint64 openPrice, uint64 tp, uint64 sl, uint192 __placeholder)[] memory)",
];

async function main() {
  console.error(`\n🔍 Querying contract directly\n`);
  console.error(`Contract: ${DIAMOND_ADDRESS}`);
  console.error(`Wallet: ${WALLET_ADDRESS}\n`);

  try {
    const provider = new JsonRpcProvider(RPC_URL);
    const contract = new Contract(DIAMOND_ADDRESS, MINIMAL_ABI, provider);

    console.error("Calling getTrades()...\n");

    const trades = await contract.getTrades(WALLET_ADDRESS);

    console.error(`✅ Found ${trades.length} trades\n`);

    trades.forEach((trade, idx) => {
      console.error(`Trade ${idx}:`);
      console.error(`  Index: ${trade.index}`);
      console.error(`  Pair: ${trade.pairIndex}`);
      console.error(`  Open: ${trade.isOpen}`);
      console.error(`  Long: ${trade.long}`);
      console.error(`  Collateral: ${trade.collateralAmount.toString()}`);
      console.error(`  Leverage: ${trade.leverage}`);
      console.error();
    });

    const openTrades = trades.filter(t => t.isOpen);
    console.error(`Open trades: ${openTrades.length}\n`);

    const output = {
      success: true,
      totalTrades: trades.length,
      openTrades: openTrades.length,
      trades: trades.map(t => ({
        index: Number(t.index),
        pairIndex: Number(t.pairIndex),
        isOpen: t.isOpen,
        long: t.long,
        collateral: t.collateralAmount.toString(),
        leverage: Number(t.leverage)
      }))
    };

    console.log(JSON.stringify(output, null, 2));

  } catch (error) {
    console.error("❌ Error:", error.message);

    // Try to decode error
    if (error.message.includes("execution reverted")) {
      console.error("\n⚠️  Contract call reverted - function signature might be wrong");
    }

    const output = {
      success: false,
      error: error.message
    };
    console.log(JSON.stringify(output, null, 2));
    process.exit(1);
  }
}

main();
