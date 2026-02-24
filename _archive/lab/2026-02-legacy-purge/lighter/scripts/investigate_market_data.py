#!/usr/bin/env python3
"""
Lighter - Market Data Investigation Script

Aquest script investiga l'SDK de Lighter per entendre:
1. Estructura completa de Market objects
2. Com obtenir orderbook (bid/ask) 
3. Mapeig symbols → order_book_id
4. Quins camps estan disponibles per TradingPair

Aquest script NO fa trading, només investiga l'API.
"""
import os
import asyncio
import json
from dotenv import load_dotenv
import lighter

load_dotenv()

# Lighter configuration (mateixes credencials que altres scripts)
BASE_URL = os.getenv("LIGHTER_BASE_URL", "https://testnet.zklighter.elliot.ai")
L1_ADDRESS = os.getenv("LIGHTER_L1_ADDRESS")
ACCOUNT_INDEX = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "210"))
API_KEY_INDEX = int(os.getenv("LIGHTER_API_KEY_INDEX", "1"))
API_PRIVATE_KEY = os.getenv("LIGHTER_API_PRIVATE_KEY")


async def investigate_markets():
    """Investiga com obtenir markets - estructura completa"""
    print("=" * 80)
    print("INVESTIGACIÓ 1: Obtenir Markets - Estructura completa")
    print("=" * 80)
    
    api_client = lighter.ApiClient()
    try:
        # Provar OrderApi.order_books() que ja funciona
        orders_api = lighter.OrderApi(api_client)
        order_books_response = await orders_api.order_books()
        
        # OrderBooks conté order_books
        if hasattr(order_books_response, 'order_books') and order_books_response.order_books:
            markets_list = order_books_response.order_books
            print(f"\n✅ OrderBooks obtinguts: {len(markets_list)} mercats\n")
            
            # Analitzar primer market en detall
            first_market = markets_list[0]
            print("📊 Primer mercat (estructura completa):")
            print(f"   Type: {type(first_market)}")
            print(f"   Dir: {[attr for attr in dir(first_market) if not attr.startswith('_')]}\n")
            
            # Intentar convertir a dict per veure tots els camps
            try:
                if hasattr(first_market, '__dict__'):
                    market_dict = first_market.__dict__
                    print("   Atributs (__dict__):")
                    for key, value in market_dict.items():
                        print(f"      {key}: {value}")
                else:
                    # Intentar serialitzar
                    market_json = json.dumps(first_market, default=str, indent=2)
                    print(f"   JSON representation:\n{market_json}")
            except Exception as e:
                print(f"   ⚠️  No es pot serialitzar: {e}")
            
            print("\n" + "-" * 80)
            print("📋 Tots els mercats (resum):")
            print("-" * 80)
            
            for i, market in enumerate(markets_list[:10]):  # Primer 10
                print(f"\n   Mercat {i+1}:")
                # Intentar extreure camps comuns
                if hasattr(market, 'order_book_id'):
                    print(f"      order_book_id: {market.order_book_id}")
                if hasattr(market, 'last_price'):
                    last_price = float(market.last_price) / 1e6 if market.last_price else None
                    print(f"      last_price: ${last_price:.2f}" if last_price else "      last_price: None")
                if hasattr(market, 'base_token'):
                    print(f"      base_token: {market.base_token}")
                if hasattr(market, 'quote_token'):
                    print(f"      quote_token: {market.quote_token}")
                if hasattr(market, 'symbol'):
                    print(f"      symbol: {market.symbol}")
                if hasattr(market, 'name'):
                    print(f"      name: {market.name}")
                if hasattr(market, 'max_leverage'):
                    print(f"      max_leverage: {market.max_leverage}")
                if hasattr(market, 'min_size'):
                    print(f"      min_size: {market.min_size}")
                if hasattr(market, 'tick_size'):
                    print(f"      tick_size: {market.tick_size}")
                
                # Mostrar tots els atributs disponibles
                attrs = [a for a in dir(market) if not a.startswith('_') and not callable(getattr(market, a, None))]
                if attrs:
                    print(f"      Altres atributs: {', '.join(attrs[:10])}")
        
        await api_client.close()
        return order_books_response
        
    except Exception as e:
        print(f"❌ Error investigant markets: {e}")
        import traceback
        traceback.print_exc()
        await api_client.close()
        return None


