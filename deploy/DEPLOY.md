# Deploying UEnvision to the Hostinger VPS

This guide puts UEnvision online on the Hostinger Ubuntu VPS at **201.18.219.201**.
When you finish, the site runs like this:

```
browser  ->  nginx (port 80/443, serves /static/)  ->  gunicorn (runs Django)  ->  db.sqlite3
```

- **nginx** is the web server that faces the internet.
- **gunicorn** runs the Django app. **systemd** keeps it running and restarts it after a reboot.
- Settings that differ on the server (debug off, secret key, host names) live in a `.env` file
  on the server, never in Git.

Commands in grey boxes are typed into a terminal. Lines starting with `#` are comments; you
don't type them. Where it says **on your PC**, use PowerShell on Windows. Where it says
**on the server**, use the SSH window you open in step 2.

Nothing in this guide contains a password. You choose your own when asked.

---

## Step 0. Before you start (on your PC)

### 0a. Stop tracking secret files in Git

`api_keys.txt` and `db.sqlite3` were committed to GitHub before there was a `.gitignore`.
Adding `.gitignore` alone does not remove them from Git. Run this once in the project folder
(PowerShell or Git Bash, inside `uenvision-capstone`):

```
git rm --cached api_keys.txt db.sqlite3
git rm -r --cached --quiet UEnvision/__pycache__ myapp/__pycache__ myapp/migrations/__pycache__ myapp/pipeline/__pycache__
git rm --cached data/.state/run.json data/.state/run.log data/.state/run_config.json
git add .
git commit -m "Prepare for deployment; stop tracking secrets and local files"
git push
```

`--cached` only removes them from Git. Your own copies on your PC stay where they are.

> **Do this before step 4.** If the server copies the code while `db.sqlite3` is still in
> Git, a later `git pull` of this commit would delete the server's database file.

### 0b. Replace your Gemini API keys

The old keys are still visible in the GitHub history. Open
[Google AI Studio → API keys](https://aistudio.google.com/apikey), create new keys, delete the
old ones, and put the new keys in your local `api_keys.txt`.

---

## Step 1. Point a domain at the VPS (optional)

You can use the site at `http://201.18.219.201` with no domain. If you want a name like
`uenvision.example.com` and HTTPS:

1. In your domain provider's DNS settings (Hostinger hPanel → Domains → DNS, if the domain is
   with Hostinger), add an **A record**: name `@`, points to `201.18.219.201`.
2. Add another A record: name `www`, points to `201.18.219.201`.
3. DNS can take from a few minutes to a few hours. You can keep going in the meantime.

In the rest of this guide, replace `yourdomain.com` with your real domain.

---

## Step 2. Connect to the server (on your PC)

In hPanel → VPS, find the root password (or set one). Then in PowerShell:

```
ssh root@201.18.219.201
```

Type `yes` the first time, then the root password. Everything from here until step 9 is
**on the server**.

---

## Step 3. Install the software

```
apt update && apt upgrade -y
apt install -y python3 python3-venv python3-pip git nginx sqlite3
```

Turn on the firewall, allowing SSH and the web:

```
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw enable
```

Type `y` when asked. (If hPanel also has a firewall for the VPS, allow ports 22, 80 and 443
there too.)

---

## Step 4. Create an app user and get the code

The site runs as its own user, `uenvision`, not as root:

```
adduser --disabled-password --gecos "" uenvision
mkdir -p /var/www/uenvision/static
chown uenvision:www-data /var/www/uenvision/static
```

Switch to that user and download the code:

```
sudo -u uenvision -i
git clone https://github.com/AikaAtUE/uenvision-capstone.git
cd uenvision-capstone
```

If the repository is private, Git asks for a username and password. Use your GitHub username
and a **personal access token** as the password (GitHub → Settings → Developer settings →
Personal access tokens → Fine-grained tokens, with read access to this repository).
To avoid typing it on every update, run `git config --global credential.helper store` before
cloning; Git then remembers the token for the `uenvision` user.

Create the Python environment and install the requirements:

```
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
```

This takes a few minutes (pandas is large).

---

## Step 5. Create the .env file

Still as the `uenvision` user, inside `~/uenvision-capstone`:

```
cp deploy/.env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
nano .env
```

The `python3` line prints a long random string. In nano:

- Paste that string after `DJANGO_SECRET_KEY=` (right-click pastes in PowerShell).
- If you have a domain, add it to `DJANGO_ALLOWED_HOSTS`, e.g.
  `DJANGO_ALLOWED_HOSTS=201.18.219.201,yourdomain.com,www.yourdomain.com`
  and to `DJANGO_CSRF_TRUSTED_ORIGINS`, e.g.
  `DJANGO_CSRF_TRUSTED_ORIGINS=http://201.18.219.201,http://yourdomain.com,http://www.yourdomain.com`
- Leave `DJANGO_HTTPS=0` for now.

Save with **Ctrl+O**, **Enter**, then exit with **Ctrl+X**. Protect the file:

```
chmod 600 .env
```

---

## Step 6. Copy your database and API keys from your PC

Type `exit` to leave the `uenvision` user (you are root again). Leave this window open and open
a **second PowerShell window on your PC**:

```
scp "D:\School Documents\Official UEnvision (Github)\uenvision-capstone\db.sqlite3" root@201.18.219.201:/tmp/db.sqlite3
scp "D:\School Documents\Official UEnvision (Github)\uenvision-capstone\api_keys.txt" root@201.18.219.201:/tmp/api_keys.txt
```

Back in the **server** window, move them into place and give them to the app user:

