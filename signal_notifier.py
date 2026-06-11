"""

信号推送版 v5（3 数据源）

====================================

降级顺序：Tushare（主）→ 新浪（免费兜底）→ akshare（最后兜底）

"""


import os

import datetime

import json


import pandas as pd

import requests



PARAMS = {

    "fast_window": 5,

    "slow_window": 30,

    "candidate_pool": 5,    # 5 只候选池，性价比最优

}


TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")



# ============================================================

# 数据源 1：Tushare（主）

# ============================================================

class TushareSource:

    name = "tushare"


    def __init__(self, token):

        import tushare as ts

        ts.set_token(token)

        self.pro = ts.pro_api()


    def get_stock_list(self, top_n=5):

        today = datetime.date.today().strftime("%Y%m%d")

        try:

            df = self.pro.daily_basic(trade_date=today, fields='ts_code,total_mv,name')

        except Exception:

            df = self.pro.daily_basic(fields='ts_code,total_mv,name').sort_values(

                'trade_date', ascending=False).head(top_n * 5)


        df = df[~df['ts_code'].str.startswith(('8', '4', '688'))]

        df = df[~df['name'].str.contains('ST|\\*ST', na=False)]

        df = df.sort_values('total_mv', ascending=True).head(top_n)

        return [{"code": r['ts_code'].split('.')[0], "name": r['name']}

                for _, r in df.iterrows()]


    def get_history(self, code, days=120):

        end_date = datetime.date.today().strftime("%Y%m%d")

        start_date = (datetime.date.today() - datetime.timedelta(days=days*2)).strftime("%Y%m%d")

        suffix = '.SH' if code.startswith(('60', '68')) else '.SZ'

        df = self.pro.daily(ts_code=code+suffix, start_date=start_date,

                             end_date=end_date, adj='qfq')

        if df is None or len(df) == 0:

            return None

        df = df.sort_values('trade_date', ascending=True).reset_index(drop=True)

        return df[['close']].tail(days+5).reset_index(drop=True)



# ============================================================

# 数据源 2：新浪财经（免费兜底，比 akshare 稳）

# ============================================================

class SinaSource:

    name = "sina"


    def get_stock_list(self, top_n=5):

        """

        新浪的列表接口是拿全 A 的，但不像东财有现成市值接口。

        这里用新浪的历史数据接口轮询小盘股——比较慢但免费稳定。

        折中方案：用固定的活跃 A 股小盘股代码。

        """

        # 已知活跃的小盘股代码列表（30 只，实际取最小的 5 只）

        candidates = [

            "000001", "000004", "000007", "000010", "000014",

            "000017", "000019", "000020", "000022", "000025",

            "000027", "000028", "000030", "000031", "000032",

            "000039", "000042", "000046", "000050", "000055",

            "000056", "000058", "000060", "000061", "000062",

            "000065", "000069", "000070", "000078", "000088",

        ]

        # 返回固定 5 只（不按市值筛选，因为新浪没现成市值接口）

        return [{"code": c, "name": ""} for c in candidates[:top_n]]


    def get_history(self, code, days=120):

        """

        新浪历史日线接口：

        http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh600000&scale=240&ma=no&datalen=120

        """

        prefix = 'sh' if code.startswith(('60', '68')) else 'sz'

        symbol = f"{prefix}{code}"

        url = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"

        params = {

            "symbol": symbol,

            "scale": 240,    # 日线

            "ma": "no",

            "datalen": days + 30,

        }

        headers = {

            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",

            "Referer": "http://finance.sina.com.cn/",

        }

        try:

            r = requests.get(url, params=params, headers=headers, timeout=10)

            data = r.json()

            if not data:

                return None

            # 新浪返回格式: [{"day":"2024-01-02","open":"10.5","high":"10.8","low":"10.3","close":"10.6","volume":"1000"}, ...]

            df = pd.DataFrame(data)

            df = df.rename(columns={'close': 'close'})

            df['close'] = df['close'].astype(float)

            return df[['close']].reset_index(drop=True)

        except Exception:

            return None



# ============================================================

# 数据源 3：akshare（最后兜底）

# ============================================================

class AkshareSource:

    name = "akshare"


    def __init__(self):

        import akshare as ak

        self.ak = ak


    def get_stock_list(self, top_n=5):

        df = self.ak.stock_zh_a_spot_em()

        df = df[~df['代码'].str.startswith(('8', '4', '688'))]

        df = df[~df['名称'].str.contains('ST|\\*ST', na=False)]

        df = df.sort_values('总市值', ascending=True).head(top_n)

        return [{"code": r['代码'], "name": r['名称']}

                for _, r in df.iterrows()]


    def get_history(self, code, days=120):

        end_date = datetime.date.today().strftime("%Y%m%d")

        start_date = (datetime.date.today() - datetime.timedelta(days=days*2)).strftime("%Y%m%d")

        df = self.ak.stock_zh_a_hist(symbol=code, period="daily",

                                     start_date=start_date, end_date=end_date,

                                     adjust="qfq")

        if df is None or len(df) == 0:

            return None

        df = df.rename(columns={'收盘': 'close'})

        return df[['close']].tail(days+5).reset_index(drop=True)



# ============================================================

# 选数据源：Tushare → 新浪 → akshare

# ============================================================

