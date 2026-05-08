import csv

with open('output/textiles_india_detailed_20260508.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    print(f"{'Company Name':<40} | {'Website':<35} | {'Emails':<40} | {'Phone':<20}")
    print('-' * 140)
    for row in reader:
        name = row.get('company_name', '')[:38]
        website = row.get('website', '')[:33]
        emails = row.get('direct_emails', '')[:38]
        phone = row.get('phone_numbers', '')[:18]
        print(f"{name:<40} | {website:<35} | {emails:<40} | {phone:<20}")
