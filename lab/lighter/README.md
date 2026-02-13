# Lab Lighter

Scripts testnet (obrir/tancar posició, SL/TP, cancel·lacions). **Lab autònom**: dependències només a `requirements.txt` d’aquesta carpeta; res afegit al projecte productiu.

**Executar** (des de l’arrel del projecte, perquè `load_dotenv()` trobi el `.env`):

```bash
pip install -r lab/lighter/requirements.txt
# .env amb LIGHTER_BASE_URL, LIGHTER_L1_ADDRESS, LIGHTER_ACCOUNT_INDEX, LIGHTER_API_KEY_INDEX, LIGHTER_API_PRIVATE_KEY
python3 lab/lighter/scripts/open_sl_update_close.py
```

Opcional: `pip install httpx` per consulta de posicions (comparació inici/final).

Documentació: [LIGHTER_COMPLETE_VALIDATION.md](LIGHTER_COMPLETE_VALIDATION.md).
