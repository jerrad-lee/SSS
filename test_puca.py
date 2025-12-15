import pandas as pd
import sys
sys.stdout.reconfigure(encoding='utf-8')

df = pd.read_excel(r'C:\FlaskDashboard\data\FiF Sw Upgrade Plan.xlsx', engine='openpyxl')
df = df.dropna(how='all')
print(f'Total rows: {len(df)}')

df_review = df[df['PUCA Status'] != 'Completed']
df_with_jira = df_review[df_review['Jira Issue Key'].notna()].copy()
print(f'Review items: {len(df_with_jira)}')

df_with_jira['sat_num'] = df_with_jira['Jira Issue Key'].str.extract(r'SAT-(\d+)').astype(float)
df_sorted = df_with_jira.sort_values('sat_num', ascending=False).head(10)
print('Top 10 SAT:')
for _, row in df_sorted.iterrows():
    print(f"  {row['Jira Issue Key']} - {row['PUCA Status']}")
