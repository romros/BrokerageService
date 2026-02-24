#!/usr/bin/env node
/**
 * Get all trades for wallet - with detailed debugging
 */

import { TradingSDK, SupportedChainId } from '@gainsnetwork/trading-sdk';
import { Wallet } from 'ethers';

const WALLET_ADDRESS = process.argv[2] || "0xD9fC17C093614D20976EFb1535A7142081A031b2";
const RPC_URL = process.env.RPC_URL || "https://sepolia-rollup.arbitrum.io/rpc";

async function main() {
  console.error(`\n📡 Querying trades for: ${WALLET_ADDRESS}\n`);

  const mnemonic = process.env.WALLET_MNEMONIC || "";

  let sdk;
  if (mnemonic) {
    const wallet = Wallet.fromPhrase(mnemonic);
    const { JsonRpcProvider } = await import('ethers');
    const provider = new JsonRpcProvider(RPC_URL);
    const connectedWallet = wallet.connect(provider);

    sdk = new TradingSDK({
      chainId: SupportedChainId.ArbitrumSepolia,
      signer: connectedWallet,
      rpcProviderUrl: RPC_URL
    });
  } else {
    sdk = new TradingSDK({
      chainId: SupportedChainId.ArbitrumSepolia,
      rpcProviderUrl: RPC_URL
    });
  }

  await sdk.initialize();
  console.error("✅ SDK initialized\n");

  const trades = await sdk.getUserTrades(WALLET_ADDRESS);

  console.error(`Total trades found: ${trades.length}`);
  console.error();

  trades.forEach((trade, idx) => {
    console.error(`Trade ${idx}: Index ${trade.trade.index}`);
    console.error(`  Pair: ${trade.trade.pairIndex}`);
    console.error(`  Open: ${trade.trade.isOpen}`);
    console.error(`  Long: ${trade.trade.long}`);
    console.error(`  Collateral: ${trade.trade.collateralAmount.toString()}`);
    console.error(`  Leverage: ${trade.trade.leverage}`);
    console.error();
  });

  const openTrades = trades.filter(t => t.trade.isOpen);
  console.error(`Open trades: ${openTrades.length}`);

  // Output JSON
  const output = {
    success: true,
    totalTrades: trades.length,
    openTrades: openTrades.length,
    trades: trades.map(t => ({
      index: t.trade.index,
      pairIndex: t.trade.pairIndex,
      isOpen: t.trade.isOpen,
      long: t.trade.long,
      collateral: t.trade.collateralAmount.toString(),
      leverage: t.trade.leverage
    }))
  };

  console.log(JSON.stringify(output, null, 2));
}

main().catch(err => {
  console.error("Error:", err.message);
  const output = {
    success: false,
    error: err.message
  };
  console.log(JSON.stringify(output, null, 2));
  process.exit(1);
});
