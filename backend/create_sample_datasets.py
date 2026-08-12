import os
import pandas as pd
import numpy as np

os.makedirs("sample_datasets", exist_ok=True)

# Set random seed for reproducibility
np.random.seed(42)

# 1. Sales Performance (CSV)
sales_data = {
    "Order_ID": [f"ORD-{1001+i}" for i in range(25)],
    "Date": pd.date_range("2024-01-01", periods=25, freq="D").strftime("%Y-%m-%d"),
    "Region": np.random.choice(["North", "South", "East", "West"], 25),
    "Category": np.random.choice(["Electronics", "Furniture", "Office Supplies"], 25),
    "Product": np.random.choice(["Laptop Pro", "Ergonomic Chair", "Wireless Mouse", "4K Monitor", "Desk Lamp"], 25),
    "Units_Sold": np.random.randint(1, 15, 25),
    "Unit_Price": np.random.choice([25.0, 85.0, 250.0, 450.0, 1200.0], 25),
    "Sales_Status": np.random.choice(["Completed", "Pending", "Shipped"], 25, p=[0.7, 0.1, 0.2])
}
df_sales = pd.DataFrame(sales_data)
df_sales["Total_Revenue"] = df_sales["Units_Sold"] * df_sales["Unit_Price"]
df_sales.to_csv("sample_datasets/01_sales_performance.csv", index=False)

# 2. Employee Payroll (CSV)
hr_data = {
    "Emp_ID": [f"EMP-{500+i}" for i in range(20)],
    "Full_Name": ["Alice Smith", "Bob Jones", "Charlie Brown", "Diana Prince", "Evan Wright",
                  "Fiona Gallagher", "George Clark", "Hannah Abbott", "Ian Malcolm", "Julia Roberts",
                  "Kevin Bacon", "Laura Croft", "Michael Scott", "Nina Williams", "Oscar Martinez",
                  "Pam Beesly", "Quentin Tarantino", "Rachel Green", "Steve Rogers", "Tony Stark"],
    "Department": np.random.choice(["Engineering", "Sales", "Marketing", "HR", "Finance"], 20),
    "Job_Title": np.random.choice(["Software Engineer", "Account Exec", "Marketing Specialist", "HR Generalist", "Financial Analyst"], 20),
    "Salary_USD": np.random.choice([65000, 75000, 92000, 110000, 145000, 180000], 20),
    "Bonus_Pct": np.random.choice([0.05, 0.10, 0.12, 0.15, 0.20], 20),
    "Performance_Score": np.random.choice([3, 4, 5], 20, p=[0.2, 0.5, 0.3]),
    "Remote": np.random.choice(["Yes", "No"], 20)
}
df_hr = pd.DataFrame(hr_data)
df_hr.to_csv("sample_datasets/02_employee_payroll.csv", index=False)

# 3. E-Commerce Orders (CSV)
ecom_data = {
    "Order_No": [f"EC-{8000+i}" for i in range(20)],
    "Customer_Country": np.random.choice(["USA", "Canada", "UK", "Germany", "Australia", "Japan"], 20),
    "Payment_Method": np.random.choice(["Credit Card", "PayPal", "Apple Pay", "Crypto"], 20),
    "Items_Count": np.random.randint(1, 8, 20),
    "Subtotal_USD": np.round(np.random.uniform(19.99, 599.99, 20), 2),
    "Shipping_Fee": np.random.choice([0.0, 4.99, 9.99, 14.99], 20),
    "Fulfillment": np.random.choice(["Delivered", "In Transit", "Processing", "Cancelled"], 20, p=[0.6, 0.2, 0.1, 0.1])
}
df_ecom = pd.DataFrame(ecom_data)
df_ecom.to_csv("sample_datasets/03_ecommerce_orders.csv", index=False)

# 4. Financial Transactions (CSV)
fin_data = {
    "TX_ID": [f"TXN-{10000+i}" for i in range(20)],
    "Timestamp": pd.date_range("2024-02-01 08:00", periods=20, freq="h").strftime("%Y-%m-%d %H:%M"),
    "Account_Type": np.random.choice(["Checking", "Savings", "Investment", "Corporate"], 20),
    "Category": np.random.choice(["Payroll", "Vendor Payment", "Subscription", "Wire Transfer", "Refund"], 20),
    "Amount_USD": np.round(np.random.uniform(-5000.0, 15000.0, 20), 2),
    "Risk_Rating": np.random.choice(["Low", "Medium", "High"], 20, p=[0.7, 0.2, 0.1])
}
df_fin = pd.DataFrame(fin_data)
df_fin.to_csv("sample_datasets/04_financial_transactions.csv", index=False)

