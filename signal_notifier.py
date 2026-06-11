"""

信号推送版 v4（双数据源）

====================================

数据源策略：

  1. 先用 akshare（免费，无 token）

  2. akshare 失败 → 自动切换 tushare

  3. 两个都失败 → 兜底模式，不出任何买卖信号

"""


import os

import datetime

import json

import time


import pandas as pd


# ============================================================

# 数据源抽象：akshare / tushare

# ============================================================


class DataSource:

    """统一的数据源接口"""

    def get_stock_list(self, top_n=20):

        """返回市值最小的 N 只股票，格式: [{'code': '000001', 'name': '平安银行'}, ...]"""

        raise NotImplementedError


    def get_history(self, code, days=120):

        """返回最近 N 天日线，格式: DataFrame with 'close' column"""

        raise NotImplementedError


    @property

    def name(self):

        raise NotImplementedError



class AkshareSource(DataSource):

    """akshare 数据源"""


    @property

    def name(self):

        return "akshare"


    def get_stock_list(self, top_n=20):

        df = ak.stock_zh_a_spot_em()

        # 排除北交所/科创板

        df = df[~df['代码'].str.startswith(('8', '4', '688'))]

        # 排除 ST

        df = df[~df['名称'].str.contains('ST|\\*ST', na=False)]

        # 按市值排序，取最小的 N

        df = df.sort_values('总市值', ascending=True).head(top_n)

        return [

            {"code": row['代码'], "name": row['名称']}

            for _, row in df.iterrows()

        ]


    def get_history(self, code, days=120):

        end_date = datetime.date.today().strftime("%Y%m%d")

        start_date = (datetime.date.today() - datetime.timedelta(days=days*2)).strftime("%Y%m%d")

        df = ak.stock_zh_a_hist(

            symbol=code,

            period="daily",

            start_date=start_date,

            end_date=end_date,

            adjust="qfq"

        )

        if df is None or len(df) == 0:

            return None

        df = df.rename(columns={'收盘': 'close'})

        return df[['close']].tail(days + 5).reset_index(drop=True)



class TushareSource(DataSource):

    """tushare 数据源（需 token）"""


    def __init__(self, token):

        import tushare as ts

        ts.set_token(token)

        self.pro = ts.pro_api()


    @property

    def name(self):

        return "tushare"


    def get_stock_list(self, top_n=20):

        # tushare 用 daily_basic 取市值

        today = datetime.date.today().strftime("%Y%m%d")

        df = self.pro.daily_basic(

            trade_date=today,

            fields='ts_code,total_mv,name'

        )

        if df is None or len(df) == 0:

            # 如果今天没数据，用最近的

            df = self.pro.daily_basic(

                fields='ts_code,total_mv,name'

            ).sort_values('trade_date', ascending=False).head(top_n * 5)


        # 排除北交所/科创板

        df = df[~df['ts_code'].str.startswith(('8', '4', '688'))]

        # 排除 ST

        df = df[~df['name'].str.contains('ST|\\*ST', na=False)]

        # 按市值排序

        df = df.sort_values('total_mv', ascending=True).head(top_n)


        result = []

        for _, row in df.iterrows():

            # ts_code 是 000001.SZ 格式，需要转成纯代码

            code = row['ts_code'].split('.')[0]

            result.append({"code": code, "name": row['name']})

        return result


    def get_history(self, code, days=120):

        end_date = datetime.date.today().strftime("%Y%m%d")

        start_date = (datetime.date.today() - datetime.timedelta(days=days*2)).strftime("%Y%m%d")


        # tushare 需要带后缀

        suffix = '.SH' if code.startswith(('60', '68')) else '.SZ'

        df = self.pro.daily(

            ts_code=code + suffix,

            start_date=start_date,

            end_date=end_date,

            adj='qfq'

        )

        if df is None or len(df) == 0:

            return None

        df = df.sort_values('trade_date', ascending=True).reset_index(drop=True)

        return df[['close']].tail(days + 5).reset_index(drop=True)



# ============================================================

# 核心扫描逻辑

# ============================================================


PARAMS = {

    "fast_window": 5,

    "slow_window": 30,

    "candidate_pool": 20,

}


TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")



def get_data_source():

    """先试 akshare，失败切 tushare"""

    try:

        print("[数据源] 尝试 akshare...")

        src = AkshareSource()

        # 用一个简单调用测试连通性

        src.get_stock_list(top_n=1)

        print(f"   ✅ akshare 可用")

        return src

    except Exception as e:

        print(f"   ❌ akshare 失败: {e}")


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

        print("   ⚠️ 未配置 TUSHARE_TOKEN，跳过")


    return None



