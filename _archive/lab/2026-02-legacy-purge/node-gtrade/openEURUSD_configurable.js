#!/usr/bin/env node
/**
 * Open EURUSD position with configurable parameters
 *
 * Usage: node openEURUSD_configurable.js <COLLATERAL> <LEVERAGE> <LONG|SHORT>
 */

import { TradingSDK, SupportedChainId } from '@gainsnetwork/trading-sdk';
import { Wallet, parseUnits } from 'ethers';

// Parse arguments
const COLLATERAL = parseFloat(process.argv[2] || "100");
const LEVERAGE = parseInt(process.argv[3] || "10");
const DIRECTION = (process.argv[4] || "LONG").toUpperCase();
const IS_LONG = DIRECTION === "LONG";

const PAIR_INDEX = 21;  // EURUSD
const PAIR_NAME = "EURUSD";

async function main() {
  console.error("\n" + "=".repeat(80));
  console.error(`🟢 OPEN ${PAIR_NAME} ${IS_LONG ? 'LONG' : 'SHORT'}`);
  console.error("=".repeat(80));
  console.error();

  // Safety checks
  if (process.env.E2E_TESTNET !== '1' || process.env.ENABLE_LIVE_TRADING !== '1') {
    console.error("❌ Safety flags not set");
    process.exit(1);
  }

  const mnemonic = process.env.WALLET_MNEMONIC;
  if (!mnemonic) {
    console.error("❌ WALLET_MNEMONIC not set");
    process.exit(1);
  }

  const rpcUrl = process.env.RPC_URL || "https://sepolia-rollup.arbitrum.io/rpc";

  try {
    // Setup
    const wallet = Wallet.fromPhrase(mnemonic);
    const { JsonRpcProvider } = await import('ethers');
    const provider = new JsonRpcProvider(rpcUrl);
    const connectedWallet = wallet.connect(provider);

    const sdk = new TradingSDK({
      chainId: SupportedChainId.ArbitrumSepolia,
      signer: connectedWallet,
      rpcProviderUrl: rpcUrl
    });

    await sdk.initialize();
    console.error("✅ SDK ready\n");

    // For EURUSD, use realistic price around 1.19
    const oraclePrice = 1.19;

    // Use SMALL spread like web (0.1%)
    // For SHORT: openPrice should be BELOW oracle (we sell at lower price)
    const buffer = IS_LONG ? 1.001 : 0.999;  // 0.1% buffer
    const openPrice = oraclePrice * buffer;

    // Max slippage: 1%
    // For SHORT: maxSlippage should be < 1 (can go lower)
    const maxSlippage = IS_LONG ? 1.01 : 0.99;

    console.error(`Config:`);
    console.error(`  Pair: ${PAIR_NAME} (index ${PAIR_INDEX})`);
    console.error(`  Direction: ${IS_LONG ? 'LONG ⬆️' : 'SHORT ⬇️'}`);
    console.error(`  Collateral: ${COLLATERAL} USDC @ ${LEVERAGE}x`);
    console.error(`  Position size: ${COLLATERAL * LEVERAGE} USDC`);
    console.error();
    console.error(`Pricing:`);
    console.error(`  Oracle: $${oraclePrice.toFixed(5)}`);
    console.error(`  Open price: $${openPrice.toFixed(5)} (${buffer}x)`);
    console.error(`  Max slippage: ${maxSlippage} (${Math.abs(maxSlippage - 1) * 100}%)`);
    console.error();

    if (!IS_LONG) {
      console.error(`🔻 SHORT strategy:`);
      console.error(`  - Sell at ${openPrice.toFixed(5)} (below oracle)`);
      console.error(`  - Profit if price goes DOWN`);
      console.error(`  - Max slippage: 0.99 (can go 1% lower)`);
      console.error();
    }

    // Open position
    console.error("Opening position...\n");

    const tradeArgs = {
      user: wallet.address,
      pairIndex: PAIR_INDEX,
      collateralAmount: parseUnits(COLLATERAL.toString(), 6),
      openPrice: openPrice,
      long: IS_LONG,
      leverage: LEVERAGE,
      tp: 0,  // No take profit
      sl: 0,  // No stop loss
      collateralIndex: 3,  // USDC
      tradeType: 0,  // Market order
      maxSlippage: maxSlippage
    };

    const openTx = await sdk.write.openTrade(tradeArgs);

    console.error(`✅ OPEN tx: ${openTx.hash}`);
    console.error(`   Explorer: https://sepolia.arbiscan.io/tx/${openTx.hash}`);
    console.error();

    // Wait for confirmation
    console.error("⏳ Waiting for confirmation...");
    const receipt = await provider.waitForTransaction(openTx.hash, 1, 60000);
    console.error(`✅ Confirmed in block ${receipt.blockNumber}\n`);

    // Wait a bit for indexing
    console.error("⏳ Waiting 5 seconds for indexing...\n");
    await new Promise(r => setTimeout(r, 5000));

    // Query trades
    console.error("📡 Querying open positions...\n");
    const trades = await sdk.getUserTrades(wallet.address);
    const openTrades = trades.filter(t => t.trade.isOpen);

    console.error(`Found ${openTrades.length} open trades\n`);

    let latestTrade = null;
    if (openTrades.length > 0) {
      latestTrade = openTrades[openTrades.length - 1]; // Latest
      console.error(`Latest trade:`);
      console.error(`  Index: ${latestTrade.trade.index}`);
      console.error(`  Pair: ${latestTrade.trade.pairIndex}`);
      console.error(`  Direction: ${latestTrade.trade.long ? 'LONG ⬆️' : 'SHORT ⬇️'}`);
      console.error(`  Collateral: ${latestTrade.trade.collateralAmount.toString()}`);
      console.error(`  Leverage: ${latestTrade.trade.leverage}x`);
      console.error();
    }

    const output = {
      success: true,
      pair: PAIR_NAME,
      pairIndex: PAIR_INDEX,
      direction: IS_LONG ? "LONG" : "SHORT",
      collateral: COLLATERAL,
      leverage: LEVERAGE,
      txHash: openTx.hash,
      explorer: `https://sepolia.arbiscan.io/tx/${openTx.hash}`,
      blockNumber: receipt.blockNumber,
      openTrades: openTrades.length,
      latestTradeIndex: latestTrade ? latestTrade.trade.index : null
    };

    console.log(JSON.stringify(output, null, 2));

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

main();
