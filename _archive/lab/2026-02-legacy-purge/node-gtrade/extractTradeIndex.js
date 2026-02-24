#!/usr/bin/env node
/**
 * Extract trade index from TradeInitialAccFeesStored event
 *
 * This event is emitted when a trade is opened and contains the trade index
 * Event signature:
 *   TradeInitialAccFeesStored(
 *     address indexed trader,
 *     uint32 indexed index,  // <-- This is what we need!
 *     uint8 collateralIndex,
 *     uint16 pairIndex,
 *     bool long,
 *     uint64 currentPairPrice,
 *     int128 newInitialAccFundingFeeP,
 *     uint128 newInitialAccBorrowingFeeP
 *   )
 */

import { JsonRpcProvider } from 'ethers';

const TX_HASH = process.argv[2];
const RPC_URL = process.env.RPC_URL || "https://sepolia-rollup.arbitrum.io/rpc";

// TradeInitialAccFeesStored event signature hash
const TRADE_FEES_STORED_TOPIC = "0xe2246a51b73f6ea7ff0fee771119006fb1c0040340321b0cef01749b7fc71c7a";

async function main() {
  if (!TX_HASH) {
    console.error("Usage: node extractTradeIndex.js <TX_HASH>");
    process.exit(1);
  }

  console.error(`\n🔍 Extracting trade index from: ${TX_HASH}\n`);

  const provider = new JsonRpcProvider(RPC_URL);
  const receipt = await provider.getTransactionReceipt(TX_HASH);

  if (!receipt) {
    console.error("❌ Transaction not found");
    const output = { success: false, error: "Transaction not found" };
    console.log(JSON.stringify(output, null, 2));
    process.exit(1);
  }

  if (receipt.status !== 1) {
    console.error("❌ Transaction failed");
    const output = { success: false, error: "Transaction failed" };
    console.log(JSON.stringify(output, null, 2));
    process.exit(1);
  }

  console.error(`✅ Transaction confirmed in block ${receipt.blockNumber}\n`);

  // Find TradeInitialAccFeesStored event
  const tradeFeesLog = receipt.logs.find(log =>
    log.topics[0] === TRADE_FEES_STORED_TOPIC
  );

  if (!tradeFeesLog) {
    console.error("❌ No TradeInitialAccFeesStored event found!");
    console.error("   This might not be an openTrade transaction\n");

    const output = {
      success: false,
      error: "No TradeInitialAccFeesStored event found"
    };
    console.log(JSON.stringify(output, null, 2));
    process.exit(1);
  }

  console.error("✅ Found TradeInitialAccFeesStored event\n");

  // Extract indexed parameters from topics:
  // topics[0] = event signature
  // topics[1] = trader (address)
  // topics[2] = index (uint32)
  const trader = "0x" + tradeFeesLog.topics[1].slice(26); // Remove padding
  const indexHex = tradeFeesLog.topics[2];
  const tradeIndex = parseInt(indexHex, 16);

  console.error(`Trader: ${trader}`);
  console.error(`Trade Index: ${tradeIndex}`);
  console.error();

  // Decode non-indexed parameters from data
  const data = tradeFeesLog.data;

  // Data layout (each 32 bytes):
  // [0-31]   collateralIndex (uint8)
  // [32-63]  pairIndex (uint16)
  // [64-95]  long (bool)
  // [96-127] currentPairPrice (uint64)
  // [128-159] newInitialAccFundingFeeP (int128)
  // [160-191] newInitialAccBorrowingFeeP (uint128)

  const collateralIndex = parseInt(data.slice(2, 66), 16);
  const pairIndex = parseInt(data.slice(66, 130), 16);
  const isLong = parseInt(data.slice(130, 194), 16) === 1;
  const currentPrice = parseInt(data.slice(194, 258), 16);

  console.error(`Details:`);
  console.error(`  Pair Index: ${pairIndex}`);
  console.error(`  Direction: ${isLong ? 'LONG' : 'SHORT'}`);
  console.error(`  Collateral Index: ${collateralIndex}`);
  console.error(`  Current Price: ${currentPrice}`);
  console.error();

  console.error(`✅ Trade index: ${tradeIndex}`);
  console.error();

  const output = {
    success: true,
    txHash: TX_HASH,
    tradeIndex: tradeIndex,
    trader: trader,
    pairIndex: pairIndex,
    isLong: isLong,
    collateralIndex: collateralIndex,
    currentPrice: currentPrice.toString(),
    blockNumber: receipt.blockNumber
  };

  console.log(JSON.stringify(output, null, 2));
}

main().catch(err => {
  console.error("Error:", err.message);
  const output = { success: false, error: err.message };
  console.log(JSON.stringify(output, null, 2));
  process.exit(1);
});
