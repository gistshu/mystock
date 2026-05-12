# 對話摘要（截至目前）

## 目標需求
使用者希望建立一個離線股票追蹤工具，核心需求如下：

1. 上傳每日券商截圖（如 `sample.png`）並擷取上方表格資料  
2. 同步擷取總覽資訊（商品、現價、成本價、投資成本、帳面收入、損益、損益率）  
3. 將資料寫入本機離線資料庫（`SQLite`）  
4. 可依商品查看曲線圖與明細表，並可選擇起迄日期  
5. 自動計算每檔股票「日增減損益」  

---

## 已完成實作

### 後端（Flask + SQLite）
- 建立主程式：`app.py`
- 建立資料表：
  - `daily_summary`
  - `daily_stock_records`
- API：
  - `POST /api/parse`：解析上傳截圖
  - `POST /api/save`：寫入/更新資料
  - `GET /api/products`：商品清單
  - `GET /api/product-data`：單一商品區間資料
  - `GET /api/portfolio-totals`：區間內最新日全商品總投資/總帳面/總損益
  - `GET /api/portfolio-totals-series`：全商品每日加總序列（總投資成本、總帳面收入）
- 每次寫入後會重算 `daily_profit_change`（日增減損益）

### OCR
- 初版 tesseract 因中文語言包不足，改為 `EasyOCR(ch_tra + en)`。
- 針對券商版面做上方區域裁切 + 表格解析規則（含股數欄位干擾處理）。
- 解析結果提供前端可手動修正再入庫。

### 前端功能（單頁）
- 分頁：
  - 上傳與寫入
  - 查詢與圖表
- 查詢區：
  - 商品切換、日期切換可自動刷新資料
  - KPI：最新損益、最新日增減損益、最新損益率
  - 總覽：總投資成本、總帳面收入、總損益、統計基準日
- 圖表（商品維度）：
  1. 現價 / 成本價
  2. 投資成本 / 帳面收入
  3. 損益 / 損益率（支援雙軸/同軸切換）
- 明細表：
  - 損益、損益率 > 0 顯示紅色；< 0 顯示綠色
- 最下方新增全商品曲線圖：
  - 總投資成本 / 總帳面收入（依日期區間）

---

## 本次互動中已處理的 UI/邏輯調整
- 修正「查詢與圖表切換商品，資料不更新」問題（補 `change` 事件綁定）。
- 曲線改為三組顯示（依使用者指定分組）。
- 新增查詢區總覽資訊卡（總投資成本、總帳面收入、總損益、基準日）。
- 新增損益圖「雙軸 / 同軸」切換按鈕。
- 新增最下方「全商品總投資成本與總帳面收入」曲線圖。

---

## 專案檔案現況
- 主程式：`app.py`
- 說明：`README.md`
- 相依：`requirements.txt`
- 本摘要：`SESSION_SUMMARY.md`

---

## GitHub 進度
- 已初始化 Git 倉庫並完成提交。
- 已建立公開倉庫並推送：`https://github.com/gistshu/mystock`
- 已加入 `.gitignore` 並移除 `sample.png` 追蹤，避免公開敏感截圖資料。

---

## 更新時間
- 本摘要最後更新：2026-04-14

---

## 今日調整摘要（2026-04-15）

### 1. 新增「區間清單」頁籤（前端）
- 在既有頁籤新增第三頁：`區間清單`
- 可設定：
  - 起始日期
  - 結束日期
- 可一鍵查詢「時間範圍內所有商品」資料

### 2. 新增全商品區間清單 API（後端）
- 新增 API：`GET /api/all-product-data`
- 支援 query 參數：
  - `start`
  - `end`
- 回傳欄位：
  - `record_date`
  - `product`
  - `current_price`
  - `cost_price`
  - `investment_cost`
  - `book_income`
  - `profit_loss`
  - `profit_loss_rate`
  - `daily_profit_change`

### 3. 排序規則（依需求）
- 清單結果排序已調整為：
  - 商品：遞減（`product DESC`）
  - 時間：遞減（`record_date DESC`）

