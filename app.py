import os
import pandas as pd
from flask import Flask, render_template, jsonify, request, send_from_directory
import db
import requests
from datetime import datetime
import yfinance as yf

app = Flask(__name__, template_folder='templates')

# Initialize DB on start
db.init_db()



def fetch_prices_from_yfinance(stocks_list):
    if not stocks_list:
        return {}
        
    # 1. Map symbols to ensure they use the Yahoo Finance format (e.g., "IDEA.NS")
    # If the database stores them as "IDEA", this automatically appends ".NS"
    yf_symbols = []
    symbol_to_id = {}
    
    for s in stocks_list:
        sym = s['symbol']
        # Automatically append .NS for NSE stocks if missing
        if not sym.endswith(".NS") and not sym.endswith(".BO"):
            sym = f"{sym}.NS"
            
        yf_symbols.append(sym)
        symbol_to_id[sym] = s['id']

    results = {}
    
    try:
        # 2. Download latest 1-day market data for all symbols simultaneously
        # We group them as a space-separated string for yfinance batching
        app.logger.info(f"Fetching data for symbols: {yf_symbols}")
        data = yf.download(
            tickers=" ".join(yf_symbols), 
            period="1d", 
            progress=False
        )
        app.logger.info(f"Data structure: {data}")
    except Exception as e:
        return {s['id']: {"price": None, "error": f"Network error: {str(e)}"} for s in stocks_list}

    # 3. Process the downloaded data
    for yf_sym, sid in symbol_to_id.items():
        try:
            if data.empty or 'Close' not in data:
                results[sid] = {"price": None, "error": "No market data returned from Yahoo Finance."}
                continue

            # Extract the raw closing data block
            close_data = data['Close']

            # Case A: If handling a single stock
            if len(yf_symbols) == 1:
                # If close_data is a DataFrame due to multi-index headers, extract the column
                if isinstance(close_data, pd.DataFrame):
                    series_data = close_data.iloc[:, 0].dropna()
                else:
                    series_data = close_data.dropna()

            # Case B: If handling multiple stocks
            else:
                if yf_sym in close_data:
                    series_data = close_data[yf_sym].dropna()
                else:
                    results[sid] = {"price": None, "error": f"Column for {yf_sym} missing."}
                    continue

            # Extract the final numeric item out of the cleaned series
            if not series_data.empty:
                latest_price = series_data.iloc[-1]
                
                # Double-check if latest_price is still somehow bundled inside a Series
                if isinstance(latest_price, pd.Series):
                    latest_price = latest_price.iloc[0]
                    
                results[sid] = {"price": float(latest_price), "error": None}
            else:
                results[sid] = {"price": None, "error": "No recent trading prices found."}
                
        except Exception as e:
            results[sid] = {"price": None, "error": f"Parsing failure: {str(e)}"}

    app.logger.info(f"Price results: {results}")
    return results

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/stocks', methods=['GET'])
def get_stocks():
    stocks = db.get_stocks()
    return jsonify(stocks)

@app.route('/api/stocks', methods=['POST'])
def add_stock():
    data = request.get_json() or {}
    symbol = data.get('symbol', '').upper().strip()
    name = data.get('name', '').strip() or None
    buy_amt = data.get('buy_amt')
    sell_amt = data.get('sell_amt')
    stock_id = data.get('id') or None
    
    if not symbol:
        return jsonify({"error": "Symbol is required"}), 400
    if buy_amt is None or sell_amt is None:
        return jsonify({"error": "buy_amt and sell_amt are required"}), 400
    
    try:
        buy_amt = float(buy_amt)
        sell_amt = float(sell_amt)
    except ValueError:
        return jsonify({"error": "Amounts must be numeric"}), 400
        
    if sell_amt <= buy_amt:
        return jsonify({"error": "Max reach (sell_amt) must be greater than min buy (buy_amt)"}), 400
        
    try:
        stock = db.add_stock(symbol, name, buy_amt, sell_amt, stock_id)
        return jsonify(stock), 201
    except Exception as e:
        # SQLite constraint violation (duplicate symbol)
        if "UNIQUE constraint failed" in str(e):
            return jsonify({"error": f"Stock symbol '{symbol}' is already on the ledger"}), 409
        return jsonify({"error": str(e)}), 500

