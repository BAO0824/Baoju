# Baoju 寶居

> 把家的想像，慢慢變成家的模樣。

Baoju 是給第一次裝潢者使用的空間規劃工具。這個 repository 目前聚焦第一個核心問題：把真實格局圖交給真正的 floor-plan model，轉成可校正、可編輯、保有拓撲關係的 Baoju geometry。

## 目前完成範圍

這是 **v0.6 前置整合版，不是 Baoju v0.6**。

- HTML / CSS / JavaScript 格局辨識工作台
- PNG、JPG、WEBP 上傳與原圖 overlay
- FastAPI `POST /api/recognize`
- 官方 Raster2Seq + CubiCasa5K inference adapter
- Raster2Seq polygon → Baoju node / wall / room / opening graph
- 相鄰房間共用牆節點與 wall entity
- 門窗附著最近 host wall，失敗時留下 issue
- Known-distance calibration，px 幾何轉成 mm
- 牆長編輯會移動共用 node，相連牆同步更新
- `.baoju` JSON 匯入／匯出
- AI 不可用時回傳 503，不使用 threshold detector fallback

尚未完成：

- 在正式 GPU 主機上跑過 Raster2Seq checkpoint inference
- 台灣建商格局圖 accuracy benchmark
- perspective correction / deskew / crop preprocessing
- topology repair 的 T / X junction 與 collinear segment merge
- 穩定的 door/window confidence 與 swing direction
- 3D geometry

因此目前不能宣稱已完成 AI 自動格局辨識，也不能稱為 v0.6。

## 目錄

```text
Baoju/
├── frontend/               # HTML 工作台
├── backend/app/
│   ├── domain/             # canonical Pydantic model
│   ├── providers/          # AI provider adapters
│   └── services/           # geometry reconstruction / calibration
├── shared/                 # Baoju JSON Schema
├── models/                 # AI checkout 與 checkpoints（不進 Git）
├── scripts/
└── tests/
```

## 啟動 API 與 HTML

需要 Python 3.10–3.12。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m uvicorn backend.app.main:app --reload
```

開啟 <http://127.0.0.1:8000>。即使 AI 尚未安裝，HTML、JSON 匯入、renderer 與 API 狀態仍可使用；按鈕會明確顯示 AI 主機未就緒。

## 安裝 Raster2Seq（Linux + NVIDIA GPU）

官方 Raster2Seq 說明的測試環境為 Python 3.10.13、PyTorch 2.3.1、CUDA 11.8，且需要編譯 deformable-attention 與 differentiable rasterization CUDA modules。Baoju 提供固定官方 commit 的安裝腳本：

```bash
chmod +x scripts/setup_raster2seq.sh
./scripts/setup_raster2seq.sh
```

安裝後以腳本最後顯示的環境變數啟動 Baoju。第一次辨識時，官方 `hf:cubicasa5k` alias 會從 `haopt/Raster2Seq` 下載 checkpoint。

可調整的環境變數：

| 變數 | 預設值 | 用途 |
| --- | --- | --- |
| `BAOJU_RASTER2SEQ_ROOT` | `models/Raster2Seq` | 官方 repo 路徑 |
| `BAOJU_RASTER2SEQ_PYTHON` | API 使用的 Python | 已安裝 AI dependencies 的 Python |
| `BAOJU_RASTER2SEQ_CHECKPOINT` | `hf:cubicasa5k` | checkpoint path 或官方 HF alias |
| `BAOJU_RASTER2SEQ_DEVICE` | `cuda` | inference device |
| `BAOJU_RASTER2SEQ_TIMEOUT` | `300` | 單次 inference timeout（秒） |

## 測試

```bash
python -m pytest
```

測試會確認：

- 相鄰房間共用同一面牆
- 門洞能附著到最近牆
- 比例校正完整縮放平面座標
- 模型缺少時 API 回 503，而不是產生假的 geometry

## API

- `GET /api/health`
- `GET /api/providers`
- `POST /api/recognize`
- `POST /api/calibrate`
- `GET /api/schema`
- Swagger：`/docs`

## 資料單位

Raster2Seq 輸出在 256 × 256 模型座標。辨識完成但尚未校正時：

- `calibration.status = required`
- `calibration.coordinateUnit = px`

使用已知距離完成校正後，所有平面座標與 opening width / offset 會轉成 mm：

- `calibration.status = calibrated`
- `calibration.coordinateUnit = mm`

高度與牆厚欄位從一開始即明確使用 mm，避免混淆。

## AI 技術誠實原則

`Raster2SeqProvider` 只會執行官方模型。若 repo、PyTorch、CUDA、編譯 extension 或 checkpoint 不可用，provider 會回報 unavailable，`POST /api/recognize` 會回傳 HTTP 503。Baoju 不會將 threshold、黑線偵測或 sample JSON 當成 AI 成功結果。
