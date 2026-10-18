# latest.json (aur offers.json agar ho) ko Hostinger par FTP se upload karta hai.
# Credentials environment variables (GitHub Secrets) se aate hain.
import ftplib, os, sys

host = os.environ["FTP_HOST"]
user = os.environ["FTP_USER"]
password = os.environ["FTP_PASSWORD"]
remote_dir = os.environ.get("FTP_DIR", "public_html/gold")
files = [f for f in ("out/offers.json", "out/market.json", "out/latest.json") if os.path.exists(f)]
if not files:
    sys.exit("Upload ke liye koi file nahi mili.")

def connect():
    try:
        ftp = ftplib.FTP_TLS(host, timeout=60)
        ftp.login(user, password)
        ftp.prot_p()
        return ftp
    except Exception as e:
        print("FTPS fail hua, plain FTP try kar raha hoon:", type(e).__name__)
        ftp = ftplib.FTP(host, timeout=60)
        ftp.login(user, password)
        return ftp

ftp = connect()
for part in [p for p in remote_dir.split("/") if p and p != "."]:
    try:
        ftp.cwd(part)
    except ftplib.error_perm:
        ftp.mkd(part)
        ftp.cwd(part)
for path in files:
    name = os.path.basename(path)
    with open(path, "rb") as f:
        ftp.storbinary("STOR " + name + ".tmp", f)
    try:
        ftp.delete(name)
    except ftplib.error_perm:
        pass
    ftp.rename(name + ".tmp", name)
    print("Uploaded", name)
ftp.quit()