@app.route('/api/stocks/<stock_id>', methods=['PUT'])
def update_stock(stock_id):
    data = request.get_json() or {}
    symbol = data.get('symbol', '').upper().strip()
    name = data.get('name', '').strip() or None
    buy_amt = data.get('buy_amt')
    sell_amt = data.get('sell_amt')
    
    if not symbol:
        return jsonify({"error": "Symbol is required"}), 400
    if buy_amt is None or sell_amt is None:
        return jsonify({"error": "buy_amt and sell_amt are required"}), 400
        
    try:
        buy_amt = float(buy_amt)
        sell_amt = float(sell_amt)
    except ValueError:
        return jsonify({"error": "Amounts must be numeric"}), 400
        
    if sell_amt <= buy_amt:
        return jsonify({"error": "Max reach (sell_amt) must be greater than min buy (buy_amt)"}), 400
        
    try:
        stock = db.update_stock(stock_id, symbol, name, buy_amt, sell_amt)
        if not stock:
            return jsonify({"error": "Stock not found"}), 404
        return jsonify(stock)
    except Exception as e:
        if "UNIQUE constraint failed" in str(e):
            return jsonify({"error": f"Stock symbol '{symbol}' is already on another record"}), 409
        return jsonify({"error": str(e)}), 500

@app.route('/api/stocks/<stock_id>', methods=['DELETE'])
def delete_stock(stock_id):
    db.delete_stock(stock_id)
    return jsonify({"success": True})

@app.route('/api/settings', methods=['GET'])
def get_settings():
    api_key = db.get_setting("apiKey", "")
    return jsonify({"apiKey": api_key})

@app.route('/api/settings', methods=['POST'])
def save_settings():
    data = request.get_json() or {}
    api_key = data.get('apiKey', '').strip()
    db.set_setting("apiKey", api_key)
    return jsonify({"apiKey": api_key, "success": True})

@app.route('/api/stocks/refresh', methods=['POST'])
def refresh_all_stocks():
    data = request.get_json() or {}
    stock_ids = data.get('ids')
    
    if stock_ids:
        stocks_to_refresh = [db.get_stock(sid) for sid in stock_ids if db.get_stock(sid)]
    else:
        stocks_to_refresh = db.get_stocks()
        
    if not stocks_to_refresh:
        return jsonify([])
        
    price_results = fetch_prices_from_yfinance(stocks_to_refresh)
    now_str = datetime.utcnow().isoformat() + "Z"
    
    for sid, result in price_results.items():
        if result.get("error"):
            db.update_stock_price(sid, None, now_str, result["error"])
        else:
            db.update_stock_price(sid, result["price"], now_str, None)
            
    # Return updated stock list
    if stock_ids:
        return jsonify([db.get_stock(sid) for sid in stock_ids if db.get_stock(sid)])
    else:
        return jsonify(db.get_stocks())

@app.route('/api/stocks/<stock_id>/refresh', methods=['POST'])
def refresh_single_stock(stock_id):
    stock = db.get_stock(stock_id)
    if not stock:
        return jsonify({"error": "Stock not found"}), 404
        
    price_results = fetch_prices_from_yfinance([stock])
    now_str = datetime.utcnow().isoformat() + "Z"
    
    result = price_results.get(stock_id, {"price": None, "error": "Fetch failed"})
    updated_stock = db.update_stock_price(stock_id, result.get("price"), now_str, result.get("error"))
    
    return jsonify(updated_stock)

if __name__ == '__main__':
    # Running on local host at port 5000
    app.run(debug=True, host='127.0.0.1', port=5000)

