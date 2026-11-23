# Deploying ResearchFlow on your own server (Oracle Cloud Always Free or any Ubuntu VPS)

This is the option for a full server: more disk space, automatic deploys on every push and nightly backups. Oracle Cloud asks for a credit or debit card to verify your identity. If you have no card, use the PythonAnywhere guide in [DEPLOYMENT.md](DEPLOYMENT.md) instead.

The result: your team opens `https://yourteam.duckdns.org`, the app never sleeps, and every `git push` to `main` that passes the tests goes live automatically.

```
Your PC ──git push──► GitHub ──CI passes──► Deploy workflow ──SSH──► Free Oracle Cloud server
                                                                     ├─ Caddy: HTTPS, serves the web app
                                                                     ├─ ResearchFlow API (always running)
                                                                     └─ /var/lib/researchflow: database + uploads (nightly backup)
```

## Why this setup

ResearchFlow needs a computer that stays on and a disk that keeps the database and uploaded files. GitHub cannot run it by itself: GitHub Pages only hosts static pages, and Codespaces shut down when idle. Free app-hosting tiers have changed a lot. Here is where they stood in late 2026:

| Option | Free? | Sleeps? | Keeps your files? |
| --- | --- | --- | --- |
| **Oracle Cloud Always Free VM** (used here) | Yes | No | Yes (up to 200 GB) |
| Google Cloud e2-micro | Yes, but traffic over 1 GB/month is billed | No | Yes (30 GB) |
| Render free web service | Yes | After 15 minutes idle | No: files are wiped on restart |
| Koyeb free instance | Yes | Scales to zero when idle | No volumes on free |

So GitHub holds the code and runs the tests and deployment, and the app runs on an Oracle Always Free server. Oracle asks for a credit or debit card to verify your identity, and Always Free resources are not charged.

**One catch:** Oracle may stop Always Free servers that look idle for a week. Avoid it by upgrading the account to **Pay As You Go** (step 1.4). Always Free resources stay free after the upgrade, and a budget alert warns you if anything ever costs money.

Total time: about 45 minutes the first time.

---

## Step 1: Create the free server (Oracle Cloud)

1. Sign up at **oracle.com/cloud/free**. Pick your **home region** carefully, because Always Free servers can only be created there. Choose one close to your team and avoid the busiest ones, such as Ashburn and Frankfurt, where free capacity often runs out.
2. Open **Compute › Instances › Create instance**:
   - **Image:** Canonical Ubuntu **24.04**.
   - **Shape:** Ampere `VM.Standard.A1.Flex`, 1 OCPU and 6 GB memory (marked *Always Free eligible*). If it says *out of capacity*, try another availability domain, or choose AMD `VM.Standard.E2.1.Micro`, which is also free. The app runs on either, because the web app is built on GitHub, not on the server.
   - **Networking:** keep "Create new virtual cloud network" and "Assign a public IPv4 address".
   - **SSH keys:** click **Save private key** and keep the file (for example `C:\Users\you\oracle.key`).
   - Create the instance. Copy its **Public IP address**.
3. **Open the web ports.** On the instance page, open the **Subnet**, then its **Security List**, then **Add Ingress Rules** twice:
   - Source CIDR `0.0.0.0/0`, protocol TCP, destination port `80`.
   - Source CIDR `0.0.0.0/0`, protocol TCP, destination port `443`.
4. **Prevent idle shutdown:** go to **Billing › Upgrade and Manage Payment** and upgrade to Pay As You Go. Then add a budget under **Billing › Budgets** (for example $1) with an email alert.

## Step 2: Get a free domain name (DuckDNS)

HTTPS needs a name, not just an IP address.

1. Go to **duckdns.org** and sign in with GitHub.
2. Add a subdomain, for example `yourteam`, which gives you `yourteam.duckdns.org`.
3. Put the server's **public IP** in the *current ip* box and click **update ip**.

## Step 3: Put the code on GitHub

1. On github.com, create a **new private repository** named `researchflow` with no README, .gitignore or license.
2. In PowerShell on your PC:

```powershell
cd path\to\researchflow
git init -b main
git add .
git status
```

Check the list: it must **not** contain `backend/.env`, `*.sqlite3`, `private_uploads`, `node_modules` or `.venv`. They are git-ignored, so normally they won't appear. Then:

```powershell
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR-USERNAME/researchflow.git
git push -u origin main
```

GitHub runs the tests in the **Actions** tab. The *Deploy* workflow is skipped for now; it starts working after step 5.

## Step 4: Prepare the server (one command)

1. Create the key GitHub will use to deploy. In PowerShell, press Enter twice when asked for a passphrase:

```powershell
ssh-keygen -t ed25519 -C github-actions-deploy -f "$HOME\researchflow_deploy"
Get-Content "$HOME\researchflow_deploy.pub"
```

Copy the printed line, which starts with `ssh-ed25519`.

2. Copy the setup script to the server and log in. `ubuntu` is the default user on Oracle's Ubuntu images:

```powershell
scp -i C:\Users\you\oracle.key deploy\server_setup.sh ubuntu@SERVER_IP:~
ssh -i C:\Users\you\oracle.key ubuntu@SERVER_IP
```

3. On the server, run the script with your domain and the public key line, in quotes:

```bash
sudo bash server_setup.sh yourteam.duckdns.org "ssh-ed25519 AAAA...your-key... github-actions-deploy"
```

The script installs Python and Caddy and opens ports 80 and 443 in the server firewall. It creates a locked-down `deploy` account for GitHub, generates the production settings with fresh secrets, installs the always-on API service with HTTPS, and schedules the nightly backup. At the end it prints what to paste into GitHub. Keep that window open.

## Step 5: Connect GitHub to the server

In your repository, open **Settings › Secrets and variables › Actions**:

