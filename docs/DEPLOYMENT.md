# Publishing ResearchFlow for free (no credit card)

This guide puts ResearchFlow online at `https://YOURNAME.pythonanywhere.com` with a free PythonAnywhere account. No card is needed, your data is kept, and the site does not go to sleep when nobody is using it.

```
Your PC ──git push──► GitHub ──tests pass──► "Publish" workflow builds the app
                                              and writes it to the "deploy" branch
                                                        │  git clone / git pull
                                                        ▼
                                   PythonAnywhere (free): one process serves the
                                   web app and the API; database and uploads live
                                   in ~/researchflow-data
```

## Which option is this?

| | **PythonAnywhere** (this guide) | Your own server ([DEPLOYMENT_SERVER.md](DEPLOYMENT_SERVER.md)) |
| --- | --- | --- |
| Cost | Free | Free on Oracle Cloud Always Free |
| Credit/debit card | **Not needed** | Needed to verify the account |
| Sleeps when idle | No | No |
| Keeps database and uploads | Yes | Yes |
| Disk space | 512 MB in total | Up to 200 GB |
| Address | `YOURNAME.pythonanywhere.com` | Your own domain |
| Updates | One command after each push | Automatic on every push |
| Upkeep | Click a button once a month | Security updates monthly |

**Know the limits before you start:**

- **Once a month** you must log in and click **Run until 1 month from today** on the Web tab. PythonAnywhere emails a reminder. If you miss it, the site is switched off until you click it; your data stays.
- **512 MB of disk** covers the program (about 100 MB), the database and every uploaded file. The setup therefore limits uploads to 25 MB per file and 100 MB per project. It suits papers, references, PDFs and small datasets, not large data.
- **One request at a time.** That is fine for a small team; many people uploading at once will feel slow.
- **Email is probably unavailable.** Free accounts can only reach an approved list of outside sites, so verification and reset emails may not send. People can still register and sign in, and you reset passwords with a command (below).

Total time: about 20 minutes.

---

## Step 1: Push the code and let GitHub build it

From your project folder:

```bash
git add .
git commit -m "Add free single-service deployment"
git push
```

On GitHub, open the **Actions** tab. Two workflows run one after the other:

1. **ResearchFlow CI & Security Pipeline** runs the tests.
2. **Publish** builds the web app, installs and tests the result the way PythonAnywhere runs it, and writes it to a branch named **`deploy`**.

Wait for both green ticks (about 5 minutes). You can also start it by hand: **Actions › Publish › Run workflow**.

## Step 2: Create the PythonAnywhere account

1. Go to **pythonanywhere.com** › **Pricing & signup** › **Create a Beginner account**.
2. Choose a username. It becomes your address: `YOURNAME.pythonanywhere.com`.

## Step 3: Create the web app

1. Open the **Web** tab › **Add a new web app** › **Next**.
2. Choose **Manual configuration** (not a framework).
3. Choose **Python 3.13** › **Next**.

## Step 4: Get the code

Open the **Consoles** tab › **Bash**.

**If your repository is public:**

```bash
git clone --depth 1 -b deploy https://github.com/YOUR-GITHUB-NAME/researchflow.git ~/researchflow
```

**If your repository is private**, give this one console read-only access with a deploy key:

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub
```

Copy the printed line. On GitHub open your repository › **Settings › Deploy keys › Add deploy key**, paste it, leave *Allow write access* off, and save. Then:

```bash
git clone --depth 1 -b deploy git@github.com:YOUR-GITHUB-NAME/researchflow.git ~/researchflow
```

Answer `yes` when asked whether to trust github.com.

## Step 5: Run the setup

```bash
bash ~/researchflow/setup.sh
```

It installs the Python packages, creates `~/researchflow-data` for the database and uploads, writes `~/researchflow.env` with fresh secrets and production settings, and points the web app at ResearchFlow. If you picked a different Python version in step 3, pass it: `bash ~/researchflow/setup.sh 3.12`.

## Step 6: Switch it on

Back on the **Web** tab:

1. **Virtualenv:** enter the path the setup printed (`/home/YOURNAME/.virtualenvs/researchflow`).
2. **Force HTTPS:** turn it on.
3. Click the green **Reload** button.

Open **https://YOURNAME.pythonanywhere.com** and create your account. The first account is an ordinary user; projects belong to whoever creates them.

---

## Everyday use

**Publish a change:** `git push`, wait for the **Publish** tick on GitHub, then in a PythonAnywhere Bash console:

```bash
bash ~/researchflow/update.sh
```

It downloads the new build, installs any new packages and restarts the site. Database changes are applied automatically; your data is kept.

**Keep it online:** once a month, Web tab › **Run until 1 month from today**.

**Admin commands** (Bash console):

```bash
cd ~/researchflow
~/.virtualenvs/researchflow/bin/python scripts/admin.py --env-file ~/researchflow.env list-users
~/.virtualenvs/researchflow/bin/python scripts/admin.py --env-file ~/researchflow.env reset-password someone@uni.edu
~/.virtualenvs/researchflow/bin/python scripts/admin.py --env-file ~/researchflow.env verify-email someone@uni.edu
```

**Back up:** there is no automatic backup on a free account, so do this regularly:

```bash
bash ~/researchflow/backup.sh
```

Then open the **Files** tab and download `researchflow-backup.tar.gz`. It holds the database and all uploaded files. To restore, upload that file to your home folder and run:

```bash
tar -xzf ~/researchflow-backup.tar.gz -C ~/researchflow-data && bash ~/researchflow/update.sh
```

**Change a setting:** edit `~/researchflow.env` (Files tab), then click **Reload** on the Web tab. For example, to let only your institution sign up, add `ALLOWED_EMAIL_DOMAINS=uni.edu`.

**Check disk space:** the Files tab shows how much of the 512 MB is used. When it is full, uploads and saves fail. Free space by emptying each project's trash, or lower `PROJECT_STORAGE_QUOTA_BYTES`.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| The **Publish** workflow is red | Open it on the Actions tab and read the failed step. Nothing is published until it passes, so the live site is unaffected. |
| `git clone` says the `deploy` branch does not exist | The Publish workflow has not finished yet (step 1). |
| "Something went wrong" page | Web tab › **Error log** shows the reason. The usual causes: the Virtualenv path is missing (step 6), or the Python version on the Web tab differs from the one the setup used (run `bash ~/researchflow/setup.sh 3.xx` with the Web tab's version, then Reload). |
| The page says the web app is disabled | The monthly period ran out. Web tab › **Run until 1 month from today**. |
| `setup.sh` says "No web app found yet" | Do step 3 first, then run it again. |
| Sign-in works but you are signed out at once | **Force HTTPS** is off (step 6), so the secure cookie is not sent. |
| Disk quota exceeded during setup | Delete files you do not need in the Files tab, then run the setup again. |

## Notes

- **Who can sign up:** anyone with the address can create an account, and a new account sees nothing until a project owner invites it. `ALLOWED_EMAIL_DOMAINS` limits sign-up to your institution.
- **The demo account does not exist here.** `scripts/seed_dev.py` refuses to run in production, and the login-page demo hint only exists in development.
- **Security:** secrets live only in `~/researchflow.env` on PythonAnywhere (readable by your account only), never in GitHub. Uploaded files are stored outside the web folder and served only through permission checks. The site sends a strict Content Security Policy and HTTPS-only cookies.
- **Outgrowing it:** when you need more space or automatic deploys, move to your own server with [DEPLOYMENT_SERVER.md](DEPLOYMENT_SERVER.md). Download a backup first and restore it there.
