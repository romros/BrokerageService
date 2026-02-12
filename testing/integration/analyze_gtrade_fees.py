#!/usr/bin/env python3
"""
Analitza fees reals de gTrade a partir de transaccions Sepolia
Compara amb el nostre CostModel per validar exactitud
"""

# Dades extretes de les captures de pantalla del usuari

transactions = [
    {
        "pair": "BTC/USD",
        "type": "SHORT",
        "collateral": 8_733,  # USDC
        "position_size": 1_746_500,  # USDC
        "fees": 873.25,  # USDC
        "leverage": 1_746_500 / 8_733,  # ~200x
    },
    {
        "pair": "BTC/USD",
        "type": "SHORT",
        "collateral": 8_733,
        "position_size": 1_746_500,
        "fees": 873.25,
        "leverage": 1_746_500 / 8_733,
    },
    {
        "pair": "BTC/USD",
        "type": "MARKET",
        "collateral": 10_000,
        "position_size": 2_000_000,
        "fees": 1_000,
        "leverage": 2_000_000 / 10_000,  # 200x
    },
]

print("=" * 80)
print("📊 ANÀLISI DE FEES REALS - gTrade Sepolia")
print("=" * 80)

for i, tx in enumerate(transactions, 1):
    print(f"\n🔹 Transacció #{i}: {tx['pair']} {tx['type']}")
    print("-" * 80)
    print(f"Collateral:     {tx['collateral']:>12,.2f} USDC")
    print(f"Position Size:  {tx['position_size']:>12,.2f} USDC")
    print(f"Leverage:       {tx['leverage']:>12,.2f}x")
    print(f"Fees Pagades:   {tx['fees']:>12,.2f} USDC")

    # Calcula fee percentage
    fee_pct = (tx['fees'] / tx['position_size']) * 100
    fee_bps = fee_pct * 100

    print(f"\n📈 Fee Analysis:")
    print(f"   Fee %:       {fee_pct:>12.4f}%")
    print(f"   Fee (bps):   {fee_bps:>12.2f} bps")

    # Estimació de components (assumint open fee només)
    # gTrade típic: spread ~1 bps + open_fee ~X bps
    estimated_open_fee_bps = fee_bps - 1.0  # Assumint 1 bps spread
    print(f"\n💡 Estimated Breakdown (si només open fee):")
    print(f"   Spread:      ~1.0 bps (assumit)")
    print(f"   Open Fee:    ~{estimated_open_fee_bps:.2f} bps")

print("\n" + "=" * 80)
print("📋 RESUM")
print("=" * 80)

avg_fee_bps = sum((tx['fees'] / tx['position_size']) * 10_000 for tx in transactions) / len(transactions)
print(f"Fee mitjana (bps): {avg_fee_bps:.2f} bps")
print(f"Fee mitjana (%):   {avg_fee_bps / 100:.4f}%")

print("\n🔍 Comparació amb el nostre CostModel:")
print("   EURUSD: spread 1.0 + open 1.2 + close 1.2 = 3.4 bps total")
print("   XAUUSD: spread 1.0 + open 5.0 + close 5.0 = 11.0 bps total")
print(f"   BTC/USD (real): ~{avg_fee_bps:.2f} bps per transacció (open only)")

print("\n⚠️  NOTA: El nostre CostModel NO té BTC/USD definit!")
print("    Només suporta EURUSD i XAUUSD.")

print("\n💡 RECOMANACIÓ:")
print("    Si volem suportar BTC/USD, hem d'afegir:")
print("    - spread_bps: 1.0 (estàndard)")
print(f"    - open_fee_bps: {estimated_open_fee_bps:.2f}")
print(f"    - close_fee_bps: {estimated_open_fee_bps:.2f} (assumint simètric)")