async def investigate_orderbook():
    """Investiga OrderApi per obtenir orderbook (bid/ask)"""
    print("\n" + "=" * 80)
    print("INVESTIGACIÓ 2: OrderApi - Orderbook (bid/ask)")
    print("=" * 80)
    
    api_client = lighter.ApiClient()
    try:
        orders_api = lighter.OrderApi(api_client)
        
        # Provar diferents mètodes d'orderbook
        methods_to_try = [
            ('order_book_details', lambda: orders_api.order_book_details(order_book_id=1)),
            ('order_book_orders', lambda: orders_api.order_book_orders(order_book_id=1)),
            ('order_books', lambda: orders_api.order_books()),
        ]
        
        # Primer obtenir llista de markets per saber quins market_id hi ha
        order_books = await orders_api.order_books()
        if hasattr(order_books, 'order_books') and order_books.order_books:
            test_market_id = order_books.order_books[0].market_id
            print(f"\n   Usant market_id={test_market_id} per proves\n")
            
            # Provar amb ReqGetOrderBookDetails
            try:
                from lighter.models import ReqGetOrderBookDetails
                req = ReqGetOrderBookDetails(market_id=test_market_id)
                result = await orders_api.order_book_details(req)
                print(f"   ✅ order_book_details() amb ReqGetOrderBookDetails:")
                print(f"      Type: {type(result)}")
                if hasattr(result, '__dict__'):
                    print(f"      Atributs: {list(result.__dict__.keys())}")
                    for key, value in result.__dict__.items():
                        if 'bid' in key.lower() or 'ask' in key.lower() or 'price' in key.lower() or 'best' in key.lower():
                            print(f"         {key}: {value}")
            except Exception as e:
                print(f"   ⚠️  order_book_details amb ReqGetOrderBookDetails: {e}")
            
            # Provar amb order_book_orders (limit és paràmetre posicional)
            try:
                result = await orders_api.order_book_orders(market_id=test_market_id, limit=10)
                print(f"\n   ✅ order_book_orders() amb ReqGetOrderBookOrders:")
                print(f"      Type: {type(result)}")
                if hasattr(result, '__dict__'):
                    print(f"      Atributs: {list(result.__dict__.keys())}")
                    # Buscar bids/asks
                    for key, value in result.__dict__.items():
                        if 'bid' in key.lower() or 'ask' in key.lower() or 'order' in key.lower():
                            print(f"         {key}: {type(value)} (length: {len(value) if hasattr(value, '__len__') else 'N/A'})")
                            if hasattr(value, '__iter__') and not isinstance(value, str):
                                try:
                                    first_item = next(iter(value)) if value else None
                                    if first_item:
                                        print(f"            Primer item: {type(first_item)}")
                                        if hasattr(first_item, '__dict__'):
                                            print(f"            Atributs: {list(first_item.__dict__.keys())[:5]}")
                                except:
                                    pass
            except Exception as e:
                print(f"   ⚠️  order_book_orders amb ReqGetOrderBookOrders: {e}")
        
        # Provar order_books() (ja sabem que funciona)
        print(f"\n   ✅ order_books() (ja validat):")
        print(f"      Retorna llista de OrderBook objects amb market_id, symbol, fees, etc.")
        
        await api_client.close()
        
    except Exception as e:
        print(f"❌ Error investigant orderbook: {e}")
        import traceback
        traceback.print_exc()
        await api_client.close()


async def map_symbols_to_orderbook_id():
    """Mapeja symbols coneguts a order_book_id"""
    print("\n" + "=" * 80)
    print("INVESTIGACIÓ 3: Mapeig Symbols → order_book_id")
    print("=" * 80)
    
    api_client = lighter.ApiClient()
    try:
        orders_api = lighter.OrderApi(api_client)
        order_books_response = await orders_api.order_books()
        
        if not hasattr(order_books_response, 'order_books') or not order_books_response.order_books:
            print("   ⚠️  No hi ha order_books disponibles")
            await api_client.close()
            return {}
        
        markets_list = order_books_response.order_books
        
        # Symbols coneguts del lab (provar variants)
        known_symbols = ["WETH-USDC", "ETH-USDC", "BTC-USDC", "WBTC-USDC", "LINK-USDC", 
                        "WETH", "ETH", "BTC", "WBTC", "LINK", "ETHUSDC", "BTCUSDC"]
        
        print("\n📋 Mapeig de symbols:")
        symbol_map = {}
        
        for market in markets_list:
            market_id = getattr(market, 'market_id', None)
            symbol = getattr(market, 'symbol', None)
            market_type = getattr(market, 'market_type', None)
            base_asset_id = getattr(market, 'base_asset_id', None)
            quote_asset_id = getattr(market, 'quote_asset_id', None)
            
            if market_id is not None:
                symbol_map[market_id] = {
                    'symbol': symbol,
                    'market_id': market_id,
                    'market_type': market_type,
                    'base_asset_id': base_asset_id,
                    'quote_asset_id': quote_asset_id
                }
        
        # Mostrar mapeig (primer 20)
        print("\n   market_id → Symbol (primer 20):")
        for market_id in sorted(symbol_map.keys())[:20]:
            info = symbol_map[market_id]
            print(f"      {market_id}: {info['symbol']} (type: {info.get('market_type', 'N/A')})")
        
        # Buscar symbols coneguts (case-insensitive)
        print("\n   Symbols coneguts del lab:")
        for known_symbol in known_symbols:
            found = False
            for market_id, info in symbol_map.items():
                symbol_upper = (info['symbol'] or '').upper()
                known_upper = known_symbol.upper()
                if symbol_upper == known_upper or known_upper in symbol_upper or symbol_upper in known_upper:
                    print(f"      ✅ {known_symbol} → market_id={market_id}, symbol={info['symbol']}")
                    found = True
                    break
            if not found:
                print(f"      ❌ {known_symbol} → NO TROBAT")
        
        await api_client.close()
        return symbol_map
        
    except Exception as e:
        print(f"❌ Error mapejant symbols: {e}")
        import traceback
        traceback.print_exc()
        await api_client.close()
        return {}


