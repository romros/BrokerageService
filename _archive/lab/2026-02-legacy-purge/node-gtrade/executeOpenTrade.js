#!/usr/bin/env node
/**
 * EXECUTE REAL TRADE - Arbitrum Sepolia Testnet
 *
 * Aplica TOTS els descobriments:
 * - maxSlippage = MULTIPLICADOR (1.10 = 10% slippage)
 * - openPrice = oracle × buffer (1.05 per LONG)
 * - SDK oficial per generar transaction
 *
 * Safety:
 * - Requereix E2E_TESTNET=1
 * - Requereix ENABLE_LIVE_TRADING=1
 * - Confirmació manual abans d'enviar
 */

import { TradingSDK, SupportedChainId } from '@gainsnetwork/trading-sdk';
import { Wallet, parseUnits } from 'ethers';

// Config
const SYMBOL = "BTCUSD";
const COLLATERAL = 150.0;  // USDC
const LEVERAGE = 10;
const IS_LONG = true;

async function main() {
  console.error("\n" + "=".repeat(80));
  console.error("🚀 EXECUTE REAL TRADE (Testnet)");
  console.error("=".repeat(80));
  console.error();

  // Safety checks
  if (process.env.E2E_TESTNET !== '1') {
    console.error("❌ E2E_TESTNET not set");
    console.error("   This script executes REAL transactions.");
    console.error("   Set E2E_TESTNET=1 to confirm.");
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

  console.error("📋 Configuration:");
  console.error(`   Symbol: ${SYMBOL}`);
  console.error(`   Direction: ${IS_LONG ? 'LONG' : 'SHORT'}`);
  console.error(`   Collateral: ${COLLATERAL} USDC`);
  console.error(`   Leverage: ${LEVERAGE}x`);
  console.error(`   Position Size: $${COLLATERAL * LEVERAGE} USD`);
  console.error(`   RPC: ${rpcUrl}`);
  console.error();

  try {
    // Create wallet from mnemonic
    console.error("🔐 Loading wallet from mnemonic...");
    const wallet = Wallet.fromPhrase(mnemonic);
    console.error(`   Address: ${wallet.address}`);
    console.error();

    // Initialize SDK with signer
    console.error("🔧 Initializing gTrade SDK...");
    const sdk = new TradingSDK({
      chainId: SupportedChainId.ArbitrumSepolia,
      signer: wallet.connect(new (await import('ethers')).JsonRpcProvider(rpcUrl)),
      rpcProviderUrl: rpcUrl
    });

    await sdk.initialize();
    console.error("✅ SDK initialized");
    console.error();

    // Get state
    console.error("📊 Fetching market state...");
    const state = await sdk.getState();

    // Get oracle price (hardcoded for now - TODO: extract from state)
    const oraclePrice = 70000.0;
    console.error(`   Oracle price: $${oraclePrice.toFixed(2)}`);

    // Calculate openPrice with buffer (DESCOBRIMENT SDK)
    const buffer = IS_LONG ? 1.05 : 0.95;
    const openPrice = oraclePrice * buffer;

    // Calculate maxSlippage (MULTIPLICADOR - DESCOBRIMENT CRÍTIC!)
    const maxSlippage = IS_LONG ? 1.10 : 0.90;

    console.error(`   openPrice: $${openPrice.toFixed(2)} (buffer: ${buffer})`);
    console.error(`   maxSlippage: ${maxSlippage} (${Math.abs(maxSlippage - 1) * 100}%)`);
    console.error();

    // Build trade args
    const tradeArgs = {
      user: wallet.address,
      pairIndex: 0, // BTCUSD
      collateralAmount: parseUnits(COLLATERAL.toString(), 6), // USDC
      openPrice: openPrice,
      long: IS_LONG,
      leverage: LEVERAGE,
      tp: 0,
      sl: 0,
      collateralIndex: 3, // GNS_USDC Sepolia
      tradeType: 0, // Market
      maxSlippage: maxSlippage
    };

    console.error("📝 Trade parameters:");
    console.error(`   openPriceScaled: ${Math.round(openPrice * 1e10)}`);
    console.error(`   maxSlippageScaled: ${Math.floor(maxSlippage * 1000)}`);
    console.error(`   leverageScaled: ${Math.floor(LEVERAGE * 1000)}`);
    console.error(`   collateralScaled: ${parseUnits(COLLATERAL.toString(), 6).toString()}`);
    console.error();

    // Skip balance check - SDK will fail if insufficient
    console.error("⚠️  Skipping balance check (SDK will validate)")
    console.error();

    // Confirm execution
    console.error("⚠️  READY TO EXECUTE REAL TRANSACTION");
    console.error();
    console.error(`   Will open ${SYMBOL} ${IS_LONG ? 'LONG' : 'SHORT'}`);
    console.error(`   openPrice: $${openPrice.toFixed(2)}`);
    console.error(`   maxSlippage: ${maxSlippage} (${Math.abs(maxSlippage - 1) * 100}%)`);
    console.error();

    // Manual confirmation via stdin
    const readline = await import('readline');
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stderr
    });

    const answer = await new Promise(resolve => {
      rl.question("Continue? [y/N]: ", resolve);
    });
    rl.close();

    if (answer.toLowerCase() !== 'y') {
      console.error("❌ Aborted by user");
      process.exit(1);
    }

    console.error();
    console.error("📤 Sending transaction...");

    // Execute trade
    const txHash = await sdk.write.openTrade(tradeArgs);

    console.error();
    console.error("=".repeat(80));
    console.error("✅ TRANSACTION SENT!");
    console.error("=".repeat(80));
    console.error();

    // Output JSON to stdout
    const output = {
      success: true,
      txHash: txHash,
      explorer: `https://sepolia.arbiscan.io/tx/${txHash}`,
      trade: {
        pair: SYMBOL,
        direction: IS_LONG ? 'LONG' : 'SHORT',
        collateral: COLLATERAL,
        leverage: LEVERAGE,
        openPrice: openPrice,
        maxSlippage: maxSlippage
      }
    };

    console.log(JSON.stringify(output, null, 2));

    console.error();
    console.error("📝 Next steps:");
    console.error("   1. Check transaction on Arbiscan");
    console.error("   2. Wait for confirmation (~2 seconds)");
    console.error("   3. Verify position in gTrade UI");
    console.error();

  } catch (error) {
    console.error();
    console.error("=".repeat(80));
    console.error("❌ ERROR");
    console.error("=".repeat(80));
    console.error();
    console.error(`Error: ${error.message}`);

    const errorStr = error.message || error.toString();
    if (errorStr.includes("0x10906acb")) {
      console.error();
      console.error("💡 Price validation error!");
      console.error("   - openPrice might still be outside acceptable range");
      console.error("   - Or maxSlippage interpretation different");
    }

    // Output error JSON to stdout
    const output = {
      success: false,
      error: error.message,
      stack: error.stack
    };
    console.log(JSON.stringify(output, null, 2));

    process.exit(1);
  }
}

main();
