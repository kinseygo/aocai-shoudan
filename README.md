# 澳彩收单系统 · 2.0 独立版

在自己电脑上运行，数据保存在 `aocai.db`。也可部署到云端，任意设备联网操作。

## 功能一览

- **登录系统**：超级用户 `admin` / 密码 `gjxing1111`，可注册新用户、修改密码
- **押注入录**：数字 01-49 网格（红蓝绿波色标记）+ 生肖 + 波色，多选号码统一金额批量录入
- **文字自动录入**：支持「各字」「各包」规则，生肖与号码重叠自动相加（如 01 = 马40 + 列表20 = 60）
- **开奖结算**：特码命中 ×47；**特码记忆**：选择历史日期自动显示该期特码与中奖信息
- **应收/应付**：总押注 − 总中奖，正数应收、负数应付
- **历史查询**：按客户 / 按日 / 按月统计，含开奖号码与押注金额，含佣金 3%（按日/按月）
- **打印对账单**：选客户或全部、选月份或时间段，含开奖号码与押注金额
- **备份恢复**：一键备份、下载、上传恢复；已有备份显示**备份时间**，可**删除**备份
- **数据保存**：顶部「保存数据」一键保存，退出页面自动保存
- **2.0 UI**：苹果 iOS 风格（毛玻璃导航、圆角卡片、触摸友好），手机/平板自适应

## 启动（Windows 本机）

1. 安装 [Python 3](https://www.python.org/downloads/)（勾选 Add Python to PATH）
2. 双击 `启动澳彩收单.bat`
3. 浏览器打开登录页（默认 http://127.0.0.1:9000 ）

或命令行：

```
pip install flask
python aocai_app.py
```

## 文字录入规则

- **各字**：该生肖下面每个号码都押这个金额。马各字40 → 马的 5 个号码每个 40。
- **各包**：该生肖一共押这个金额，再平均到每个号码。鼠各包40 → 4 个号码每个 10；马各包40 → 5 个号码每个 8。
- 号码列表与生肖重叠时**自动相加**。例如马各字40 且 01 各 20 → 01 为 60。
- 支持逗号、点、斜杠；`2818` 会拆成 28 和 18。

## 云端部署（2.0）

### 方案一：GitHub 托管代码

仓库：https://github.com/kinseygo/aocai-shoudan

```
git clone https://github.com/kinseygo/aocai-shoudan.git
cd aocai-shoudan
pip install flask
python aocai_app.py
```

### 方案二：Cloudflare Tunnel 联网访问（推荐，数据在本机）

让任意设备通过自己域名访问本机程序：

1. 下载并安装 [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
2. 启动本机程序后，运行：
   ```
   cloudflared tunnel --url http://127.0.0.1:9000
   ```
3. 会得到一个 `https://xxxx.trycloudflare.com` 临时网址，任意设备打开即可访问
4. 绑定自己的域名：登录 Cloudflare 控制台 → Zero Trust → Tunnels → 创建隧道并绑定域名

### 方案三：Railway / Render 云平台部署（数据在云端）

1. 把代码推送到 GitHub
2. 在 [Railway](https://railway.app/) 或 [Render](https://render.com/) 选择 Deploy from GitHub repo
3. 设置环境变量：
   - `PORT` 由平台自动注入
   - `AOCAI_DATA_DIR=/data`（挂载持久卷保存数据库，避免重启丢数据）
4. 部署完成后平台会给公网网址，任意设备可访问，绑定自定义域名

### 方案四：PythonAnywhere（国内访问较慢，免费额度够用）

1. 注册 [PythonAnywhere](https://www.pythonanywhere.com/) 免费账号
2. 上传代码，创建 Web App（手动配置 Flask + `aocai_app.py`）
3. 数据保存在账号文件系统中

> 说明：云端部署时 SQLite 数据库文件请放在持久化存储（Railway 卷 / Render Disk / PythonAnywhere 文件系统），否则重启会丢数据。备份功能会把数据库复制到 `backups/` 目录。

## 其它说明

- 期数 = 一年中的第几天，每年 1 月 1 日从第 1 期重新开始
- 数据文件 `aocai.db` 与备份目录 `backups/` 请定期备份