### 4. 使用方式
1. 啟動 `mystock` 服務後，進入「區間清單」頁籤
2. 選擇起訖日期
3. 點「查詢全部商品」
4. 下方表格即顯示區間內所有商品資料（商品+時間遞減）

### 5. 影響檔案
- `app.py`（HTML/JS 分頁與清單查詢邏輯、`/api/all-product-data` 路由）

### 6. 備註
- 本次未更動資料表 schema，直接沿用 `daily_stock_records`。
- 如無資料，前端會顯示 0 筆結果。

## 更新時間
- 本摘要最後更新：2026-04-15

---

## 今日調整摘要（2026-04-20）

### 1. 補上「股數」欄位（前後端 + DB）
- OCR 解析結果新增 `shares`（股數）
- 上傳頁可手動編修股數後再寫入
- `daily_stock_records` 新增 `shares REAL` 欄位
- 已加入既有資料庫自動補欄位（migration）
- 查詢 API 也回傳 `shares`，包含：
  - `GET /api/product-data`
  - `GET /api/all-product-data`

### 2. 新增「總投資」頁籤
- 最上方新增第四個頁籤：`總投資`
- 將原本「查詢與圖表」頁最下方的
  - 「總投資成本 / 總帳面收入（全商品）」曲線
  移動到此新頁籤

### 3. 總投資頁新增每日總覽表格
- 在總投資曲線下方新增表格，顯示每日：
  - 總投資成本
  - 總帳面收入
  - 總損益
  - 總損益率(%)

### 4. API 擴充（總投資序列）
- `GET /api/portfolio-totals-series` 新增回傳欄位：
  - `total_profit_loss`
  - `total_profit_rate`
- `total_profit_rate` 計算方式：
  - `SUM(profit_loss) * 100 / SUM(investment_cost)`
  - 若分母為 0 則回傳 `NULL`

### 5. 驗證紀錄
- `sample.png` 實測可解析出 `shares`（例如 `16,000`）
- 寫入與查詢流程已驗證 `shares` 可正確保存與回傳
- `python3 -m py_compile app.py` 通過

## 更新時間
- 本摘要最後更新：2026-04-20

---

## 今日調整摘要（2026-05-05）

### 1. 總投資頁每日總覽表格新增欄位
- 在「總投資」頁的「每日總覽」表格中，
  於「總損益率(%)」左側新增欄位：`每天差異金額`。

### 2. 每天差異金額計算邏輯
- 前端在載入 `GET /api/portfolio-totals-series` 的資料後，
  依日期升冪計算：
  - `每天差異金額 = 當日總損益 - 前一日總損益`
- 若為首日（無前一日可比較）則顯示 `-`。

### 3. 表格顯示與樣式
- 新欄位數值沿用既有損益顏色規則：
  - 正值：紅色
  - 負值：綠色
  - 無值：`-`

### 4. 影響檔案
- `app.py`（總投資頁表頭與 `loadPortfolioPageData()` 表格渲染邏輯）

### 5. 驗證紀錄
- `python3 -m py_compile app.py` 通過。

## 更新時間
- 本摘要最後更新：2026-05-05

---

## 今日調整摘要（2026-05-12）

### 1. 區間清單頁（第 5 頁）日增減損益顏色規則調整
- 針對「5) 依起訖日期查看所有商品資訊清單」下方表格，
  將 `日增減損益` 欄位套用損益顏色樣式。
- 顯示規則：
  - 正數：紅色
  - 負數：綠色

### 2. 實作細節
- 前端 `loadAllProductData()` 的表格渲染欄位：
  - 由 `<td>${fmt(r.daily_profit_change)}</td>`
  - 改為 `<td class="${profitClass(r.daily_profit_change)}">${fmt(r.daily_profit_change)}</td>`
- 僅調整第 5 頁區間清單表格，不影響資料庫 schema 與 API 回傳。

### 3. 影響檔案
- `app.py`（`loadAllProductData()` 表格渲染）

### 4. 驗證紀錄
- `python3 -m py_compile app.py` 通過。

## 更新時間
- 本摘要最後更新：2026-05-12