- **Variables** tab › *New repository variable*: `DEPLOY_HOST` = `yourteam.duckdns.org`.
- **Secrets** tab › *New repository secret*:
  - `DEPLOY_SSH_KEY`: the whole content of the **private** key file. Run `Get-Content "$HOME\researchflow_deploy"` and include the `BEGIN` and `END` lines.
  - `DEPLOY_KNOWN_HOSTS`: the line the setup script printed (`yourteam.duckdns.org ssh-ed25519 AAAA...`).

Then go to **Actions › Deploy › Run workflow**. In about 3 minutes it shows ✓ and the site is live at **https://yourteam.duckdns.org**. The first page load can take up to a minute while Caddy gets the HTTPS certificate. Register your account.

You can now delete the private key from your PC (`researchflow_deploy`, not the `.pub` file). GitHub keeps its copy, and you can always make a new key and run the setup again.

---

## Everyday use

**Ship a change:** commit and `git push`. CI runs the tests, and if they pass, Deploy puts the new version live. Database changes are applied automatically and existing data is kept. If the tests fail, nothing is deployed.

**Admin commands** (on the server, from `ssh -i oracle.key ubuntu@SERVER_IP`):

```bash
cd /opt/researchflow/backend
sudo -u researchflow /opt/researchflow/venv/bin/python scripts/admin.py --env-file /etc/researchflow/backend.env list-users
sudo -u researchflow /opt/researchflow/venv/bin/python scripts/admin.py --env-file /etc/researchflow/backend.env reset-password someone@uni.edu
sudo -u researchflow /opt/researchflow/venv/bin/python scripts/admin.py --env-file /etc/researchflow/backend.env verify-email someone@uni.edu
```

| Task | Command on the server |
| --- | --- |
| Is it running? | `sudo systemctl status researchflow` |
| Live logs | `sudo journalctl -u researchflow -f` |
| HTTPS / Caddy logs | `sudo journalctl -u caddy -n 50` |
| Change settings (e.g. email) | `sudo nano /etc/researchflow/backend.env`, then `sudo systemctl restart researchflow` |
| Back up now | `sudo researchflow-backup` |
| Security updates | `sudo apt update && sudo apt -y upgrade` (monthly) |

**Email (optional):** to send verification and reset codes, get SMTP credentials from a provider with a free plan (for example Brevo), or use a Gmail account with an app password. In `/etc/researchflow/backend.env`, set `EMAIL_BACKEND=smtp`, uncomment the `SMTP_*` lines, fill them in, and restart. Without email, people can still register and sign in, and you reset passwords with `admin.py`.

## Backups

Every night at 02:30 the server saves the database and uploaded files to `/var/backups/researchflow`, keeping 14 days. That protects against mistakes, not against losing the server, so copy them to your PC now and then:

```bash
# on the server
sudo cp -r /var/backups/researchflow ~/backups && sudo chown -R ubuntu ~/backups
```
```powershell
# on your PC
scp -r -i C:\Users\you\oracle.key ubuntu@SERVER_IP:~/backups .\researchflow-backups
```

**Restore** a night's backup on the server (replace the date):

```bash
sudo systemctl stop researchflow
gunzip -c /var/backups/researchflow/db-20261029-023000.sqlite3.gz | sudo tee /var/lib/researchflow/researchflow.sqlite3 >/dev/null
sudo rm -f /var/lib/researchflow/researchflow.sqlite3-wal /var/lib/researchflow/researchflow.sqlite3-shm
sudo tar -xzf /var/backups/researchflow/uploads-20261029-023000.tar.gz -C /var/lib/researchflow
sudo chown -R researchflow:researchflow /var/lib/researchflow
sudo systemctl start researchflow
```

## Troubleshooting

| Problem | Fix |
| --- | --- |
| Deploy fails at "Upload release" with *Permission denied* or *Host key verification failed* | Re-check the `DEPLOY_SSH_KEY` and `DEPLOY_KNOWN_HOSTS` secrets. The known-hosts line must start with the same name as `DEPLOY_HOST`. |
| Deploy fails at "Activate release" | On the server: `sudo journalctl -u researchflow -n 50`. Usually a setting in `/etc/researchflow/backend.env`. |
| Site does not load or has no HTTPS | Ports 80/443 open in the Oracle **Security List** (step 1.3)? Does DuckDNS show the current IP? Check `sudo journalctl -u caddy -n 50`. |
| `ssh` on Windows says *UNPROTECTED PRIVATE KEY FILE* | `icacls C:\Users\you\oracle.key /inheritance:r /grant:r "$($env:USERNAME):(R)"` |
| Oracle says *out of capacity* | Try another availability domain, the AMD micro shape, or try again later. |
| Server IP changed (instance recreated) | Update the IP on DuckDNS. If you ran the setup on a new server, update `DEPLOY_KNOWN_HOSTS` too. |

## Notes

- **Who can sign up:** anyone with the URL can create an account, and a new account sees nothing until a project owner invites it. To allow only your institution, set `ALLOWED_EMAIL_DOMAINS=uni.edu` (comma-separate several) in `/etc/researchflow/backend.env` and restart.
- **Demo account:** `scripts/seed_dev.py` refuses to run on a production server, and the login-page demo hint does not exist outside development.
- **One API process** is intentional: SQLite and the login rate limiter both assume a single process, which comfortably serves a research group or department.
- **GitHub Actions minutes:** private repositories get 2,000 free minutes a month. A test-and-deploy run takes about 5.
- **Security layout:** the API runs as `researchflow` and can write only to `/var/lib/researchflow`. The `deploy` account used by GitHub can update the code and restart the API, and nothing else as root. Secrets live only in `/etc/researchflow/backend.env` on the server, never in GitHub.
