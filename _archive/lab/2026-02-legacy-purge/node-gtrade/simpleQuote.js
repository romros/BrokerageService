#!/usr/bin/env node
/**
 * DEMO: Minimal quote generator using gTrade SDK
 *
 * Output: JSON amb openPrice, maxSlippage, i calldata
 */

import { TradingSDK, SupportedChainId } from '@gainsnetwork/trading-sdk';
import { parseUnits } from 'ethers';

async function main() {
  try {
    // Config
    const config = {
      pair: process.argv[2] || 'BTCUSD',
      isLong: process.argv[3] !== 'short',
      collateral: parseFloat(process.argv[4] || '150'),
      leverage: parseInt(process.argv[5] || '10'),
      walletAddress: process.argv[6] || '0xD9fC17C093614D20976EFb1535A7142081A031b2',
      rpcUrl: process.argv[7] || 'https://sepolia-rollup.arbitrum.io/rpc'
    };

    console.error('🔧 Initializing gTrade SDK...');
    const sdk = new TradingSDK({
      chainId: SupportedChainId.ArbitrumSepolia,
      rpcProviderUrl: config.rpcUrl
    });

    await sdk.initialize();
    console.error('✅ SDK initialized');

    // Get state (includes oracle prices)
    console.error('📊 Fetching market state...');
    const state = await sdk.getState();

    // Find pair index
    const pairIndex = 0; // BTCUSD = 0

    // Get oracle price (from state or use hardcoded for demo)
    const oraclePrice = 70000.0; // TODO: Extract from state
    console.error(`   Oracle price: $${oraclePrice.toFixed(2)}`);

    // Calculate openPrice with buffer (DESCOBRIMENT SDK)
    const buffer = config.isLong ? 1.05 : 0.95;
    const openPrice = oraclePrice * buffer;

    // Calculate maxSlippage (MULTIPLICADOR - DESCOBRIMENT CRÍTIC!)
    const maxSlippage = config.isLong ? 1.10 : 0.90;

    console.error(`   openPrice: $${openPrice.toFixed(2)} (buffer: ${buffer})`);
    console.error(`   maxSlippage: ${maxSlippage} (${Math.abs(maxSlippage - 1) * 100}%)`);

    // Build transaction
    console.error('📝 Building transaction...');
    const tradeArgs = {
      user: config.walletAddress,
      pairIndex: pairIndex,
      collateralAmount: parseUnits(config.collateral.toString(), 6), // USDC
      openPrice: openPrice,
      long: config.isLong,
      leverage: config.leverage,
      tp: 0,
      sl: 0,
      collateralIndex: 3, // GNS_USDC Sepolia
      tradeType: 0, // Market
      maxSlippage: maxSlippage
    };

    const tx = await sdk.build.openTrade(tradeArgs);
    console.error('✅ Transaction built');

    // Output JSON (només stdout, errors a stderr)
    const output = {
      success: true,
      config: {
        pair: config.pair,
        direction: config.isLong ? 'LONG' : 'SHORT',
        collateral: config.collateral,
        leverage: config.leverage
      },
      quote: {
        oraclePrice: oraclePrice,
        openPrice: openPrice,
        maxSlippage: maxSlippage,
        buffer: buffer,
        positionSize: config.collateral * config.leverage
      },
      transaction: {
        to: tx.to,
        data: tx.data
      },
      parameters: {
        openPriceScaled: Math.round(openPrice * 1e10),
        maxSlippageScaled: Math.floor(maxSlippage * 1000),
        leverageScaled: Math.floor(config.leverage * 1000),
        collateralScaled: parseUnits(config.collateral.toString(), 6).toString()
      }
    };

    console.log(JSON.stringify(output, null, 2));

  } catch (error) {
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
