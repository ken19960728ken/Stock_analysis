#%%
import sqlite3
import twstock
import numpy as np
import pandas as pd
import mplfinance as mpf

class StockData:   
    @staticmethod
    def read_stock_info():
        conn = sqlite3.connect(r"C:\Users\ken19\OneDrive\文件\SideProject\Stock_analysis\stock.db")
        sql = "select * from total_code"
        stock_info = pd.read_sql(sql ,conn)
        return stock_info
    
    @staticmethod
    def fetch_data(code):
        name_attribute = [
            'Date', 'Capacity', 'Volume', 'Open', 'High', 'Low', 'Close', 'Change',
            'Transcation'
            ]          
        stock = twstock.Stock(code)
        target_price = stock.fetch_from(2023, 8)
        df = pd.DataFrame(columns=name_attribute, data=target_price)
        df['code'] = code
        df["5_MA"] = StockData.get_MA(list(df["Close"]), 5)
        df["10_MA"] = StockData.get_MA(list(df["Close"]), 10)
        df["20_MA"] = StockData.get_MA(list(df["Close"]), 20)
        df["rate"] = StockData.get_rate(list(df["Close"]), list(df["Change"]))
        df["upper_shadow"] = df["High"] - df["Close"]
        df["lower_shadow"] = df["Open"] - df["Low"]
        df["Candlestick"] = df["Close"] - df["Open"]
        df.index = df["Date"]
        df = df[['Date', 'code', 'Open', 'High', 'Low', 'Close', 
                 'Change', "upper_shadow", "lower_shadow", "Candlestick",  
                 "5_MA", "10_MA", "20_MA", 'rate', 'Transcation', "Volume", 
                 "Capacity"]]
        return df
    
    @staticmethod
    def get_rate(close_data, change_data):
        result = []
        for i in range(len(change_data)):
            if i == 0:
                result.append(np.nan)
            else:
                last_close = close_data[i-1]
                change = change_data[i]
                result.append(round(change/last_close, 2))
        
        return result
    
    @staticmethod
    def get_MA(data, days):
        result = []
        data = data[:]
        for _ in range(len(data)):
            if len(data) < days:
                result.append(np.nan)
            else:
                result.append(round(np.mean(data[-days:]), 2))
            data.pop()
        return result[::-1]
    
    @staticmethod
    def plot(data, title):
        mc = mpf.make_marketcolors(up='r', down='g', inherit=True)
        s  = mpf.make_mpf_style(base_mpf_style='yahoo', marketcolors=mc)
        kwargs = dict(
            type='candle', 
            mav=(5,20,60), 
            volume=True, 
            figratio=(10,8), 
            figscale=0.75, 
            title=title, 
            style=s)
        mpf.plot(data, **kwargs)

# %%
stock_info = StockData.read_stock_info()
listed_stocks = stock_info.loc[stock_info["market"] == "上市"]
semiconductor = listed_stocks.loc[listed_stocks["group"] == "半導體業"]
# %%
data = StockData.fetch_data("2330")
StockData.plot(data, "2330")
data
# %%
def get_train_and_test_data(data):
    data = data.dropna()
    y_close = data["Close"].iloc[1:]
    y_open = data["Open"].iloc[1:]
    features = ["Open", "High", "Low", "Close", "Change", "5_MA", "10_MA", "20_MA", 'rate', "upper_shadow", "lower_shadow", "Candlestick"]
    X = data[features].iloc[:-1]
    return X, y_close, y_open
#%%
def get_stock_datas(stock_data):
    X_data_list = []
    y_open_data_list = []
    y_close_data_list = []
    for code in stock_data["code"]:
        data = StockData.fetch_data(code)
        X, y_close, y_open = get_train_and_test_data(data)
        X_data_list.append(X)
        y_open_data_list.append(y_open)
        y_close_data_list.append(y_close)
    return X_data_list, y_open_data_list, y_close_data_list

X_data_list, y_open_data_list, y_close_data_list = get_stock_datas(semiconductor)
# %%
semiconductor_X = pd.concat(X_data_list, ignore_index=True)
semiconductor_y_open = pd.concat(y_open_data_list, ignore_index=True)
semiconductor_y_close = pd.concat(y_close_data_list, ignore_index=True)
semiconductor_X
#%%
from sklearn.linear_model import LinearRegression
import matplotlib.pyplot as plt
semiconductor_reg = LinearRegression()
semiconductor_reg.fit(semiconductor_X, semiconductor_y_open)
features = ["Open", "High", "Low", "Close", "Change", "5_MA", "10_MA", "20_MA", 'rate', "upper_shadow", "lower_shadow", "Candlestick"]
semiconductor_reg.predict(data[features].iloc[-2:])

