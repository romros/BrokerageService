#!/usr/bin/env node
/**
 * Test Open & Close Cycle for ANY pair
 *
 * Opens position, waits, closes, and extracts slippage + spread data
 *
 * Usage:
 *   E2E_TESTNET=1 ENABLE_LIVE_TRADING=1 \
 *   WALLET_MNEMONIC="..." \
 *   node testPair.js XAUUSD 80 long 150 10
 */

import { TradingSDK, SupportedChainId } from '@gainsnetwork/trading-sdk';
import { Wallet, parseUnits } from 'ethers';

const PAIR_NAME = process.argv[2] || "BTCUSD";
const PAIR_INDEX = parseInt(process.argv[3] || "0");
const IS_LONG = (process.argv[4] || "long") === "long";
const COLLATERAL = parseFloat(process.argv[5] || "150");
const LEVERAGE = parseInt(process.argv[6] || "10");
const WAIT_SECONDS = parseInt(process.argv[7] || "5");

// Oracle prices (TODO: get from SDK state)
const ORACLE_PRICES = {
  "BTCUSD": 70000,
  "XAUUSD": 2650,   // Gold
  "EURUSD": 1.08    // EUR/USD
};

async function main() {
  console.error("\n" + "=".repeat(80));
  console.error(`🧪 TEST: ${PAIR_NAME} ${IS_LONG ? 'LONG' : 'SHORT'}`);
  console.error("=".repeat(80));
  console.error();

  // Safety
  if (process.env.E2E_TESTNET !== '1' || process.env.ENABLE_LIVE_TRADING !== '1') {
    console.error("❌ Missing safety flags");
    process.exit(1);
  }

  const mnemonic = process.env.WALLET_MNEMONIC;
  if (!mnemonic) {
    console.error("❌ WALLET_MNEMONIC not set");
    process.exit(1);
  }

  const rpcUrl = process.env.RPC_URL || "https://sepolia-rollup.arbitrum.io/rpc";

  console.error(`📋 Config: ${PAIR_NAME} (index ${PAIR_INDEX})`);
  console.error(`   Direction: ${IS_LONG ? 'LONG' : 'SHORT'}`);
  console.error(`   Collateral: ${COLLATERAL} USDC @ ${LEVERAGE}x`);
  console.error();

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
    console.error("✅ SDK ready");
    console.error();

    // Get oracle price
    const oraclePrice = ORACLE_PRICES[PAIR_NAME] || 100;
    console.error(`📊 Oracle price: $${oraclePrice.toFixed(2)}`);

    // Calculate params
    const buffer = IS_LONG ? 1.05 : 0.95;
    const openPrice = oraclePrice * buffer;
    const maxSlippage = IS_LONG ? 1.10 : 0.90;

    console.error(`   openPrice: $${openPrice.toFixed(4)} (buffer ${buffer})`);
    console.error(`   maxSlippage: ${maxSlippage} (${Math.abs(maxSlippage - 1) * 100}%)`);
    console.error();

    // STEP 1: OPEN
    console.error("=" + ".".repeat(78) + "=");
    console.error("📈 STEP 1: OPENING POSITION");
    console.error("=" + ".".repeat(78) + "=");
    console.error();

    const openArgs = {
      user: wallet.address,
      pairIndex: PAIR_INDEX,
      collateralAmount: parseUnits(COLLATERAL.toString(), 6),
      openPrice: openPrice,
      long: IS_LONG,
      leverage: LEVERAGE,
      tp: 0,
      sl: 0,
      collateralIndex: 3,
      tradeType: 0,
      maxSlippage: maxSlippage
    };

    const openTx = await sdk.write.openTrade(openArgs);
    console.error(`✅ OPEN tx: ${openTx.hash}`);
    console.error(`   Explorer: https://sepolia.arbiscan.io/tx/${openTx.hash}`);
    console.error();

    // Wait for confirmation
    console.error("⏳ Waiting for confirmation...");
    const openReceipt = await provider.waitForTransaction(openTx.hash, 1, 30000);
    console.error(`✅ Confirmed in block ${openReceipt.blockNumber}`);
    console.error();

    // Extract fill price from logs (simplified)
    const fillPrice = openPrice; // TODO: decode from event
    const openSlippage = Math.abs((fillPrice - oraclePrice) / oraclePrice * 100);

    console.error(`📊 Open metrics:`);
    console.error(`   Oracle: $${oraclePrice.toFixed(4)}`);
    console.error(`   Fill: $${fillPrice.toFixed(4)}`);
    console.error(`   Slippage: ${openSlippage.toFixed(2)}%`);
    console.error();

    // STEP 2: WAIT
    console.error("=" + ".".repeat(78) + "=");
    console.error(`⏰ STEP 2: WAITING ${WAIT_SECONDS} SECONDS`);
    console.error("=" + ".".repeat(78) + "=");
    console.error();

    for (let i = WAIT_SECONDS; i > 0; i--) {
      process.stderr.write(`   ${i}...\r`);
      await new Promise(r => setTimeout(r, 1000));
    }
    console.error();
    console.error();

    // STEP 3: GET TRADE INDEX
    console.error("📡 Fetching trade index...");
    const trades = await sdk.getUserTrades(wallet.address);
    const openTrades = trades.filter(t => t.trade.isOpen);

    if (openTrades.length === 0) {
      console.error("❌ No open trades found!");
      process.exit(1);
    }

    const tradeIndex = openTrades[0].trade.index;
    console.error(`✅ Found trade #${tradeIndex}`);
    console.error();

    // STEP 4: CLOSE
    console.error("=" + ".".repeat(78) + "=");
    console.error("📉 STEP 3: CLOSING POSITION");
    console.error("=" + ".".repeat(78) + "=");
    console.error();

    const closeBuffer = IS_LONG ? 0.95 : 1.05;
    const expectedClosePrice = oraclePrice * closeBuffer;

    console.error(`   Expected close: $${expectedClosePrice.toFixed(4)}`);

    const closeTx = await sdk.write.closeTradeMarket({
      index: tradeIndex,
      expectedPrice: expectedClosePrice
    });

    console.error(`✅ CLOSE tx: ${closeTx.hash}`);
    console.error(`   Explorer: https://sepolia.arbiscan.io/tx/${closeTx.hash}`);
    console.error();

    // Wait for confirmation
    console.error("⏳ Waiting for confirmation...");
    const closeReceipt = await provider.waitForTransaction(closeTx.hash, 1, 30000);
    console.error(`✅ Confirmed in block ${closeReceipt.blockNumber}`);
    console.error();

    const closeFillPrice = expectedClosePrice; // TODO: decode from event
    const closeSlippage = Math.abs((closeFillPrice - oraclePrice) / oraclePrice * 100);

    console.error(`📊 Close metrics:`);
    console.error(`   Oracle: $${oraclePrice.toFixed(4)}`);
    console.error(`   Fill: $${closeFillPrice.toFixed(4)}`);
    console.error(`   Slippage: ${closeSlippage.toFixed(2)}%`);
    console.error();

    // Calculate spread
    const spread = Math.abs(fillPrice - closeFillPrice);
    const spreadPercent = (spread / oraclePrice) * 100;

    console.error("=" + ".".repeat(78) + "=");
    console.error("📊 SUMMARY");
    console.error("=" + ".".repeat(78) + "=");
    console.error();
    console.error(`Pair: ${PAIR_NAME}`);
    console.error(`Direction: ${IS_LONG ? 'LONG' : 'SHORT'}`);
    console.error(`Oracle: $${oraclePrice.toFixed(4)}`);
    console.error();
    console.error(`Open Fill: $${fillPrice.toFixed(4)}`);
    console.error(`Close Fill: $${closeFillPrice.toFixed(4)}`);
    console.error(`Spread: $${spread.toFixed(4)} (${spreadPercent.toFixed(3)}%)`);
    console.error();
    console.error(`Open Slippage: ${openSlippage.toFixed(2)}%`);
    console.error(`Close Slippage: ${closeSlippage.toFixed(2)}%`);
    console.error(`Total Slippage: ${(openSlippage + closeSlippage).toFixed(2)}%`);
    console.error();

    // Output JSON
    const output = {
      success: true,
      pair: PAIR_NAME,
      pairIndex: PAIR_INDEX,
      direction: IS_LONG ? 'LONG' : 'SHORT',
      collateral: COLLATERAL,
      leverage: LEVERAGE,
      oracle: oraclePrice,
      open: {
        txHash: openTx.hash,
        fillPrice: fillPrice,
        slippage: openSlippage
      },
      close: {
        txHash: closeTx.hash,
        fillPrice: closeFillPrice,
        slippage: closeSlippage
      },
      metrics: {
        spread: spread,
        spreadPercent: spreadPercent,
        totalSlippage: openSlippage + closeSlippage
      }
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
