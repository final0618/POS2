# 會員及紅利點數後端規格

本文件描述現有實作，範圍為會員、會員點數、會員下單及後台會員查詢。完整專案規格另見 [後端 API 規格](../早餐店規格/backend.md)；介面行為見 [前端規格](./前端規格.md)。

## 架構與啟動

- FastAPI 由 `src/main.py` 建立；會員 API 位於 `src/members.py`、點數邏輯位於 `src/loyalty.py`、管理 API 位於 `src/admin.py`。
- 使用 `data/pos.db` SQLite；初始化由 `src/database.py` 呼叫 `src/loyalty_schema.py` 的版本化遷移，版本記錄於 `schema_migrations`。
- 專案根目錄執行 `.\run.bat`，預設服務 `http://127.0.0.1:8001`。部署至公開網路時應使用 HTTPS。
- 金額為新台幣整數、點數為整數；時間以 UTC ISO 8601 儲存，介面顯示台北時間。

## 身分與安全

### 會員

- 註冊、登入使用台灣手機及密碼。後端移除手機中的空白與連字號，結果需符合 `09` 開頭、共 10 位數；手機正規化後唯一。
- 密碼長度為 10 至 128 字元，以隨機鹽及 `scrypt` 雜湊儲存，不儲存明文。註冊後須另行登入；目前沒有手機所有權驗證或線上忘記密碼功能。
- 登入成功發出 `gmc_member_session` cookie，有效期 7 天，`HttpOnly`、`SameSite=Strict`、路徑 `/`，HTTPS 下設為 `Secure`；資料庫僅保存 token 雜湊。登出撤銷 session 並清除 cookie。過期、撤銷或停用會員的 session 不可用。
- 每 15 分鐘內手機或來源 IP 達 5 次失敗後暫時拒絕登入；輸入不存在帳號、停用帳號或密碼錯誤均顯示一般化錯誤。
- 註冊、登入、登出及會員下單若帶有 `Origin`，必須符合請求的 scheme 與 host；未附 `Origin` 不做此比對。CORS 不允許跨來源憑證。
- 會員點數 API 僅依 session 辨識本人；訂單的會員 ID 由後端決定，頂層額外的 `member_id` 會被拒絕。

### 管理員

- 管理 API 使用獨立的 `gmc_admin_session`，由 `ADMIN_USERNAME`、`ADMIN_PASSWORD`、`ADMIN_SESSION_SECRET` 環境變數設定；有效期 8 小時，cookie 路徑為 `/api/admin`。
- 會員列表及明細必須通過管理員驗證，回應設定 `Cache-Control: no-store`；不回傳會員密碼雜湊。列表及明細會向管理員顯示完整手機號碼。

## 點數與訂單規則

- 初始規則為實付每 10 元累積 1 點，零頭捨去；每 100 點折抵 1 元。可折抵至應付 0 元，不得超過可用點數或訂單總額。
- 訪客可不登入下單；訪客訂單 `member_id` 為 NULL，不累點。會員身分由有效 session 關聯至新訂單。
- 新會員訂單提交時立即扣除折抵點數；未付款訂單不會自動取消或釋放點數。點數按最早到期、相同到期時間按批次 ID 順序扣除。
- 會員訂單同時為 `completed`、`paid` 才累點；兩種狀態可先後更新。累點基礎為折抵後 `payable_amount`，例如 199 元得 19 點；應付 0 元不產生累點交易。
- 點數自取得日起依台北時間加 12 個曆月、同一時刻到期；遇目標月份沒有原日則使用該月最後一天。
- 可用餘額為未到期批次的剩餘點數加總。會員點數／歷史查詢、管理員歷史查詢及非零折抵時，會將到期批次入帳為 `expire`；管理員會員列表僅排除已到期批次，不執行到期入帳。即將到期為現在之後至 30 天內（含上界）的未使用點數。
- 會員訂單取消或退款時產生反向交易；若原累點已部分使用或已到期，或折抵所用批次已過期／無法退還，回傳 409，不更新狀態及點數。已取消／已退款會員訂單不得重新開啟；不支援部分退款。
- 訂單、扣點、批次分配、累點及沖銷使用同一 SQLite 寫入交易；帳本冪等鍵避免重複入帳。歷史帳本不刪除，折抵取消以 `reversal` 追溯原交易。
- `orders.total_amount` 為折抵前金額，`points_discount_amount` 為折抵金額，`payable_amount` 為折抵後應付。原營收儀表板仍以非取消訂單折抵前總額統計，包含未付款，不等於實收。

## API 規格

JSON 欄位範例均為示意，不代表實際會員資料。一般錯誤回傳 `{"detail": "訊息"}`；資料格式驗證錯誤的 `detail` 可為陣列。

### 會員註冊、登入、登出

