import os
import time
import json
from datetime import datetime
import akshare as ak
import yfinance as yf

# ================= 1. 专属监控股票池 =================
# A股配置：(代码, 名称, 分类: semi半导体核心 / qdii跨境纳指标普ETF)
A_SHARES = [
    ("002436", "兴森科技", "semi"),
    ("600584", "长电科技", "semi"),
    ("513100", "纳指ETF(国泰)", "qdii"),
    ("513300", "纳指ETF(华夏)", "qdii"),
    ("159941", "纳指ETF(广发)", "qdii"),
    ("513500", "标普500ETF", "qdii"),
]

# 美股配置：(代码, 名称, 分类: mag7科技七姐妹与AI巨头 / etf美股核心宽基)
US_STOCKS = [
    ("NVDA", "英伟达", "mag7"),
    ("AAPL", "苹果", "mag7"),
    ("MSFT", "微软", "mag7"),
    ("GOOGL", "谷歌", "mag7"),
    ("AMZN", "亚马逊", "mag7"),
    ("META", "Meta", "mag7"),
    ("TSLA", "特斯拉", "mag7"),
    ("ORCL", "甲骨文", "mag7"),
    ("QQQM", "纳指100(QQQM)", "etf"),
    ("VOO", "标普500(VOO)", "etf"),
]

# 大盘风向标
MARKET_INDICES = {
    "cn": [("000001", "上证指数"), ("000688", "科创50")],
    "us": [("^IXIC", "纳斯达克"), ("^GSPC", "标普500")]
}

# ================= 2. 差异化策略阈值计算 =================
def calc_signals(price, ma120, market="CN", category="semi"):
    deviation = round((price - ma120) / ma120 * 100, 2)
    
    # 宽基 ETF 波动率低，采用紧凑偏离阈值
    if category in ("qdii", "etf"):
        buy1 = round(ma120 * 0.90, 2)   # -10%
        buy2 = round(ma120 * 0.82, 2)   # -18%
        sell = round(ma120 * 1.15, 2)   # +15%
    elif market == "CN":
        # A股半导体高弹性
        buy1 = round(ma120 * 0.85, 2)   # -15%
        buy2 = round(ma120 * 0.75, 2)   # -25%
        sell = round(ma120 * 1.20, 2)   # +20%
    else:
        # 美股科技七姐妹与算力巨头
        buy1 = round(ma120 * 0.82, 2)   # -18%
        buy2 = round(ma120 * 0.72, 2)   # -28%
        sell = round(ma120 * 1.25, 2)   # +25%

    span = sell - buy2
    pos_pct = round(max(0, min(100, (price - buy2) / span * 100)), 1) if span > 0 else 50

    if price <= buy2:
        status = "极值补仓"
    elif price <= buy1:
        status = "买入信号"
    elif price <= buy1 * 1.03:
        status = "即将到位"
    elif price >= sell:
        status = "卖出信号"
    else:
        status = "正常"

    return deviation, buy1, buy2, sell, status, pos_pct

# ================= 3. 数据抓取逻辑 =================
def fetch_cn_hist(code, is_etf=False, retries=3):
    for i in range(retries):
        try:
            if is_etf:
                df = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="qfq")
            else:
                df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
            if df is not None and len(df) >= 120:
                return df
        except Exception as e:
            print(f"[A股重试 {i+1}/{retries}] {code}: {e}")
            time.sleep(2)
    return None

