# 🚀 Setup Arbitrum Sepolia Testnet

## ✅ Estat actual

- ✅ Contractes gTrade verificats a Sepolia: `0xd659a15812064C79E189fd950A189b15c75d3186`
- ✅ Backend Sepolia disponible: `https://backend-sepolia.gains.trade`
- ✅ Wallet amb ETH: `0xD9fC17C093614D20976EFb1535A7142081A031b2` (0.03 ETH)

## 📋 Passos per configurar

### 1️⃣ Configura la seed phrase

Edita el fitxer `.env` i substitueix aquesta línia:

```bash
WALLET_MNEMONIC=OMPLIR_AMB_LES_12_PARAULES_DE_LA_TEVA_WALLET
```

Per les teves 12 paraules de la wallet, per exemple:

```bash
WALLET_MNEMONIC=word1 word2 word3 word4 word5 word6 word7 word8 word9 word10 word11 word12
```

### 2️⃣ Aconsegueix Practice DAI

1. Ves a https://gains.trade/
2. Connecta la teva wallet (Metamask, Rabby, etc.) a Arbitrum Sepolia
3. Activa "Practice Mode" (dalt a la dreta)
4. Reclama 10,000 DAI gratuïts

### 3️⃣ Verifica la connexió

Executa el test de connexió:

```bash
./test.sh testing/integration/test_sepolia_connection.py
```

Hauries de veure:

```
✅ Connectat: Chain ID 421614
✅ Wallet: 0xD9fC17C093614D20976EFb1535A7142081A031b2
✅ gTrade Diamond (Sepolia): 0xd659a15812064C79E189fd950A189b15c75d3186
```

### 4️⃣ Comprova el backend

Pots veure les teves posicions obertes aquí:

https://backend-sepolia.gains.trade/open-trades/0xD9fC17C093614D20976EFb1535A7142081A031b2

## 🔐 Seguretat

- ⚠️ **IMPORTANT**: El fitxer `.env` està a `.gitignore` i NO es commitarà mai
- ⚠️ **Aquesta és una wallet de testnet** - No conté diners reals
- ⚠️ **No comparteixis mai la seed phrase** amb ningú

## 🚀 Next Steps

Un cop verificada la connexió, estàs llest per **FASE 6B.1.B.5 - Testnet Dry Run**:

1. Primera transacció real a blockchain (testnet)
2. Open position + backend verification
3. Close position + confirmació

Tots els tests actuals (21/21) passen amb mocks. Ara podem provar amb blockchain real! 🎉
