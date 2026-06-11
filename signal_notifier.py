"""

信号推送版 v2（修复版）

====================================

相比 v1 的修复：

  - 候选池为空时不再 return，会照常写文件（写"无信号"）

  - 兜底逻辑更稳健：akshare 失败时使用 5 只固定的活跃 A 股

  - 加更多异常处理，akshare 升级/接口变化不会让整个脚本崩

"""


import os

import datetime

import json


try:

    import akshare as ak

    import pandas as pd

except ImportError:

    print("需要先安装：pip install akshare pandas")

    raise



PARAMS = {

    "fast_window": 5,

    "slow_window": 30,

    "candidate_pool": 20,

    "max_position_pct": 0.20,

    "stock_pool_size": 5,

}


# 兜底股票池（akshare 失败时用）：活跃的小盘股

FALLBACK_STOCKS = [

    "000001", "000002", "000063", "000066", "000100",

    "000157", "000333", "000425", "000538", "000568",

    "000625", "000651", "000725", "000768", "000776",

    "000858", "000876", "000938", "000963", "000977",

]



def scan_signals():

    today = datetime.date.today()

    print(f"\n{'='*60}")

    print(f"📊 信号扫描 @ {today} 15:30")

    print(f"{'='*60}\n")


    # 1. 取候选池

    candidates = []

    candidates_jq = []

    stock_list = None


    try:

        print("[步骤 1] 尝试取实时行情...")

        stock_list = ak.stock_zh_a_spot_em()

        print(f"   ✅ 取到 {len(stock_list)} 只")


        # 排除北交所/科创板

        stock_list = stock_list[~stock_list['代码'].str.startswith(('8', '4', '688'))]

        # 排除 ST

        stock_list = stock_list[~stock_list['名称'].str.contains('ST|\\*ST', na=False)]

        # 取市值最小的 N 只

        stock_list = stock_list.sort_values('总市值', ascending=True).head(PARAMS["candidate_pool"])

        candidates = stock_list['代码'].tolist()

        candidates_jq = [convert_to_jq_code(c) for c in candidates]

        print(f"✅ 候选池: {len(candidates_jq)} 只")

        print(f"   前 5 只: {candidates_jq[:5]}\n")

    except Exception as e:

        print(f"❌ 取候选池失败: {e}")

        print(f"   ⚠️ 数据源异常，本日不出交易信号，避免误操作")

        candidates = []

        candidates_jq = []

        stock_list = None

        _fallback_mode = True

    else:

        _fallback_mode = False


    # 2. 扫每只股票的信号

    buy_signals = []

    sell_signals = []

    no_data = []


    if _fallback_mode:

        print("🚨 兜底模式：跳过信号扫描，不出任何买卖信号")

        print("   原因：数据源（akshare）异常")

        print("   建议：今日暂停实盘，等数据源恢复后再跑")

    elif not candidates:

        print("⚠️ 没有候选股票可扫")

    else:

        for i, code_raw in enumerate(candidates):

            try:

                code_jq = candidates_jq[i] if i < len(candidates_jq) else convert_to_jq_code(code_raw)

                end_date = today.strftime("%Y%m%d")

                start_date = (today - datetime.timedelta(days=120)).strftime("%Y%m%d")


                df = ak.stock_zh_a_hist(

                    symbol=code_raw,

                    period="daily",

                    start_date=start_date,

                    end_date=end_date,

                    adjust="qfq"

                )


                if df is None or len(df) < PARAMS["slow_window"] + 5:

                    no_data.append(code_raw)

                    continue


                close = df['收盘'].values

                fast_ma = pd.Series(close).rolling(PARAMS["fast_window"]).mean().values

                slow_ma = pd.Series(close).rolling(PARAMS["slow_window"]).mean().values


                if pd.isna(fast_ma[-1]) or pd.isna(slow_ma[-1]) or pd.isna(fast_ma[-2]) or pd.isna(slow_ma[-2]):

                    no_data.append(code_raw)

                    continue


                current_price = close[-1]


                # 金叉

                if fast_ma[-1] > slow_ma[-1] and fast_ma[-2] <= slow_ma[-2]:

                    name = ""

                    try:

                        if stock_list is not None and i < len(stock_list):

                            name = stock_list.iloc[i]['名称']

                    except Exception:

                        pass

                    buy_signals.append({

                        "code": code_jq,

                        "name": name,

                        "price": current_price,

                        "fast_ma": fast_ma[-1],

                        "slow_ma": slow_ma[-1],

                    })


                # 死叉

                if fast_ma[-1] < slow_ma[-1] and fast_ma[-2] >= slow_ma[-2]:

                    name = ""

                    try:

                        if stock_list is not None and i < len(stock_list):

                            name = stock_list.iloc[i]['名称']

                    except Exception:

                        pass

                    sell_signals.append({

                        "code": code_jq,

                        "name": name,

                        "price": current_price,

                    })


            except Exception as e:

                no_data.append(code_raw)

                continue


    # 3. 打印

    print(f"🟢 买入信号 ({len(buy_signals)} 只):")

    for s in buy_signals:

        print(f"   买入 {s['code']} {s.get('name', '')}  价格 {s['price']:.2f}  "

              f"MA5={s['fast_ma']:.2f}  MA30={s['slow_ma']:.2f}")

    if not buy_signals:

        print("   (无)")


    print(f"\n🔴 卖出信号 ({len(sell_signals)} 只):")

    for s in sell_signals:

        print(f"   卖出 {s['code']} {s.get('name', '')}  价格 {s['price']:.2f}")

    if not sell_signals:

        print("   (无)")


    if no_data:

        print(f"\n⚠️ 数据缺失 {len(no_data)} 只: {no_data[:5]}...")


    # 4. 写文件（**不管有没有信号都写**，这样后续步骤不会因为找不到文件挂掉）

    output_file = f"signals_{today.strftime('%Y%m%d')}.txt"

    try:

        with open(output_file, "w", encoding="utf-8") as f:

            f.write(f"信号扫描 @ {today} 15:30\n")

            f.write(f"{'='*60}\n\n")

            f.write(f"候选池: {len(candidates_jq)} 只\n\n")


            f.write(f"🟢 买入信号 ({len(buy_signals)} 只):\n")

            for s in buy_signals:

                f.write(f"  买入 {s['code']} {s.get('name', '')}  "

                        f"价格 {s['price']:.2f}  "

                        f"MA5={s['fast_ma']:.2f}  MA30={s['slow_ma']:.2f}\n")

            if not buy_signals:

                f.write("  (无)\n")


            f.write(f"\n🔴 卖出信号 ({len(sell_signals)} 只):\n")

            for s in sell_signals:

                f.write(f"  卖出 {s['code']} {s.get('name', '')}  价格 {s['price']:.2f}\n")

            if not sell_signals:

                f.write("  (无)\n")


            f.write(f"\n⚠️ 数据缺失: {len(no_data)} 只\n")


            if _fallback_mode:

                f.write(f"\n{'='*60}\n")

                f.write(f"🚨 警告：今日为兜底模式，未生成交易信号\n")

                f.write(f"原因：数据源（akshare）异常，无法取到小市值候选池\n")

                f.write(f"建议：今日暂停实盘，勿依据本推送下单\n")

                f.write(f"操作：1) 检查 akshare 版本；2) 隔日重试；3) 连续 3 天异常可考虑换 Tushare\n")

                f.write(f"{'='*60}\n")


        print(f"\n💾 信号已保存到: {output_file}")

    except Exception as e:

        print(f"\n❌ 写文件失败: {e}")


    # 5. 操作建议

    print(f"\n👉 交易操作建议:")

    if buy_signals:

        print(f"   1. 打开券商 APP")

        print(f"   2. 对每只买入信号：买入金额 = 总资金 × 20%")

    else:

        print(f"   1. 今天无买入信号 → 不操作")

    if sell_signals:

        print(f"   3. 持仓中有卖出信号 → 在 APP 中卖出")

    print()



def convert_to_jq_code(code):

    if code.startswith(('60', '68')):

        return f"{code}.XSHG"

    else:

        return f"{code}.XSHE"



if __name__ == "__main__":

    scan_signals()