# 5. Customer Churn Analytics (CSV)
churn_data = {
    "Customer_ID": [f"CUST-{300+i}" for i in range(20)],
    "Subscription_Plan": np.random.choice(["Basic", "Pro", "Enterprise"], 20),
    "Tenure_Months": np.random.randint(1, 48, 20),
    "Monthly_Fee_USD": np.random.choice([29.0, 79.0, 299.0], 20),
    "Support_Tickets": np.random.randint(0, 10, 20),
    "Contract_Type": np.random.choice(["Month-to-Month", "One Year", "Two Year"], 20),
    "Churned": np.random.choice(["Yes", "No"], 20, p=[0.3, 0.7])
}
df_churn = pd.DataFrame(churn_data)
df_churn.to_csv("sample_datasets/05_customer_churn_analytics.csv", index=False)

# 6. Real Estate Listings (Excel XLSX)
re_data = {
    "Property_ID": [f"PROP-{700+i}" for i in range(20)],
    "City": np.random.choice(["Austin", "Seattle", "Denver", "Miami", "Boston", "Chicago"], 20),
    "Property_Type": np.random.choice(["Single Family", "Condo", "Townhouse", "Multi-Family"], 20),
    "Bedrooms": np.random.randint(1, 6, 20),
    "Bathrooms": np.random.choice([1.0, 1.5, 2.0, 2.5, 3.0, 4.0], 20),
    "Square_Feet": np.random.randint(750, 4500, 20),
    "Year_Built": np.random.randint(1985, 2023, 20),
    "Price_USD": np.random.randint(250000, 1850000, 20)
}
df_re = pd.DataFrame(re_data)
df_re.to_excel("sample_datasets/06_real_estate_listings.xlsx", index=False)

# 7. Marketing Campaigns ROI (Excel XLSX)
mkt_data = {
    "Campaign_ID": [f"CMP-{400+i}" for i in range(20)],
    "Channel": np.random.choice(["Google Ads", "Meta Ads", "LinkedIn", "Email Newsletter", "SEO Organic"], 20),
    "Budget_USD": np.random.choice([1000, 2500, 5000, 10000, 25000], 20),
    "Impressions": np.random.randint(10000, 500000, 20),
    "Clicks": np.random.randint(500, 25000, 20),
    "Conversions": np.random.randint(20, 1200, 20),
    "Revenue_Generated": np.random.randint(2000, 75000, 20)
}
df_mkt = pd.DataFrame(mkt_data)
df_mkt["CTR_Pct"] = np.round((df_mkt["Clicks"] / df_mkt["Impressions"]) * 100, 2)
df_mkt.to_excel("sample_datasets/07_marketing_campaigns.xlsx", index=False)

# 8. Student Academic Performance (Excel XLSX)
edu_data = {
    "Student_ID": [f"STU-{100+i}" for i in range(20)],
    "Grade_Level": np.random.choice(["Freshman", "Sophomore", "Junior", "Senior"], 20),
    "Math_Score": np.random.randint(55, 100, 20),
    "Science_Score": np.random.randint(50, 100, 20),
    "English_Score": np.random.randint(60, 100, 20),
    "Attendance_Pct": np.round(np.random.uniform(80.0, 100.0, 20), 1),
    "Study_Hours_Per_Week": np.random.randint(5, 30, 20)
}
df_edu = pd.DataFrame(edu_data)
df_edu["GPA"] = np.round((df_edu["Math_Score"] + df_edu["Science_Score"] + df_edu["English_Score"]) / 75.0, 2)
df_edu.to_excel("sample_datasets/08_student_academic_performance.xlsx", index=False)

# 9. Inventory Warehouse Stock (Excel XLSX)
inv_data = {
    "SKU": [f"SKU-88{i:02d}" for i in range(20)],
    "Item_Name": [f"Industrial Tool #{i+1}" for i in range(20)],
    "Category": np.random.choice(["Power Tools", "Hand Tools", "Safety Gear", "Fasteners", "Hardware"], 20),
    "Warehouse_Zone": np.random.choice(["Zone A", "Zone B", "Zone C", "Zone D"], 20),
    "Stock_Qty": np.random.randint(0, 500, 20),
    "Reorder_Threshold": np.random.choice([25, 50, 100], 20),
    "Unit_Cost_USD": np.round(np.random.uniform(5.50, 180.00, 20), 2)
}
df_inv = pd.DataFrame(inv_data)
df_inv.to_excel("sample_datasets/09_inventory_warehouse_stock.xlsx", index=False)

# 10. Healthcare Patient Records (Excel XLSX)
health_data = {
    "Patient_ID": [f"PAT-90{i:02d}" for i in range(20)],
    "Age": np.random.randint(18, 85, 20),
    "Gender": np.random.choice(["Male", "Female"], 20),
    "Blood_Type": np.random.choice(["A+", "A-", "B+", "B-", "O+", "O-", "AB+"], 20),
    "Diagnosis": np.random.choice(["Hypertension", "Diabetes Type 2", "Asthma", "Arrhythmia", "Orthopedic Surgery"], 20),
    "Hospital_Stay_Days": np.random.randint(1, 14, 20),
    "Billing_Amount_USD": np.round(np.random.uniform(1200.0, 28000.0, 20), 2)
}
df_health = pd.DataFrame(health_data)
df_health.to_excel("sample_datasets/10_healthcare_patient_records.xlsx", index=False)

print("Created all 10 sample datasets in sample_datasets/ directory!")