| 方法及路徑 | 輸入 | 成功回應 |
| --- | --- | --- |
| `POST /api/members/register` | `{"phone":"0912345678","password":"<10至128字元>"}` | 201，`{"message":"註冊完成，請登入。"}` |
| `POST /api/members/login` | 同上 | 200，`{"message":"登入成功。"}`，並設定會員 cookie |
| `POST /api/members/logout` | 無 | 200，`{"message":"已登出。"}`，撤銷 cookie 對應 session |
| `GET /api/members/session` | 會員 cookie，若有 | 200，`{"authenticated":true,"phone":"5678"}`；無 cookie 時為 `{"authenticated":false,"phone":null}`；有無效 cookie 時為 401 |

註冊重複手機回傳 409，格式錯誤 422；登入失敗 401，超過限制 429，來源不符 403。

### 會員查詢點數

`GET /api/members/me/points` 需有效會員 session：

```json
{
  "available_points": 391,
  "expiring": [{"expires_at":"2027-01-15T04:30:00.000Z","points":100}]
}
```

`GET /api/members/me/points/transactions?limit=20&offset=0` 查詢本人歷史；`limit` 預設 20、範圍 1–100，`offset` 預設 0、不可為負。依 `created_at DESC, id DESC` 排序：

```json
{
  "transactions": [
    {"id":"transaction-id","order_id":"order-id","kind":"redeem","points_delta":-100,"created_at":"2026-11-14T05:30:00.000Z"}
  ],
  "has_more": false
}
```

`order_id` 可為 `null`；`kind` 為 `earn`（累點）、`redeem`（折抵）、`expire`（到期）、`reversal`（沖銷）或 `adjustment`（調整）。點數查詢無有效會員登入回傳 401。

### 會員／訪客下單

`POST /api/orders`：

```json
{
  "table_number":"01",
  "items":[{"menu_item_id":"sunny-plate","quantity":1}],
  "points_redeemed":100
}
```

- `table_number` 為 `01` 至 `12`；`items` 為 1–50 筆，單品合併數量上限 99。`points_redeemed` 選填，預設 0，範圍 0–1,000,000,000。
- 商品名稱、價格、小計及總額由後端查詢菜單計算；無會員時折抵非零回傳 401，無效數量、不可用商品、點數不足或折抵規則不符回傳 422。
- 成功 201 回傳 `order`，包含 `id`、`table_number`、`status`、`payment_status`、`total_amount`、`points_redeemed`、`points_discount_amount`、`payable_amount`、`created_at` 及 `items`；初始狀態分別為 `received`、`unpaid`。

### 後台會員查詢

- `GET /api/admin/members?query=&limit=20&offset=0`：`query` 可用手機或姓名的子字串，最長 80 字元；`limit` 1–100、`offset` 至少 0。回傳 `{"members":[...],"has_more":false}`；各會員包含 `id`、`phone`、`name`、`status`、`created_at`、`available_points`。依註冊時間及 ID 降冪。
- `GET /api/admin/members/{member_id}/transactions?limit=20&offset=0`：回傳 `{"member":{...},"transactions":[...],"has_more":false}`。`member` 包含前述會員欄位以及 `expiring`，歷史交易格式同會員查詢；不存在回傳 404。
- 管理員 session 不存在或無效回傳 401；未設定管理員環境變數回傳 503。列表與歷史均支援 `limit`／`offset` 分頁。
- `PATCH /api/admin/orders/{order_id}` 接受 `status` 和／或 `payment_status`，狀態更新與點數累積／沖銷在同一交易中完成；規則衝突回傳 409。

## 資料表

完整實際定義及索引以 `src/loyalty_schema.py` 為準；ER 圖見 [既有紅利 ERD](./ERD.mmd)。

| 資料表 | 主要欄位及用途 |
| --- | --- |
| `members` | `id`、唯一 `phone`、`password_hash`、可空 `name`、`status`、建立／更新時間。 |
| `member_sessions` | `member_id`、唯一 `token_hash`、`expires_at`、可空 `revoked_at`、建立時間。 |
| `member_login_attempts` | 手機／IP 雜湊鍵及嘗試時間，用於登入限流。 |
| `loyalty_rules` | 累點金額／點數、折抵點數／金額、效期月數及生效時間；交易可引用規則。 |
| `point_transactions` | 會員、可空訂單與規則、異動類型、正負點數、可空原交易、唯一冪等鍵及時間。 |
| `point_lots` | 來源交易、會員、初始與剩餘點數、到期及建立時間；限制剩餘點數介於 0 與初始點數之間。 |
| `point_redemption_allocations` | 折抵交易與批次的分配點數，複合外鍵限制交易、批次和會員一致。 |
| `orders` | 既有訂單新增可空 `member_id`、`points_redeemed`、`points_discount_amount`、可空 `payable_amount`；遷移將舊訂單應付金額回填為原總額。 |

`members` 不保存點數餘額快取；由未到期批次計算。遷移啟動前應備份資料庫，避免舊版程式與新版同時寫入。

## 相關測試

在專案根目錄可執行：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_member_loyalty tests.test_admin_members
```

測試使用獨立暫存資料庫，涵蓋登入、訪客與會員訂單、累點、折抵、到期、沖銷、並發及管理員權限查詢。