def scan_signals():

    today = datetime.date.today()

    print(f"\n{'='*60}")

    print(f"📊 信号扫描 @ {today} 15:30")

    print(f"{'='*60}\n")


    buy_signals = []

    sell_signals = []

    no_data = []

    data_source_name = "无"

    fallback_mode = True


    # 1. 取数据源

    src = get_data_source()


    if src is None:

        print("🚨 所有数据源都不可用，今日不出信号")

    else:

        data_source_name = src.name

        fallback_mode = False


        # 2. 取候选池

        try:

            print(f"\n[步骤 2] 用 {src.name} 取候选池...")

            candidates = src.get_stock_list(top_n=PARAMS["candidate_pool"])

            print(f"   ✅ 候选池: {len(candidates)} 只")

            for c in candidates[:3]:

                print(f"      {c['code']} {c['name']}")

        except Exception as e:

            print(f"   ❌ 取候选池失败: {e}")

            candidates = []

            fallback_mode = True


        # 3. 扫信号

        if not fallback_mode and candidates:

            print(f"\n[步骤 3] 扫信号...")

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


                    # 金叉

                    if fast_ma[-1] > slow_ma[-1] and fast_ma[-2] <= slow_ma[-2]:

                        buy_signals.append({

                            "code": c['code'],

                            "name": c['name'],

                            "price": current_price,

                            "fast_ma": fast_ma[-1],

                            "slow_ma": slow_ma[-1],

                        })


                    # 死叉

                    if fast_ma[-1] < slow_ma[-1] and fast_ma[-2] >= slow_ma[-2]:

                        sell_signals.append({

                            "code": c['code'],

                            "name": c['name'],

                            "price": current_price,

                        })


                except Exception as e:

                    no_data.append(c['code'])

                    continue


    # 4. 打印

    print(f"\n🟢 买入信号 ({len(buy_signals)} 只):")

    for s in buy_signals:

        print(f"   买入 {s['code']} {s['name']}  价格 {s['price']:.2f}  "

              f"MA5={s['fast_ma']:.2f}  MA30={s['slow_ma']:.2f}")

    if not buy_signals:

        print("   (无)")


    print(f"\n🔴 卖出信号 ({len(sell_signals)} 只):")

    for s in sell_signals:

        print(f"   卖出 {s['code']} {s['name']}  价格 {s['price']:.2f}")

    if not sell_signals:

        print("   (无)")


    if no_data:

        print(f"\n⚠️ 数据缺失 {len(no_data)} 只")


    # 5. 写文件（**永远写**，不管有没有信号）

    output_file = f"signals_{today.strftime('%Y%m%d')}.txt"

    try:

        with open(output_file, "w", encoding="utf-8") as f:

            f.write(f"信号扫描 @ {today} 15:30\n")

            f.write(f"数据源: {data_source_name}\n")

            f.write(f"{'='*60}\n\n")

            f.write(f"🟢 买入信号 ({len(buy_signals)} 只):\n")

            for s in buy_signals:

                f.write(f"  买入 {s['code']} {s['name']}  "

                        f"价格 {s['price']:.2f}  "

                        f"MA5={s['fast_ma']:.2f}  MA30={s['slow_ma']:.2f}\n")

            if not buy_signals:

                f.write("  (无)\n")


            f.write(f"\n🔴 卖出信号 ({len(sell_signals)} 只):\n")

            for s in sell_signals:

                f.write(f"  卖出 {s['code']} {s['name']}  价格 {s['price']:.2f}\n")

            if not sell_signals:

                f.write("  (无)\n")


            f.write(f"\n⚠️ 数据缺失: {len(no_data)} 只\n")


            if fallback_mode:

                f.write(f"\n{'='*60}\n")

                f.write(f"🚨 兜底模式：所有数据源都不可用，未生成交易信号\n")

                f.write(f"建议：今日暂停实盘\n")

                f.write(f"{'='*60}\n")


        print(f"\n💾 信号已保存到: {output_file}")

    except Exception as e:

        print(f"\n❌ 写文件失败: {e}")


    print(f"\n👉 数据源: {data_source_name} | "

          f"买入 {len(buy_signals)} 只, 卖出 {len(sell_signals)} 只")



if __name__ == "__main__":

    # 延迟 import akshare/tushare（如果没装不立即报错）

    try:

        import akshare as ak

    except ImportError:

        ak = None

        print("⚠️ akshare 未安装")


    scan_signals()
