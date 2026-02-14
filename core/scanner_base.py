import abc

from tqdm import tqdm

from core.db import check_exists, dispose_engine


class BaseScanner(abc.ABC):
    """Scanner 基底類別：主迴圈、進度條、Ctrl+C、斷點續傳"""

    name = "BaseScanner"
    # 子類別設定此值以啟用斷點續傳（檢查的 DB table 名稱）
    resume_table = None

    def scan(self):
        targets = self.get_targets()
        if not targets:
            print("⚠️ 無目標可執行，請檢查資料庫。")
            return

        print(f"🚀 [{self.name}] 開始掃描，共 {len(targets)} 檔...")
        print("💡 隨時按 Ctrl+C 可安全中斷")

        pbar = tqdm(targets)
        success_count = 0
        skip_count = 0
        fail_count = 0

        try:
            for target in pbar:
                stock_id = self._get_stock_id(target)
                pbar.set_description(f"{self.name} {stock_id}")

                # 斷點續傳
                if self.resume_table and check_exists(self.resume_table, stock_id):
                    skip_count += 1
                    continue

                try:
                    ok = self.fetch_one(target)
                    if ok:
                        success_count += 1
                    else:
                        fail_count += 1
                except Exception as e:
                    print(f"\n⚠️ [{stock_id}] 失敗: {e}")
                    fail_count += 1

        except KeyboardInterrupt:
            pbar.close()
            print("\n\n🛑 收到中斷指令，正在安全退出...")

        finally:
            dispose_engine()
            print("\n==========================================")
            print(f"📊 [{self.name}] 任務結算")
            print("==========================================")
            print(f"📥 成功: {success_count} 檔")
            print(f"⏭️ 跳過: {skip_count} 檔")
            print(f"❌ 失敗: {fail_count} 檔")
            print("✅ 系統已安全著陸。")

    @abc.abstractmethod
    def fetch_one(self, target):
        """
        處理單支股票，返回 True/False 表示成功與否。
        target 可以是 stock_id 字串或 dict。
        """
        ...

    def get_targets(self):
        """子類別可覆寫以自訂目標清單，預設返回 stock_id 字串清單"""
        from core.stock_list import get_stock_ids_from_daily_price
        return get_stock_ids_from_daily_price()

    def _get_stock_id(self, target):
        """從 target 中提取 stock_id"""
        if isinstance(target, dict):
            return target.get("stock_id", str(target))
        return str(target)
