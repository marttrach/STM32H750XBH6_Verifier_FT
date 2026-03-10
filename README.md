# Environment

Require Python >= 3.12

```
pip install -r requirement.txt
python ./main.py
```

# UV
```
#大約 每 2~4 週更新一次 就很夠用
uv --version  
>>> 0.9.7 (0adb44480 2025-10-30)

uv self update
```

# 專案程式碼審查與功能總結 (Code Review Summary)

涵蓋 STLink, MySQL, MES, USB, GPIO, ESP32, 設定檔, 及建置打包.exe,進行程式碼審查與各檔案功能敘述。相關的詳細說明文檔（如 API 及連線測試教學）請參考 `./docs/` 資料夾下的 PDF 文件：
- `GoldTek_PIEAPI.pdf`
- `MES與MySQL上傳模組說明.pdf`
- `如何使用 Postman與MES連線測試.pdf`

# 安裝

```
cd GoldTek_Toppan_Fixture_Test_Tool
uv sync
```

# Debug測試

```
uv run main.py
```

# 編譯

```
#這裡用原生 Windows python環境來跑，不使用uv環境，但會尋找當前的 venv(如果先前有跑 uv sync 應該會建立好 當前資料夾的venv), 如果當前 venv 完善好了， 就可以直接執行 ./build.bat 來編譯打包。

./build.bat
```

## 個別檔案功能敘述

### 1. `cmysql.py` (MySQL 資料庫整合)
- **功能描述**：負責與 MySQL 資料庫的連線與資料操作。
- **近期更動與亮點**：
  - 實作了輕量級封裝，提供測試紀錄的插入 (`insert_record`) 與回讀驗證 (`insert_and_verify`)。
  - 包含工廠測試流程所需的連線測試 (`smoke_tests`)，在「省略測試」(Skip Test) 模式下可單獨驗證資料庫連線狀況。

### 2. `com_port.py` (COM Port 管理)
- **功能描述**：提供系統 COM Port 掃描與測試輔助。
- **近期更動與亮點**：
  - 透過 `serial.tools.list_ports` 掃描可用通訊埠並更新至 UI 下拉選單中。
  - 提供背景非同步執行的迴圈測試 (`_perform_loopback`)，可用於驗證 RS232/RS422/RS485 等介面的收發功能。

### 3. `config_store.py` (使用者設定存儲)
- **功能描述**：提供使用者介面狀態與設定的封裝管理。
- **近期更動與亮點**：
  - 定義 `UserConfig` 資料結構儲存 UI 狀態（如主題、選擇的測項、COM port 選項等）。
  - 作為讀取與寫入 `setting.py` 中 AppSettings 的橋樑，確保使用者習慣的設定能被記憶。

### 4. `csv_log.py` (CSV 測試日誌)
- **功能描述**：負責將本地端測試結果匯出保存為 CSV 檔案。
- **近期更動與亮點**：
  - 以時間戳記、員工編號、產品序號 (SN) 為主鍵，將各個測項（Power, STLink, USB, GPIO 等）的測試結果（PASS/FAIL）寫入 `RESULTS_FILE`，並將錯誤詳細訊息附加在備註 (remark) 欄位中。

### 5. `esp32.py` (ESP32 電源控制與監測)
- **功能描述**：負責透過序列埠與附屬的 ESP32 進行通訊，進行治具電源控制及電壓電流監測。
- **近期更動與亮點**：
  - 實作了 `Esp32PowerJob` 與 `Esp32EndJob` 等背景執行緒 (QRunnable)。
  - 解析 ESP32 回傳的文字格式，提取如 `VIN_mV`, `IIN_mA`, `3V3_mV`, `5V_mV` 等數值，並將日誌安全地發送回主 UI 的執行緒。

### 6. `main.py` (主應用程式介面)
- **功能描述**：基於 PySide6 的主應用程式介面，統整所有測試流程。
- **近期更動與亮點**：
  - 實作了響應式 (Responsive) 及縮放 (Scale) 支援的 UI，涵蓋刷機、各項硬體測試、以及結果匯總顯示。
  - 整合多個外部模組，包括工單/員工登入輸入、MES/MySQL 參數設定對話框，以及測試流程控制。
  - 負責排程管理及在各測項完成時更新畫面與計數（Pass/Fail）。