```
mv /tmp/db.sqlite3 /tmp/api_keys.txt /home/uenvision/uenvision-capstone/
chown uenvision:www-data /home/uenvision/uenvision-capstone/db.sqlite3 /home/uenvision/uenvision-capstone/api_keys.txt
chmod 660 /home/uenvision/uenvision-capstone/db.sqlite3
chmod 600 /home/uenvision/uenvision-capstone/api_keys.txt
```

(Skipping `api_keys.txt` is fine if you put keys in `GEMINI_API_KEYS` in `.env` instead, or
plan to paste them on the Data → Extract Skills page.)

Now prepare the database and static files as the app user:

```
sudo -u uenvision -i
cd uenvision-capstone
set -a; . ./.env; set +a
venv/bin/python manage.py migrate
venv/bin/python manage.py collectstatic --noinput
venv/bin/python manage.py check --deploy
exit
```

`check --deploy` may print warnings about HSTS or HTTPS. Those are expected until step 8.

If you did **not** copy a database and need a first administrator account, run
`venv/bin/python manage.py createsuperuser` before `exit`.

---

## Step 7. Start gunicorn and nginx

As root:

```
cp /home/uenvision/uenvision-capstone/deploy/uenvision.service /etc/systemd/system/uenvision.service
systemctl daemon-reload
systemctl enable --now uenvision
systemctl status uenvision
```

You should see **active (running)** in green. Press **q** to leave the status screen.

Set up nginx:

```
cp /home/uenvision/uenvision-capstone/deploy/nginx-uenvision.conf /etc/nginx/sites-available/uenvision
ln -s /etc/nginx/sites-available/uenvision /etc/nginx/sites-enabled/uenvision
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx
```

`nginx -t` must say **syntax is ok** and **test is successful**.

Open **http://201.18.219.201** in your browser. You should see UEnvision and be able to log in
with your existing accounts.

---

## Step 8. Turn on HTTPS (only if you have a domain)

Wait until the domain opens the site over `http://yourdomain.com`. Then add the domain to nginx:

```
nano /etc/nginx/sites-available/uenvision
```

Change the `server_name` line to:

```
    server_name 201.18.219.201 yourdomain.com www.yourdomain.com;
```

Save, then:

```
nginx -t && systemctl reload nginx
apt install -y certbot python3-certbot-nginx
certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

Certbot asks for an email (for expiry notices) and to accept its terms. When asked about
redirecting HTTP to HTTPS, choose **redirect**. Certificates renew automatically.

Now tell Django it is on HTTPS. Edit `.env`:

```
nano /home/uenvision/uenvision-capstone/.env
```

- Set `DJANGO_HTTPS=1`
- Change `DJANGO_CSRF_TRUSTED_ORIGINS` to
  `https://yourdomain.com,https://www.yourdomain.com`

Save, then restart:

```
systemctl restart uenvision
```

Open **https://yourdomain.com** and log in to check that it works. Once HTTPS has worked for a
few days, you can raise `DJANGO_HSTS_SECONDS` to `31536000` and restart again.

> With `DJANGO_HTTPS=1`, logging in over plain `http://201.18.219.201` no longer works, because
> the login cookie is HTTPS-only. Use the domain from then on.

---

## Updating the site later

1. **On your PC:** make your changes, test with `python manage.py runserver`, then `git push`.
2. **On the server** (`ssh root@201.18.219.201`):

```
sudo bash /home/uenvision/uenvision-capstone/deploy/update.sh
```

That script backs up `db.sqlite3` (as `db.sqlite3.<date>.bak`), pulls the new code, installs any
new requirements, runs migrations, collects static files, and restarts gunicorn.

If `deploy/uenvision.service` or `deploy/nginx-uenvision.conf` changed, copy them again as in
step 7 and run `systemctl daemon-reload` / `systemctl reload nginx`.

Restarting stops any scrape or skill extraction running on the Data page, so update when none
is running.

---

## Backing up the database

The live data (accounts, survey answers) is in `/home/uenvision/uenvision-capstone/db.sqlite3`
on the server. To download a copy to your PC (PowerShell on your PC):

```
scp root@201.18.219.201:/home/uenvision/uenvision-capstone/db.sqlite3 "$HOME\Downloads\uenvision-backup.sqlite3"
```

Do not copy your local `db.sqlite3` to the server again after people start using the live
site, or their new data is overwritten.

---

## When something goes wrong

| What you see | What to check |
| --- | --- |
| **502 Bad Gateway** | gunicorn isn't running: `systemctl status uenvision` and `journalctl -u uenvision -n 50` |
| **Bad Request (400)** | The address you typed isn't in `DJANGO_ALLOWED_HOSTS` in `.env`. Add it, then `systemctl restart uenvision` |
| **CSRF verification failed** when submitting a form | Add the exact `http://` or `https://` address to `DJANGO_CSRF_TRUSTED_ORIGINS`, then restart |
| Page has no styling | Run collectstatic again (step 6) and check `/var/www/uenvision/static` has files |
| `attempt to write a readonly database` | `chown uenvision:www-data` on `db.sqlite3` **and** the `uenvision-capstone` folder |
| Gemini says no API key | Check `api_keys.txt` on the server, or `GEMINI_API_KEYS` in `.env`, then restart |
| nginx errors | `nginx -t` and `tail -n 50 /var/log/nginx/error.log` |

Useful commands:

```
systemctl restart uenvision        # restart the app after changing .env
journalctl -u uenvision -f         # watch the app's log live (Ctrl+C to stop)
systemctl reload nginx             # after editing the nginx file
```

---

## Running locally is unchanged

On your PC nothing new is needed: with no `.env`, Django uses `DEBUG=True`, the old development
secret key, `localhost`, and `api_keys.txt` exactly as before. `python manage.py runserver`
works the same way.
