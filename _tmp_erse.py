import openpyxl, sys
wb = openpyxl.load_workbook(r'C:\Users\PEDROM~1.MAR\AppData\Local\Temp\erse_tar.xlsx', data_only=True)
ws = wb.worksheets[1]
for i, row in enumerate(ws.iter_rows(min_row=1, max_row=90), 1):
    vals = [c.value for c in row if c.value is not None]
    if vals:
        print(i, vals)
