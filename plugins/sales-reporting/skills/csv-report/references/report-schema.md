# Report contract

Input columns, in order: date, product, quantity, unit_price.
quantity and unit_price are nonnegative integers in this training dataset.
Revenue for each row is quantity multiplied by unit_price.

summary.json contains row_count, total_quantity, total_revenue and by_product,
where by_product maps product names to integer revenue. report.md starts with
`# 매출 분석 보고서` and contains the same metrics. skill_evidence.json records
the script revision and SHA-256 of the actual input bytes; it is execution
evidence for this exercise, not an enterprise audit log.