def get_data_source():

    # 1. 试 Tushare

    if TUSHARE_TOKEN:

        try:

            print("[数据源] 尝试 tushare...")

            src = TushareSource(TUSHARE_TOKEN)

            src.get_stock_list(top_n=1)

            print(f"   ✅ tushare 可用")

            return src

        except Exception as e:

            print(f"   ❌ tushare 失败: {e}")

    else:

        print("   ⚠️ 未配置 TUSHARE_TOKEN，跳过 tushare")


    # 2. 试新浪

    try:

        print("[数据源] 尝试 sina...")

        src = SinaSource()

        src.get_stock_list(top_n=1)

        # 测试连通性

        test = src.get_history("000001", days=10)

        if test is not None and len(test) > 0:

            print(f"   ✅ sina 可用")

            return src

        print(f"   ❌ sina 返回空数据")

    except Exception as e:

        print(f"   ❌ sina 失败: {e}")


    # 3. 试 akshare

    try:

        print("[数据源] 尝试 akshare...")

        src = AkshareSource()

        src.get_stock_list(top_n=1)

        print(f"   ✅ akshare 可用")

        return src

    except Exception as e:

        print(f"   ❌ akshare 失败: {e}")


    return None



# ============================================================

# 主扫描

# ============================================================

def scan_signals():

    today = datetime.date.today()

    print(f"\n{'='*60}")

    print(f"📊 信号扫描 @ {today} 15:30")

    print(f"{'='*60}\n")


    src = get_data_source()

    if src is None:

        print("🚨 所有数据源都不可用")

        _write_result(today, "无", [], [], [], fallback=True)

        return


    data_source_name = src.name

    print(f"\n📌 当前数据源: {data_source_name}")


    # 取候选池

    try:

        candidates = src.get_stock_list(top_n=PARAMS["candidate_pool"])

        print(f"   ✅ 候选池: {len(candidates)} 只")

    except Exception as e:

        print(f"   ❌ 候选池失败: {e}")

        _write_result(today, data_source_name, [], [], [], fallback=True)

        return


    # 扫信号

    buy_signals = []

    sell_signals = []

    no_data = []


    for c in candidates:

        try:

            df = src.get_history(c['code'], days=PARAMS["slow_window"] + 30)

            if df is None or len(df) < PARAMS["slow_window"] + 5:

                no_data.append(c['code'])

                continue


            close = df['close'].values

            fast_ma = pd.Series(close).rolling(PARAMS["fast_window"]).mean().values

            slow_ma = pd.Series(close).rolling(PARAMS["slow_window"]).mean().values


            if pd.isna(fast_ma[-1]) or pd.isna(slow_ma[-1]) or pd.isna(fast_ma[-2]) or pd.isna(slow_ma[-2]):

                no_data.append(c['code'])

                continue


            current_price = close[-1]


            if fast_ma[-1] > slow_ma[-1] and fast_ma[-2] <= slow_ma[-2]:

                buy_signals.append({

                    "code": c['code'], "name": c['name'],

                    "price": current_price,

                    "fast_ma": fast_ma[-1], "slow_ma": slow_ma[-1],

                })


            if fast_ma[-1] < slow_ma[-1] and fast_ma[-2] >= slow_ma[-2]:

                sell_signals.append({

                    "code": c['code'], "name": c['name'],

                    "price": current_price,

                })


        except Exception:

            no_data.append(c['code'])

            continue


    # 打印 + 写文件

    print(f"\n🟢 买入信号 ({len(buy_signals)} 只):")

    for s in buy_signals:

        print(f"   {s['code']} {s['name']}  价格 {s['price']:.2f}  "

              f"MA5={s['fast_ma']:.2f}  MA30={s['slow_ma']:.2f}")

    if not buy_signals:

        print("   (无)")


    print(f"\n🔴 卖出信号 ({len(sell_signals)} 只):")

    for s in sell_signals:

        print(f"   {s['code']} {s['name']}  价格 {s['price']:.2f}")

    if not sell_signals:

        print("   (无)")


    _write_result(today, data_source_name, buy_signals, sell_signals, no_data, fallback=False)



def _write_result(today, data_source, buy, sell, no_data, fallback=False):

    """统一写文件函数"""

    output_file = f"signals_{today.strftime('%Y%m%d')}.txt"

    with open(output_file, "w", encoding="utf-8") as f:

        f.write(f"信号扫描 @ {today} 15:30\n")

        f.write(f"数据源: {data_source}\n")

        f.write(f"{'='*60}\n\n")

        f.write(f"🟢 买入信号 ({len(buy)} 只):\n")

        for s in buy:

            f.write(f"  {s['code']} {s['name']}  价格 {s['price']:.2f}  "

                    f"MA5={s['fast_ma']:.2f}  MA30={s['slow_ma']:.2f}\n")

        if not buy:

            f.write("  (无)\n")

        f.write(f"\n🔴 卖出信号 ({len(sell)} 只):\n")

        for s in sell:

            f.write(f"  {s['code']} {s['name']}  价格 {s['price']:.2f}\n")

        if not sell:

            f.write("  (无)\n")

        if fallback:

            f.write(f"\n🚨 所有数据源都不可用，今日不出信号\n")

    print(f"\n💾 已保存: {output_file}")



if __name__ == "__main__":

    scan_signals()
