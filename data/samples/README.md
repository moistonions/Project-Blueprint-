# Synthetic sample data (NOT real)

Every file in this folder is **made up** to exercise the pipeline end to end.
The asset, part numbers, vendor, intervals and notes are fictional and must
not be used as maintenance guidance. Everything loaded from here is tagged
`is_sample=true` and shown with a SAMPLE badge in the app.

- `sample_oem_generator_spec.txt`: fictional OEM schedule for generator `SAMPLE-GEN-01`.
  Stands in for a real manual until Angus's manuals arrive.
- `sample_vendor_contract.txt`: fictional vendor contract with planted gaps.
- `sample_tickets.csv`: fictional vendor checklist tickets (Jan to Oct 2025) with
  meter readings, two planted execution gaps, and notes explaining the vendor's extra work.
- `planted_gaps.json`: the answer key. 10 gaps across all five gap types, plus the
  two "vendor does more" items that should be explained, not flagged.

`python scripts/load_samples.py` runs the real pipeline on these files and
scores the result against the answer key (success = all found, no false alarms).

Once the real manuals are in, the plan is to build the simulated contract and
tickets from the real manuals' task lists in the same way.
