Mock Salesforce-style commit/consumption dataset

This version reflects the latest requested changes:
- Removed commitments.csv
- quote_line_items.csv now removes quantity, list_price, and net_price
- quote_line_items.csv shows discount_percent only
- quotes.csv annual_commit values are rounded to realistic 50,000 increments with minimum 100,000
- accounts.csv current_arr values are rounded to realistic 50,000 increments with minimum 100,000
- accounts.csv renewal_date values land on the last day of the month
- products.csv contains only the cleaned SKU lists
