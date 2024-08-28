import sqlite3
import twstock
import pandas as pd

class StockInfo:
    @property
    def stock_infos(self) -> dict:
        return twstock.codes 
    
    def get_etch_stock(self, stock_number):
        stock_info = self.stock_infos[stock_number]
        stock_info_dict = {
            "name": stock_info.name,
            "code": stock_info.code,
            "type": stock_info.type,
            "CFI": stock_info.CFI,
            "ISIN": stock_info.ISIN, 
            "start": stock_info.start, 
            "market": stock_info.market, 
            "group": stock_info.group, 
        }
        return stock_info_dict
    
    def parse_table(self):
        code_list = list(self.stock_infos.keys())
        info_list = list(map(lambda code: self.get_etch_stock(code), code_list))
        return pd.DataFrame(info_list)


if __name__ == "__main__":
    stock = StockInfo()
    stock_table = stock.parse_table()
    conn = sqlite3.connect(r"C:\Users\ken19\OneDrive\文件\SideProject\Stock_analysis\stock.db")
    stock_table.to_sql(name="total_code", if_exists="replace", index=False, con=conn)
