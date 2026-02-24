#!/usr/bin/env node
/**
 * Close ALL Open Trades
 *
 * Tanca totes les posicions obertes del wallet
 *
 * Usage:
 *   E2E_TESTNET=1 ENABLE_LIVE_TRADING=1 \
 *   WALLET_MNEMONIC="..." \
 *   node closeAllTrades.js
 */

import { TradingSDK, SupportedChainId } from '@gainsnetwork/trading-sdk';
import { Wallet } from 'ethers';

async function main() {
  console.error("\n" + "=".repeat(80));
  console.error("🔴 CLOSE ALL OPEN TRADES (Testnet)");
  console.error("=".repeat(80));
  console.error();

  // Safety checks
  if (process.env.E2E_TESTNET !== '1') {
    console.error("❌ E2E_TESTNET not set");
    process.exit(1);
  }

  if (process.env.ENABLE_LIVE_TRADING !== '1') {
    console.error("❌ ENABLE_LIVE_TRADING not set");
    process.exit(1);
  }

  const mnemonic = process.env.WALLET_MNEMONIC;
  if (!mnemonic) {
    console.error("❌ WALLET_MNEMONIC not set");
    process.exit(1);
  }

  const rpcUrl = process.env.RPC_URL || "https://sepolia-rollup.arbitrum.io/rpc";

  try {
    // Create wallet
    console.error("🔐 Loading wallet...");
    const wallet = Wallet.fromPhrase(mnemonic);
    console.error(`   Address: ${wallet.address}`);
    console.error();

    // Initialize SDK
    console.error("🔧 Initializing SDK...");
    const { JsonRpcProvider } = await import('ethers');
    const provider = new JsonRpcProvider(rpcUrl);
    const connectedWallet = wallet.connect(provider);

    const sdk = new TradingSDK({
      chainId: SupportedChainId.ArbitrumSepolia,
      signer: connectedWallet,
      rpcProviderUrl: rpcUrl
    });

    await sdk.initialize();
    console.error("✅ SDK initialized");
    console.error();

    // Get open trades
    console.error("📡 Fetching open trades...");
    const allTrades = await sdk.getUserTrades(wallet.address);
    const openTrades = allTrades.filter(t => t.trade.isOpen);

    console.error(`   Total trades: ${allTrades.length}`);
    console.error(`   Open trades: ${openTrades.length}`);
    console.error();

    if (openTrades.length === 0) {
      console.error("✅ No open trades to close");
      const output = {
        success: true,
        closedTrades: []
      };
      console.log(JSON.stringify(output, null, 2));
      return;
    }

    // Show trades to close
    console.error("📋 Trades to close:");
    openTrades.forEach((trade, i) => {
      const pairName = getPairName(trade.trade.pairIndex);
      const direction = trade.trade.long ? 'LONG' : 'SHORT';
      const collateral = Number(trade.trade.collateralAmount) / 1e6;
      const leverage = trade.trade.leverage / 1000;
      const openPrice = trade.trade.openPrice / 1e10;

      console.error(`   ${i + 1}. Trade #${trade.trade.index} - ${pairName} ${direction}`);
      console.error(`      Collateral: $${collateral} @ ${leverage}x`);
      console.error(`      Open Price: $${openPrice.toFixed(2)}`);
    });
    console.error();

    // Confirm
    const readline = await import('readline');
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stderr
    });

    const answer = await new Promise(resolve => {
      rl.question(`⚠️  Close ALL ${openTrades.length} trades? [y/N]: `, resolve);
    });
    rl.close();

    if (answer.toLowerCase() !== 'y') {
      console.error("❌ Aborted");
      process.exit(1);
    }

    console.error();

    // Close each trade
    const results = [];
    for (let i = 0; i < openTrades.length; i++) {
      const trade = openTrades[i];
      const tradeIndex = trade.trade.index;

      console.error(`📤 Closing trade #${tradeIndex} (${i + 1}/${openTrades.length})...`);

      try {
        // Get current state for price
        const state = await sdk.getState();
        const oraclePrice = 70000.0; // TODO: get from state

        // Calculate expected price (inverse buffer for closing)
        const isLong = trade.trade.long;
        const buffer = isLong ? 0.95 : 1.05;  // Inverse for closing
        const expectedPrice = oraclePrice * buffer;

        console.error(`   Expected price: $${expectedPrice.toFixed(2)}`);

        // Close trade
        const closeArgs = {
          index: tradeIndex,
          expectedPrice: expectedPrice
        };

        const txHash = await sdk.write.closeTradeMarket(closeArgs);

        console.error(`   ✅ Transaction sent: ${txHash.hash}`);

        results.push({
          tradeIndex: tradeIndex,
          success: true,
          txHash: txHash.hash,
          explorer: `https://sepolia.arbiscan.io/tx/${txHash.hash}`
        });

      } catch (error) {
        console.error(`   ❌ Failed: ${error.message}`);

        results.push({
          tradeIndex: tradeIndex,
          success: false,
          error: error.message
        });
      }

      console.error();
    }

    // Output results
    const output = {
      success: true,
      closedTrades: results
    };

    console.log(JSON.stringify(output, null, 2));

    console.error("=".repeat(80));
    console.error("✅ DONE");
    console.error("=".repeat(80));

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
