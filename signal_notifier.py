"""

信号推送版（每日运行一次）

====================================

作用：每天收盘后扫一遍股票池，告诉你"今天该买/卖什么"

运行方式：本地电脑或云服务器，每天 15:30 跑一次

输出：信号文件 + 屏幕打印


这是给"3000 元试水阶段"用的——你看完信号手动去券商 APP 下单。

等未来 5% 上线了，再换成 PTrade/QMT 全自动。

"""


import os

import datetime

import json


# 尝试用 akshare 取数据（免费，无需 token）

try:

    import akshare as ak

    import pandas as pd

except ImportError:

    print("需要先安装 akshare 和 pandas：pip install akshare pandas")

    raise



# ============================================================

# 参数（和你回测版一致）

# ============================================================

PARAMS = {

    "fast_window": 5,

    "slow_window": 30,

    "candidate_pool": 20,    # 候选池大小

    "max_position_pct": 0.20,

    "stock_pool_size": 5,

}



# ============================================================

# 主函数：扫一次信号

# ============================================================

def scan_signals():

    today = datetime.date.today()

    print(f"\n{'='*60}")

    print(f"📊 信号扫描 @ {today} 15:30")

    print(f"{'='*60}\n")


    # 1. 取候选池（用同花顺/东财的全 A 列表）

    try:

        stock_list = ak.stock_zh_a_spot_em()  # 全 A 实时行情

        # 排除北交所(8/4 开头)、科创板(688 开头)

        stock_list = stock_list[~stock_list['代码'].str.startswith(('8', '4', '688'))]

        # 排除 ST

        stock_list = stock_list[~stock_list['名称'].str.contains('ST|\\*ST', na=False)]

        # 取市值最小的 20 只（小市值因子）

        # 注意：akshare 的市值列叫"总市值"

        stock_list = stock_list.sort_values('总市值', ascending=True).head(PARAMS["candidate_pool"])

        candidates = stock_list['代码'].tolist()

        # 转成聚宽格式（带后缀 .XSHE/.XSHG）

        candidates_jq = [convert_to_jq_code(c) for c in candidates]

        print(f"✅ 候选池: {len(candidates_jq)} 只")

        print(f"   前 5 只: {candidates_jq[:5]}\n")

    except Exception as e:

        print(f"❌ 取候选池失败: {e}")

        return


    # 2. 扫每只股票的信号

    buy_signals = []

    sell_signals = []

    no_data = []


    for i, (code_raw, code_jq) in enumerate(zip(candidates, candidates_jq)):

        try:

            # 取最近 60 天数据

            end_date = today.strftime("%Y%m%d")

            start_date = (today - datetime.timedelta(days=120)).strftime("%Y%m%d")


            df = ak.stock_zh_a_hist(

                symbol=code_raw,

                period="daily",

                start_date=start_date,

                end_date=end_date,

                adjust="qfq"  # 前复权

            )


            if df is None or len(df) < PARAMS["slow_window"] + 5:

                no_data.append(code_jq)

                continue


            close = df['收盘'].values

            fast_ma = pd.Series(close).rolling(PARAMS["fast_window"]).mean().values

            slow_ma = pd.Series(close).rolling(PARAMS["slow_window"]).mean().values


            # 跳过 NaN

            if pd.isna(fast_ma[-1]) or pd.isna(slow_ma[-1]):

                no_data.append(code_jq)

                continue


            current_price = close[-1]


            # 金叉：今日快线 > 慢线 且 昨日快线 ≤ 慢线

            if fast_ma[-1] > slow_ma[-1] and fast_ma[-2] <= slow_ma[-2]:

                buy_signals.append({

                    "code": code_jq,

                    "name": stock_list.iloc[i]['名称'],

                    "price": current_price,

                    "fast_ma": fast_ma[-1],

                    "slow_ma": slow_ma[-1],

                })


            # 死叉

            if fast_ma[-1] < slow_ma[-1] and fast_ma[-2] >= slow_ma[-2]:

                sell_signals.append({

                    "code": code_jq,

                    "name": stock_list.iloc[i]['名称'],

                    "price": current_price,

                })


        except Exception as e:

            no_data.append(code_jq)

            continue


    # 3. 打印 + 写文件

    print(f"🟢 买入信号 ({len(buy_signals)} 只):")

    for s in buy_signals:

        print(f"   买入 {s['code']} {s['name']}  价格 {s['price']:.2f}  "

              f"MA5={s['fast_ma']:.2f}  MA30={s['slow_ma']:.2f}")


    print(f"\n🔴 卖出信号 ({len(sell_signals)} 只):")

    for s in sell_signals:

        print(f"   卖出 {s['code']} {s['name']}  价格 {s['price']:.2f}")


    if no_data:

        print(f"\n⚠️ 数据缺失 {len(no_data)} 只: {no_data[:5]}...")


    # 4. 写文件（你每天看这个文件）

    output_file = f"signals_{today.strftime('%Y%m%d')}.txt"

    with open(output_file, "w", encoding="utf-8") as f:

        f.write(f"信号扫描 @ {today} 15:30\n")

        f.write(f"{'='*60}\n\n")

        f.write(f"候选池: {len(candidates_jq)} 只\n\n")


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


    print(f"\n💾 信号已保存到: {output_file}")

    print(f"\n👉 你现在要做的：")

    if buy_signals:

        print(f"   1. 打开券商 APP")

        print(f"   2. 对每只买入信号：买入金额 = 总资金 × 20%")

        print(f"   3. 注意：单只不超过 3000 × 20% = 600 元（3000 阶段）")

    else:

        print(f"   1. 今天没有买入信号 → 不操作")

        print(f"   2. 如果你持仓里有卖出信号 → 在 APP 里卖出")

        print(f"   3. 持仓里的股票如果没出现卖出信号 → 继续持有")

    print()



# ============================================================

# 工具函数

# ============================================================

def convert_to_jq_code(code):

    """6 位代码 → 聚宽格式"""

    if code.startswith(('60', '68')):

        return f"{code}.XSHG"

    else:

        return f"{code}.XSHE"



# ============================================================

# 入口

# ============================================================

if __name__ == "__main__":

    scan_signals()



"""

========================================

怎么用

========================================

1. 装依赖：pip install akshare pandas

2. 跑一次试试：python signal_notifier.py

3. 看到输出后，就知道每天该买/卖什么


怎么"每天自动跑"：

- Mac/Linux：cron 设置每天 15:30 跑

- Windows：用任务计划程序

- 云服务器：用 crontab

- 最简单：用 GitHub Actions 定时（免费）


示例 crontab（每天 15:35 跑）：

35 15 * * 1-5 cd /path/to/this/script && python signal_notifier.py >> signal_log.txt 2>&1


进阶：把信号通过 Server酱/企业微信/邮件推送到你手机

"""
