#!/usr/bin/env node
/**
 * List Open Trades
 *
 * Mostra totes les posicions obertes del wallet
 */

import { TradingSDK, SupportedChainId } from '@gainsnetwork/trading-sdk';

async function main() {
  const walletAddress = process.argv[2] || process.env.WALLET_ADDRESS || "0xD9fC17C093614D20976EFb1535A7142081A031b2";
  const rpcUrl = process.env.RPC_URL || "https://sepolia-rollup.arbitrum.io/rpc";

  console.error("📊 Listing Open Trades");
  console.error("=".repeat(80));
  console.error(`Wallet: ${walletAddress}`);
  console.error(`RPC: ${rpcUrl}`);
  console.error();

  try {
    // Initialize SDK (read-only)
    console.error("🔧 Initializing SDK...");
    const sdk = new TradingSDK({
      chainId: SupportedChainId.ArbitrumSepolia,
      rpcProviderUrl: rpcUrl
    });

    await sdk.initialize();
    console.error("✅ SDK initialized");
    console.error();

    // Get user trades
    console.error("📡 Fetching trades...");
    const trades = await sdk.getUserTrades(walletAddress);
    console.error(`✅ Found ${trades.length} trades`);
    console.error();

    // Output JSON to stdout
    const output = {
      success: true,
      wallet: walletAddress,
      totalTrades: trades.length,
      trades: trades.map(trade => ({
        index: trade.trade.index,
        pairIndex: trade.trade.pairIndex,
        direction: trade.trade.long ? 'LONG' : 'SHORT',
        collateral: Number(trade.trade.collateralAmount) / 1e6,  // USDC has 6 decimals
        leverage: trade.trade.leverage / 1000,
        openPrice: trade.trade.openPrice / 1e10,
        isOpen: trade.trade.isOpen,
        tp: trade.trade.tp / 1e10,
        sl: trade.trade.sl / 1e10
      }))
    };

    console.log(JSON.stringify(output, null, 2));

    // Show summary in stderr
    console.error();
    console.error("📋 Summary:");
    output.trades.forEach((trade, i) => {
      console.error(`${i + 1}. Trade #${trade.index} - ${getPairName(trade.pairIndex)} ${trade.direction}`);
      console.error(`   Collateral: $${trade.collateral} @ ${trade.leverage}x`);
      console.error(`   Open Price: $${trade.openPrice.toFixed(2)}`);
      console.error(`   Status: ${trade.isOpen ? '🟢 OPEN' : '🔴 CLOSED'}`);
    });

  } catch (error) {
    console.error();
    console.error("❌ Error:", error.message);

    const output = {
      success: false,
      error: error.message
    };
    console.log(JSON.stringify(output, null, 2));
    process.exit(1);
  }
}

function getPairName(pairIndex) {
  const pairs = {
    0: 'BTCUSD',
    1: 'ETHUSD',
    2: 'LINKUSD'
  };
  return pairs[pairIndex] || `PAIR${pairIndex}`;
}

main();
