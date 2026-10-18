# Disclaimer

SFTP Pilot uploads, overwrites and deletes files on remote servers, and
its scheduler does so unattended, repeatedly, at times you choose in advance.
A wrong path or a wrong server can destroy data.

- The software is provided **AS IS**, without warranty of any kind, express or
  implied, including fitness for a particular purpose.
- You use it **entirely at your own risk**. The author accepts no liability for
  data loss or corruption, overwritten or deleted files, hardware damage,
  unbootable or unreachable systems, business interruption, or any direct,
  indirect or consequential damages.
- **You are responsible** for checking every source and destination path and
  every target server before running or scheduling a task, for keeping tested
  backups of anything it can touch, and for being authorised to change the
  servers you connect to.
- It is **not certified** for regulated, forensic, safety-critical or other
  high-assurance use.
- Host key checking defaults to `accept_new`, which trusts a server the first
  time it is seen. Verify the fingerprint of a new server through another
  channel if that first connection matters.

- The Windows program is built from the same source with PyInstaller and is
  **not code-signed**. Verify the SHA256 on the release page before running it,
  and expect some antivirus products to be suspicious of it.

This file is a plain-language summary. The [MIT License](LICENSE) is the
governing text and prevails wherever the two differ.

SFTP Pilot is not affiliated with or endorsed by WinSCP or any other file
transfer product; it talks SFTP directly through
[paramiko](https://www.paramiko.org/).