### 7. `MES.py` (MES 系統整合)
- **功能描述**：負責與廠內製造執行系統 (MES) 進行 API 介接。
- **近期更動與亮點**：
  - 實作了 `MesClient` 以處理 HTTP POST 請求，提供取得過站狀態 (`check_sn_status`) 與上傳測試結果 (`upload_result`) 兩大核心功能。
  - 提供 `EmployeeLoginDialog` 作為作業員登入介面，並內建除錯與煙霧測試機制 (`smoke_tests`) 確保服務連線。

### 8. `setting.py` (系統設定與組態)
- **功能描述**：應用程式設定檔管理中心。
- **近期更動與亮點**：
  - 處理 `settings.json` 的加載與保存，支援向下相容舊版的 `user_config.json`。
  - 提供複雜的 `SettingDialog` 供使用者設置站別 (Station)、測試上限/下限參數 (Power Limits)、以及 USB 刷機的進階選項 (支援 MP Firmware, Loader, CB Firmware 等)。

### 9. `stlink.py` (STLink 韌體燒錄)
- **功能描述**：基於 `stm32cubeprog` API 的 STLink 燒錄模組。
- **近期更動與亮點**：
  - 自動尋找系統中的 STM32CubeProgrammer 安裝路徑，並載入對應 DLL/SO 檔案。
  - 在背景執行序進行 STLink 連線、解鎖 (RDP level 設定) 與 bootloader 下載，並加入了逾時保護 (`_run_with_timeout`) 避免卡死。

### 10. `stm32_binary_tool.py` (STM32 硬體與二進制測試)
- **功能描述**：與待測物 (DUT) 上的 STM32 韌體進行二進制或 ASCII 命令通訊的輔助工具。
- **近期更動與亮點**：
  - 透過自訂的二進位協定 (BinaryProtocol) 讀取雷射或暫存器狀態。
  - 實作了具體的硬體測試工作，包含：`GpioTestJob` (GPIO 輸入輸出控制測試)、`LcdTestJob` (讀取暫存器檢查 LCD/Backlight 狀態) 及 `EthernetTestJob` (以網路 Ping 測試狀態)。

### 11. `usb_firmware.py` (USB 韌體與檔案刷寫)
- **功能描述**：包裝底層下載器 (`iot_downloader_ft`) 的介面模組。
- **近期更動與亮點**：
  - 實作 `UsbFirmwareController` 作為主 UI 與下載器之間的橋樑，負責處理各種狀態訊號 (Signal)，如版端資訊、刷機進度及完成狀態。
  - 支援重啟 USB 列舉、傳送 Ctrl+D 進入特定模式，及不同型態檔案的刷機操作 (`start_flash`)。

### 12. `build.bat` (建置與打包)
- **功能描述**：Windows 環境下將 Python 專案構建為執行檔 (`.exe`) 的批次腳本。
- **近期更動與亮點**：
  - 自動生成並進入 Python 虛擬環境，安裝相依套件 (`requirement.txt` 與 `nuitka` 等)。
  - 利用 Nuitka 提供 `--onefile` 編譯指令，將圖示 (`icon`)、二進位資源 (`bin`) 及授權說明 (`LICENSE`) 整合成單一免安裝的執行檔。包含 console 模式的啟動開關以利除錯。
  - 目前用 NUITKA 的打包方式，會把所有需要的檔案打包成一個 exe，不用特別使用 pyarmor 加密。

### 13. `docs/` (文件)
- **功能描述**：存放專案相關文件。
- **近期更動與亮點**：
  - 存放 API 及連線測試教學文件，包含 `GoldTek_PIEAPI.pdf`, `MES與MySQL上傳模組說明.pdf`, `如何使用 Postman與MES連線測試.pdf`。

### 14. `about.md` (關於)
- **功能描述**：存放專案相關資訊。
- **近期更動與亮點**：
  - 存放專案Changlog 顯示。

# reference

- [Nuitka](https://nuitka.net/)
- [PySide6](https://www.qt.io/product/development-tools/pyside)
- [uv](https://github.com/astral-sh/uv)
- [stm32cubeprog](https://github.com/wervin/python-stm32cubeprog)
