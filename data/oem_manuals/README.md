# Drop real OEM manuals here

Put OEM manuals and maintenance specifications (PDF, TXT, MD or CSV) in this
folder, one subfolder per asset if you like:

```
data/oem_manuals/
  PUMP-P101/
    acme-sp100-operation-maintenance.pdf
```

Then either upload them in the app (**Ingest** page, document type "OEM manual")
or bulk-load the folder with:

```
python scripts/ingest_folder.py data/oem_manuals/PUMP-P101 --kind oem --asset PUMP-P101
```

Notes:
- Text-based PDFs work directly. Scanned (image-only) PDFs need OCR first.
- Manuals are often copyrighted; this folder is git-ignored so they stay local.
