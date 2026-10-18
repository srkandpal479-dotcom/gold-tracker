# Gold tracker (GitHub Actions)

Is repo mein SIRF code rehta hai. Koi password, key ya token yahan commit nahi hota.

## Setup
1. Ye saari files repo ke root mein rakho (yeh folder structure waisa hi rakho).
2. Amazon SDK ka folder `creatorsapi_python_sdk` bhi repo ke root mein copy karo, saath mein SDK ki LICENSE aur NOTICE files.
3. SDK ki `requirements.txt` ka content is repo ki `requirements.txt` mein paste karo.
4. Settings -> Secrets and variables -> Actions -> New repository secret mein ye daalo:
   - AMAZON_CREDENTIAL_ID, AMAZON_CREDENTIAL_SECRET, AMAZON_CREDENTIAL_VERSION (3.2), AMAZON_PARTNER_TAG
   - FTP_HOST, FTP_USER, FTP_PASSWORD, FTP_DIR (jaise public_html/gold)
   - PRODUCTS_CSV (optional: poori products.csv ka text; ye daaloge to repo wali products.csv ignore hogi)
5. Actions tab -> "Gold tracker" -> Run workflow se pehla test chalao.