# %%
import copy
import tqdm
import torch
import numpy as np
import pandas as pd
import torch.nn as nn
import torch.optim as optim
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split

#%%
# train-test split for model evaluation
X = semiconductor_X.to_numpy()
y_open = semiconductor_y_open.to_numpy()
y_close = semiconductor_y_close.to_numpy()

#%%
# Define the model
class NNRegression:
    def __init__(self, X, y, 
                 n_epochs=100, batch_size=15,
                 loss_fn=nn.MSELoss()):
        
        X_train, X_test, y_train, y_test = train_test_split(X, y, train_size=0.7, shuffle=True)
        self.X_train = self.to_tensor(X_train)
        self.y_train = self.to_tensor(y_train).reshape(-1, 1)
        self.X_test = self.to_tensor(X_test)
        self.y_test = self.to_tensor(y_test).reshape(-1, 1)

        self.model = nn.Sequential(
            nn.Linear(12, 24),
            nn.ReLU(),
            nn.Linear(24, 12),
            nn.ReLU(),
            nn.Linear(12, 1)
        )

        self.n_epochs = n_epochs
        self.batch_size = batch_size

        self.best_mse = np.inf   
        self.best_weights = None

        self.loss_fn = loss_fn
        self.optimizer = optim.Adam(self.model.parameters(), lr=0.0001)
        self.history = []

    def to_tensor(self, data, dtype=torch.float32):
        return torch.tensor(data, dtype=dtype)
    
    def forward_pass(self, X_batch, y_batch):
        y_pred = self.model(X_batch)
        loss = self.loss_fn(y_pred, y_batch)
        return loss

    def backward_pass(self, loss):
        self.optimizer.zero_grad()
        loss.backward()

    def validation(self):
        self.model.eval()
        y_pred = self.model(self.X_test)
        mse = self.loss_fn(y_pred, self.y_test)
        mse = float(mse)
        self.history.append(mse)
        if mse < self.best_mse:
            self.best_mse = mse
            self.best_weights = copy.deepcopy(self.model.state_dict())

    def train(self):
        for epoch in range(self.n_epochs):
            self.model.train()
            batch_start = torch.arange(0, len(self.X_train), self.batch_size)
            with tqdm.tqdm(batch_start, unit="batch", mininterval=0, disable=True) as bar:
                bar.set_description(f"Epoch {epoch}")
                for start in bar:
                    # take a batch
                    X_batch = self.X_train[start:start+self.batch_size]
                    y_batch = self.y_train[start:start+self.batch_size]
                    # forward pass
                    loss = self.forward_pass(X_batch, y_batch)
                    # backward pass
                    self.backward_pass(loss)
                    # update weights
                    self.optimizer.step()
                    # print progress
                    bar.set_postfix(mse=float(loss))
            
            # evaluate accuracy at end of each epoch
            self.validation()
            
    def visual(self):
        self.model.load_state_dict(self.best_weights)
        print("MSE: %.2f" % self.best_mse)
        print("RMSE: %.2f" % np.sqrt(self.best_mse))
        plt.plot(self.history)
        plt.show()

 

# %%
nn_model_open = NNRegression(X, y_open)
nn_model_open.train()
nn_model_open.visual()

# %%
nn_model_close = NNRegression(X, y_close)
nn_model_close.train()
nn_model_close.visual()
# %%
nn_model_open.model(torch.tensor([[945, 964, 943, 964, 22, 951.2, 957.2, 935.45, 2.34, 0, 2, 19]], dtype=torch.float32))
# %%
nn_model_close.model(torch.tensor([[945, 964, 943, 964, 22, 951.2, 957.2, 935.45, 2.34, 0, 2, 19]], dtype=torch.float32))

# %%
torch.save(nn_model_close.model, r'C:\Users\ken19\OneDrive\文件\SideProject\Stock_analysis\models\semiconductor_open_model.pt')
torch.save(nn_model_close.model, r'C:\Users\ken19\OneDrive\文件\SideProject\Stock_analysis\models\semiconductor_open_model.pt')