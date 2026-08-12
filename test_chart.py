"""
test_chart.py — Verify chart generation and safe_exec plot capture
"""
import sys
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dataiq.executor import safe_exec

df = pd.read_csv("sample_data.csv")

code = """
import matplotlib.pyplot as plt
plt.figure(figsize=(8, 4))
df.groupby('category')['revenue'].sum().plot(kind='bar', color='skyblue')
plt.title('Revenue by Category')
plt.ylabel('Revenue ($)')
plt.tight_layout()
result = "Chart generated successfully"
"""

res = safe_exec(code, df)

print(f"Execution OK: {res.ok}")
print(f"Result: {res.result}")
print(f"Base64 Plot Length: {len(res.plot_base64)}")
if res.plot_base64:
    print(f"Base64 Plot Prefix: data:image/png;base64,{res.plot_base64[:30]}...")