def fetch_cn():
    results = []
    for code, name, cat in A_SHARES:
        is_etf = code.startswith(("51", "15", "56", "58"))
        df = fetch_cn_hist(code, is_etf=is_etf)
        if df is None:
            continue
        df = df.tail(130)
        latest = df.iloc[-1]
        price = round(float(latest["收盘"]), 3 if is_etf else 2)
        change = round(float(latest["涨跌幅"]), 2)
        ma120 = round(df["收盘"].tail(120).mean(), 3 if is_etf else 2)

        div_val = 0.0
        div_str = "--"
        if not is_etf:
            try:
                ind = ak.stock_a_indicator_lg(symbol=code)
                if not ind.empty and "dv_ttm" in ind.columns:
                    val = ind.iloc[-1]["dv_ttm"]
                    if val and float(val) > 0:
                        div_val = round(float(val), 2)
                        div_str = f"{div_val}%"
            except Exception:
                pass

        dev, b1, b2, sell, status, pos_pct = calc_signals(price, ma120, "CN", cat)
        if is_etf:
            b1, b2, sell = round(b1, 3), round(b2, 3), round(sell, 3)

        market_prefix = "sh" if code.startswith(("6", "5")) else "sz"
        results.append({
            "code": code, "name": name, "category": cat, "price": price,
            "change": change, "dividend": div_str, "high_div": div_val >= 3.5,
            "deviation": dev, "buy1": b1, "buy2": b2, "ma120": ma120,
            "sell": sell, "status": status, "pos_pct": pos_pct,
            "url": f"https://quote.eastmoney.com/{market_prefix}{code}.html"
        })
    return results

def fetch_us():
    results = []
    for code, name, cat in US_STOCKS:
        try:
            ticker = yf.Ticker(code)
            hist = ticker.history(period="8mo")
            if len(hist) < 120:
                continue

            price = round(float(hist["Close"].iloc[-1]), 2)
            prev_close = float(hist["Close"].iloc[-2])
            change = round((price - prev_close) / prev_close * 100, 2)
            ma120 = round(float(hist["Close"].tail(120).mean()), 2)

            info = ticker.info
            raw_div = info.get("dividendYield")
            div_val = round(raw_div * 100, 2) if raw_div else 0.0
            div_str = f"{div_val}%" if div_val > 0 else "--"

            dev, b1, b2, sell, status, pos_pct = calc_signals(price, ma120, "US", cat)
            results.append({
                "code": code, "name": name, "category": cat, "price": price,
                "change": change, "dividend": div_str, "high_div": div_val >= 3.5,
                "deviation": dev, "buy1": b1, "buy2": b2, "ma120": ma120,
                "sell": sell, "status": status, "pos_pct": pos_pct,
                "url": f"https://finance.yahoo.com/quote/{code}"
            })
        except Exception as e:
            print(f"[美股] {code} 获取失败: {e}")
    return results

def fetch_indices():
    idx_data = {"cn": [], "us": []}
    for code, name in MARKET_INDICES["cn"]:
        try:
            df = ak.stock_zh_index_daily_em(symbol=f"sh{code}")
            df = df.tail(125)
            price = round(float(df["close"].iloc[-1]), 2)
            prev = float(df["close"].iloc[-2])
            chg = round((price - prev) / prev * 100, 2)
            ma120 = round(df["close"].tail(120).mean(), 2)
            dev = round((price - ma120) / ma120 * 100, 2)
            idx_data["cn"].append({"name": name, "price": price, "change": chg, "deviation": dev})
        except Exception:
            pass
    for code, name in MARKET_INDICES["us"]:
        try:
            hist = yf.Ticker(code).history(period="8mo")
            price = round(float(hist["Close"].iloc[-1]), 2)
            prev = float(hist["Close"].iloc[-2])
            chg = round((price - prev) / prev * 100, 2)
            ma120 = round(float(hist["Close"].tail(120).mean()), 2)
            dev = round((price - ma120) / ma120 * 100, 2)
            idx_data["us"].append({"name": name, "price": price, "change": chg, "deviation": dev})
        except Exception:
            pass
    return idx_data

if __name__ == "__main__":
    today = datetime.now().strftime("%Y-%m-%d")
    output = {
        "date": today,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "indices": fetch_indices(),
        "cn": fetch_cn(),
        "us": fetch_us()
    }

    os.makedirs("history", exist_ok=True)
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    with open(f"history/{today}.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    dates = sorted([fn.replace(".json", "") for fn in os.listdir("history") if fn.endswith(".json") and fn != "dates.json"], reverse=True)
    with open("history/dates.json", "w", encoding="utf-8") as f:
        json.dump(dates, f, ensure_ascii=False)

    print(f"✅ 炒股韭菜王监控数据更新完成: {today}")
