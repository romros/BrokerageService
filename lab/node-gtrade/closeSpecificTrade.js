#!/usr/bin/env node
/**
 * Close specific trade by index
 */

import { TradingSDK, SupportedChainId } from '@gainsnetwork/trading-sdk';
import { Wallet } from 'ethers';

const TRADE_INDEX = parseInt(process.argv[2]);
const EXPECTED_PRICE = parseFloat(process.argv[3] || "0"); // 0 = market price

async function main() {
  if (isNaN(TRADE_INDEX)) {
    console.error("Usage: node closeSpecificTrade.js <TRADE_INDEX> [EXPECTED_PRICE]");
    process.exit(1);
  }

  console.error("\n" + "=".repeat(80));
  console.error(`🔴 CLOSE TRADE #${TRADE_INDEX}`);
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

    // Get trade info first
    const trades = await sdk.getUserTrades(wallet.address);
    const trade = trades.find(t => t.trade.index === TRADE_INDEX);

    if (!trade) {
      console.error(`❌ Trade #${TRADE_INDEX} not found`);
      process.exit(1);
    }

    console.error(`Trade #${TRADE_INDEX}:`);
    console.error(`  Pair: ${trade.trade.pairIndex}`);
    console.error(`  Long: ${trade.trade.long}`);
    console.error(`  Collateral: ${trade.trade.collateralAmount.toString()}`);
    console.error();

    // Close
    console.error("Closing position...\n");

    const closeTx = await sdk.write.closeTradeMarket({
      index: TRADE_INDEX,
      expectedPrice: EXPECTED_PRICE || 0
    });

    console.error(`✅ CLOSE tx: ${closeTx.hash}`);
    console.error(`   Explorer: https://sepolia.arbiscan.io/tx/${closeTx.hash}`);
    console.error();

    // Wait for confirmation
    console.error("⏳ Waiting for confirmation...");
    const receipt = await provider.waitForTransaction(closeTx.hash, 1, 30000);
    console.error(`✅ Confirmed in block ${receipt.blockNumber}\n`);

    const output = {
      success: true,
      tradeIndex: TRADE_INDEX,
      txHash: closeTx.hash,
      explorer: `https://sepolia.arbiscan.io/tx/${closeTx.hash}`,
      blockNumber: receipt.blockNumber
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
