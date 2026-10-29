# Vendor contracts, schedules and field documents

Put vendor service contracts / maintenance schedules (`--kind vendor`) and
field material such as service logs, work orders and exported emails
(`--kind field`) here. Vendor documents need a vendor name:

```
python scripts/ingest_folder.py data/vendor_docs/acme --kind vendor --asset PUMP-P101 --vendor "Acme Services"
python scripts/ingest_folder.py data/vendor_docs/acme/logs --kind field --asset PUMP-P101 --vendor "Acme Services"
```

This folder is git-ignored apart from this README.
