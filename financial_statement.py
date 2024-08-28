# -*- coding: utf-8 -*-
"""
Spyder Editor

This is a temporary script file.
"""

import numpy as np 
import pandas as pd
import requests 
from bs4 import BeautifulSoup

'''
公開資訊觀測站: https://mops.twse.com.tw/mops/web/index
'''

TYPEK = {
    '上市': 'sii',
    '上櫃': 'otc',
    '興櫃': 'rotc',
    '公開發行': 'pub'}

financial_statement_elements ={
    '綜合損益表': 'ajax_t163sb04',
    '資產負債表': 'ajax_t163sb05',
    '現金流量表': 'ajax_t163sb20'
    }

def get_Data(elements, typek):
    url = f'http://mops.twse.com.tw/mops/web/{financial_statement_elements[elements]}'
    form_data = {
        'encodeURIComponent':1,
        'step':1,
        'firstin':1,
        'off':1,
        'TYPEK': TYPEK[typek],
        'year': 111,
        'season': 4,
    }
    res = requests.post(url, form_data)
    soup = BeautifulSoup(res.text, 'html5lib')
    return soup


tables = [i for i in soup.find_all('table')]
def get_table(table):
    table_element = [i.getText() for i in table.find_all('td')]
    table_columns = [i.getText() for i in table.find_all('th')]
    a = np.array(table_element)
    n_columns = len(table_columns)
    n_row = len(table_element)//n_columns
    a = a.reshape(n_row,n_columns)
    df = pd.DataFrame(a, columns=table_columns)
    return df


#%%
get_table(tables[6])



# %%
