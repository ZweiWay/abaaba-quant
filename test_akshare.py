import sys
print("="*60)
print("Python:", sys.version.split()[0])
print("="*60)

print("\n[测试 1] 导入 akshare")
try:
    import akshare as ak
    print(f"✅ 成功, 版本 {ak.__version__}")
except ImportError as e:
    print(f"❌ 失败: {e}")
    print("   解决: pip install akshare")
    sys.exit(1)

print("\n[测试 2] 取实时行情 (ak.stock_zh_a_spot_em)")
try:
    df = ak.stock_zh_a_spot_em()
    print(f"✅ 成功, {len(df)} 只股票")
    print(f"   列名: {list(df.columns)[:10]}")
except Exception as e:
    print(f"❌ 失败: {type(e).__name__}: {e}")

print("\n[测试 3] 取单只股票历史数据 (000001)")
try:
    df = ak.stock_zh_a_hist(symbol="000001", period="daily", adjust="qfq")
    print(f"✅ 成功, {len(df)} 行")
    print(f"   列名: {list(df.columns)}")
except Exception as e:
    print(f"❌ 失败: {type(e).__name__}: {e}")

print("\n[测试 4] 网络连通性")
try:
    import requests
    r = requests.get("https://www.baidu.com", timeout=5)
    print(f"✅ 百度可达, 状态码 {r.status_code}")
except Exception as e:
    print(f"❌ 失败: {e}")

print("\n" + "="*60)
print("测试完成")
