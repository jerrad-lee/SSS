import pandas as pd
from datetime import datetime

df = pd.read_excel('D:/0_Download/flask_dashboard_project/data/FiF Sw Upgrade Plan.xlsx', engine='openpyxl')
df = df.dropna(how='all')
df['Commit Date'] = pd.to_datetime(df['Commit Date'], errors='coerce')

# 기본 필터: 최근 3개월
today = pd.Timestamp.now()
start_date = today - pd.DateOffset(months=3)
print(f'Today: {today}')
print(f'Start Date (3 months ago): {start_date}')

# 최신 10개 SAT의 Commit Date 확인
df_with_jira = df[df['Jira Issue Key'].notna()].copy()
df_with_jira['sat_num'] = df_with_jira['Jira Issue Key'].str.extract(r'SAT-(\d+)').astype(float)
df_sorted = df_with_jira.sort_values('sat_num', ascending=False).head(10)

print('\nTop 10 SAT with Commit Date:')
for _, row in df_sorted.iterrows():
    commit_date = row['Commit Date']
    in_range = commit_date >= start_date if pd.notna(commit_date) else False
    status = 'IN RANGE' if in_range else 'OUT OF RANGE'
    print(f"  {row['Jira Issue Key']} - Commit: {commit_date} - {status}")

# 필터 적용 후 결과
df_filtered = df[df['Commit Date'] >= start_date]
df_review = df_filtered[df_filtered['PUCA Status'] != 'Completed']
df_review_jira = df_review[df_review['Jira Issue Key'].notna()]
print(f'\nAfter date filter: {len(df_review_jira)} review items with Jira')

# 최신 5개 확인
df_review_jira = df_review_jira.copy()
df_review_jira['sat_num'] = df_review_jira['Jira Issue Key'].str.extract(r'SAT-(\d+)').astype(float)
df_review_sorted = df_review_jira.sort_values('sat_num', ascending=False).head(5)
print('\nFiltered Top 5:')
for _, row in df_review_sorted.iterrows():
    print(f"  {row['Jira Issue Key']} - {row['PUCA Status']}")
