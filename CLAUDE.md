# Mr.du：可以捏的臉

單頁網站：一行大標題，加一張可以抓著拉的臉，眼球會跟著游標。
上線網址 https://alanchiangg.github.io/Mr.du/ ，由 GitHub Pages 從 `main` 分支的根目錄直接發佈，沒有建置步驟。

和使用者用繁體中文溝通。

## 檔案

| 路徑 | 內容 |
|---|---|
| `index.html`、`assets/css/style.css` | 版面。字型 Kanit Black 放在 `assets/fonts`，頁面不向外部請求任何東西 |
| `assets/js/portrait.js` | 引擎（WebGL），沒有相依套件 |
| `assets/face/*.webp`、`assets/js/face-data.js`、`assets/icon-*.png` | 由 `tools/build_faces.py` 產生，不要手改 |
| `tools/src/joy.png`、`tools/src/shocked.png` | 兩張來源表情圖：平常的臉、被捏時的反應 |
| `tools/measure.py` | 量測來源圖，寫出 `tools/geometry.json` |
| `tools/build_faces.py`、`tools/facekit.py` | 去背、對齊、合成所有眼睛狀態，輸出素材 |
| `tools/check_page.js`、`tools/check_behaviour.js`、`tools/record_preview.js` | 用無頭瀏覽器實測、錄預覽動畫 |

## 臉是怎麼動的

- **皮膚**：72×72 網格上的阻尼波動方程，固定 1/240 秒步進。每一幀做一次「解纏」，把每列每行的節點排回順序，網格才不會翻折。這段取自 motionsites.ai 上一段公開分享的 Living Portrait prompt。
- **表情**：只有兩張整圖。`joy` 是平常，`shock` 在被拉、被點、被鬼手拉時顯示。切換是最多 70ms 的淡入淡出。
- **眼睛**：`eyes.webp` 是一張補丁表，一格一個狀態，alpha 是遮罩。shader 用同一組座標把補丁疊在整圖上，所以補丁會跟著皮膚一起變形，不會錯位。
  - `joy_l1..l4`、`joy_r1..r4`：黑眼珠左右各四段。`joy_half`、`joy_closed`：眨眼、睡著。
  - `s_XY`：Shocked 的視線，X 是 0..4 由左到右，Y 是 0..2 由上到下，`s_21` 是正視。
- **為什麼不是每個狀態一張整圖**：26 張整圖各自做有損壓縮後，眼睛以外的皮膚在切換時會閃。現在所有狀態共用同一張整圖，只有眼睛那一小塊會變。

## 兩種眼睛，兩種做法

- **瞇著的眼睛**（joy）：看得到的只有黑眼珠中間一條。做法是在眼縫裡把內容橫向滑動，眼白一邊拉長、一邊壓短。上下移動看不出來，所以只做左右。眨眼是把上眼皮往下拉到下眼皮，睫毛線整條平移，上方的皮膚拉伸。
- **睜大的眼睛**（shocked）：整顆黑眼珠都看得到。做法是先把眼白補成一顆「空眼球」，把黑眼珠切成獨立的圓片，移到新位置後用上下眼皮的平滑曲線裁切。

`build_faces.py` 目前假設「平常那張是瞇眼、反應那張是睜眼」。如果新的人平常那張是睜眼，要把睜眼的做法也用在平常那張上，而且睜眼的眨眼還沒做。

## 做一張新的臉

每個人用自己的 repo。把這個 repo 的 `index.html`、`assets/css`、`assets/js/portrait.js`、`assets/fonts`、`tools/` 複製過去再改。

1. **圖**：把兩張表情圖放進 `tools/src/joy.png`、`tools/src/shocked.png`。如果使用者給的是多格拼圖，先裁出各格；格線可以用整行、整列相鄰像素的差值找出來。
2. **環境**：

   ```bash
   python3 -m venv --system-site-packages .venv
   .venv/bin/pip install opencv-python-headless scipy mediapipe
   apt-get update && apt-get install -y --no-install-recommends libegl1 libgles2
   ```

3. **量測**：`.venv/bin/python tools/measure.py --debug 檢查圖資料夾`。一定要看檢查圖：圓圈要貼著黑眼珠，`overlay.png` 裡兩張臉的頭髮和耳朵要重合。圓圈偏了就直接改 `tools/geometry.json`，裡面的數字都是畫布像素。
4. **產生素材**：`.venv/bin/python tools/build_faces.py --debug 檢查圖資料夾`，看每個眼睛狀態的放大圖。
5. **文字**：改 `index.html` 的標題、`<title>`、說明、圖片替代文字，以及 `README.md` 的網址。標題字數變了要重算 `style.css` 的 `--fs`：「HI, I’M MR.DU」的自然寬度約 5.77em，取 16.4vw 時約佔畫面寬度的 95%。
6. **實測**：`node tools/check_page.js 截圖資料夾 1440 900`，再跑 `390 844`；`node tools/check_behaviour.js 截圖資料夾`。兩者都要印出 `no console errors`，並且要實際看截圖。
7. **上線**：推到 `main`，請使用者到 repo 的 Settings → Pages 選「Deploy from a branch」、`main`、`/ (root)`。

## 來源圖的條件

- 兩張是同一個人、同一次產出，最好來自同一張拼圖，臉才會一致。
- 正面、整顆頭入鏡、素色淺背景。背景靠顏色去背，背景越單純越乾淨。
- 解析度越高越好。這次每張臉只有約 666px，放大後偏軟。
- 圖下方如果有文字標籤沒關係，肩膀的淡出會把它裁掉。
- 這個環境不能產圖，表情圖要使用者自己用 Gemini 之類的工具產生。
- 臉會公開放在網路上，做別人的臉之前要先確認本人同意。

## 踩過的坑

- **頭髮白邊**：淺背景上的頭髮邊緣有亮絲，放到深色頁面會變成白邊。`facekit.matte` 會把貼著背景的亮絲併入背景，並把輪廓上殘留的亮點塗成旁邊的髮色。
- **對齊**：兩張表情用頭髮和耳朵的輪廓對齊，只比鼻子以上。用五官的定位點對齊，誤差有十幾個像素，切換時整顆頭會跳。
- **睜眼的眼皮邊緣**：用顏色判斷眼球範圍會多吃到下眼瞼和睫毛線，黑眼珠移動後會蓋到眼皮上。所以改用擬合出來的平滑曲線裁切。
- **眨眼的眼尾**：眼尾外側那段粗睫毛線要跟著變細，否則閉眼時會在開口結束的地方出現一個台階。
- **一開頁面就醒來**：瀏覽器在頁面出現時會立刻回報靜止的游標位置。引擎刻意讓他先睡 1.5 秒（`NAP`）再醒。
- **測試時間相關的行為**：無頭瀏覽器截一張圖約一秒，實際時間會跑掉。`record_preview.js` 用手動時鐘一幀一幀推進，才錄得到平順的畫面。
- **WebGL**：無頭 Chromium 要加 `--use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader --ignore-gpu-blocklist`。

## 這個雲端環境做不到的事

- 建立新的 repo。請使用者開 `https://github.com/new?name=名稱&visibility=public` 自己建，再把它加進 session。
- 開啟 GitHub Pages，Pages 的 API 路徑被擋。部署結果可以用 `gh api "repos/擁有者/名稱/deployments?per_page=1"` 和它的 `statuses` 查。
- 打開 github.io 的網址。上線後的實際畫面要請使用者自己看。