async def investigate_trading_pair_fields():
    """Investiga quins camps de Market es poden mapejar a TradingPair"""
    print("\n" + "=" * 80)
    print("INVESTIGACIÓ 4: Camps disponibles per TradingPair")
    print("=" * 80)
    
    api_client = lighter.ApiClient()
    try:
        orders_api = lighter.OrderApi(api_client)
        order_books_response = await orders_api.order_books()
        
        if not hasattr(order_books_response, 'order_books') or not order_books_response.order_books:
            print("   ⚠️  No hi ha mercats disponibles")
            await api_client.close()
            return
        
        market = order_books_response.order_books[0]
        
        print("\n📋 Camps necessaris per TradingPair domain model:")
        print("   (domain/models/trading_pair.py)")
        print("\n   Requerits:")
        print("      - pair_id: int")
        print("      - symbol: str")
        print("      - base: str")
        print("      - quote: str")
        print("      - min_leverage: float")
        print("      - max_leverage: float")
        print("      - maker_fee_percent: float")
        print("      - taker_fee_percent: float")
        print("      - is_market_open: bool")
        
        print("\n   Mapeig des de Market object:")
        mapping = {}
        
        # pair_id
        if hasattr(market, 'market_id'):
            mapping['pair_id'] = f"market.market_id ({market.market_id})"
        
        # symbol
        if hasattr(market, 'symbol'):
            mapping['symbol'] = f"market.symbol ({market.symbol})"
        
        # base/quote (OrderBook no té base_token/quote_token directe, usar asset_id o symbol parsing)
        if hasattr(market, 'symbol'):
            # Intentar parsejar symbol (ex: "ETH" o "ETH-USDC")
            symbol = market.symbol
            if '-' in symbol:
                parts = symbol.split('-')
                mapping['base'] = f"symbol.split('-')[0] ({parts[0] if len(parts) > 0 else 'N/A'})"
                mapping['quote'] = f"symbol.split('-')[1] ({parts[1] if len(parts) > 1 else 'N/A'})"
            else:
                mapping['base'] = f"symbol ({symbol})"
                mapping['quote'] = "USDC (assumit per perpetuals)"
        
        # leverage (OrderBook no té leverage directe)
        mapping['max_leverage'] = "Default (Lighter suporta leverage variable, consultar API separada)"
        mapping['min_leverage'] = "1.0 (default)"
        
        # fees
        if hasattr(market, 'maker_fee'):
            mapping['maker_fee_percent'] = f"market.maker_fee ({market.maker_fee})"
        if hasattr(market, 'taker_fee'):
            mapping['taker_fee_percent'] = f"market.taker_fee ({market.taker_fee})"
        
        # market open
        if hasattr(market, 'status'):
            mapping['is_market_open'] = f"market.status == 'active' ({market.status})"
        
        for key, value in mapping.items():
            print(f"      ✅ {key}: {value}")
        
        # Camps no trobats
        missing = ['min_leverage', 'maker_fee_percent', 'taker_fee_percent', 'is_market_open']
        for field in missing:
            if field not in mapping:
                print(f"      ⚠️  {field}: NO TROBAT (usar default)")
        
        await api_client.close()
        
    except Exception as e:
        print(f"❌ Error investigant TradingPair: {e}")
        import traceback
        traceback.print_exc()
        await api_client.close()


async def main():
    print("=" * 80)
    print("LIGHTER - MARKET DATA INVESTIGATION")
    print("=" * 80)
    print(f"Base URL: {BASE_URL}")
    print(f"Account: {ACCOUNT_INDEX}\n")
    
    # Executar totes les investigacions
    order_books_response = await investigate_markets()
    await investigate_orderbook()
    symbol_map = await map_symbols_to_orderbook_id()
    await investigate_trading_pair_fields()
    
    # Resum final
    print("\n" + "=" * 80)
    print("RESUM FINAL")
    print("=" * 80)
    print("\n✅ Investigacions completes")
    print("\n📝 Conclusions per TASK 3:")
    print("   1. OrderApi.order_books() retorna llista de OrderBook objects")
    print("   2. OrderApi té mètodes per orderbook details (verificar quins funcionen)")
    print("   3. Symbol mapping: usar camps de OrderBook object")
    print("   4. TradingPair: alguns camps poden requerir defaults")
    print("\n💡 Pròxim pas: Revisar resultats i implementar mappers.py + marketdata_client.py")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
