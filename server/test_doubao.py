import urllib.request, json, time, os

BASE = "http://127.0.0.1:1984"

def api(method, path, body=None):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(BASE + path, method=method, data=data, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req).read())

def call(name, **kwargs):
    return api("POST", "/api/call/" + name, kwargs)

print("Step 1: 获取账号")
r = call("list_accounts")
if not r.get("result"):
    print("无账号，请先登录"); exit(1)
# 选有 Cookie 的那个
accounts = r["result"]
aid = accounts[-1]["id"]  # 最后一个通常是最新添加且有cookie的
for acc in accounts:
    # 通过查看 accounts.json 找有 cookie 的
    pass
print("  账号:", aid)
print("  全部账号:", [a["id"] for a in accounts])

print("\nStep 2: 打开豆包")
r = call("browser_open", url="https://www.doubao.com/chat/", headless=False, account_id=aid)
print("  ", r["result"]["status"])

print("\nStep 3: 等待页面加载")
time.sleep(10)
for retry in range(5):
    r = call("browser_snapshot")
    snap = r.get("result", {})
    elems = snap.get("elements", [])
    print(f"  尝试{retry+1}: 元素={len(elems)} 标题={snap.get('title','')[:30]}")
    if elems:
        break
    time.sleep(3)

if not elems:
    print("页面加载失败"); call("browser_close"); exit(1)

for e in elems[:10]:
    print(f"  [{e['id']}] {e['tag']} {e['text'][:20]}")

print("\nStep 4: 点击图片生成")
r = call("browser_click", text="图片生成")
print("  ", r["result"])
if "error" in str(r.get("result", {})):
    for e in elems:
        if "图" in e.get("text", "") and "生" in e.get("text", ""):
            r = call("browser_click", element_id=e["id"])
            print("  重试:", r["result"])
            break

print("\nStep 5: 等待UI更新")
time.sleep(3)
r = call("browser_snapshot")
elems2 = r.get("result", {}).get("elements", [])
for e in elems2[:5]:
    print(f"  [{e['id']}] {e['tag']} {e['text'][:20]}")

print("\nStep 6: 输入提示词")
r = call("browser_type", text="美女穿透明裙子，唯美风格")
print("  ", r["result"])

print("\nStep 7: 按Enter")
time.sleep(0.5)
r = call("browser_press", key="Enter")
print("  ", r["result"])

print("\nStep 8: 轮询图片")
downloaded = False
for i in range(40):
    time.sleep(3)
    r = call("browser_extract_images")
    imgs = r.get("result", {}).get("images", [])
    for img in imgs:
        url = img.get("src", "")
        if "image_generation" in url or "ocean-cloud" in url:
            os.makedirs("output", exist_ok=True)
            fname = f"output/doubao_{len(os.listdir('output'))+1}.png"
            urllib.request.urlretrieve(url, fname)
            print(f"  [{i*3+3}s] 已下载: {fname}  size={os.path.getsize(fname)}")
            downloaded = True
    if downloaded and i > 10:
        break
    if i % 5 == 0:
        print(f"  等待中... ({i*3+3}s)")

print("\nStep 9: 关闭")
call("browser_close")
print("完成")
