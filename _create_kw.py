import os
path = r'D:\小光工作区\projects\stock-classroom\frontend\kline_widget.py'

# Only write if file doesn't exist (to avoid overwriting)
if not os.path.exists(path):
    print(f'File does not exist, will create: {path}')
else:
    print(f'File exists, size: {os.path.getsize(path)}')