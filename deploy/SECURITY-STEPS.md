# Security steps that need you (GitHub and the server)

These can't be done from the code. Do them once, in this order.

---

## 1. Old secrets in the GitHub history

`api_keys.txt` and `db.sqlite3` were committed before `.gitignore` existed. Removing them
later (DEPLOY.md step 0a) only stopped tracking them: every old commit still contains them, so
anyone who can open the repository can still download the old Gemini keys and the old database
(emails, password hashes, survey answers).

### 1a. Kill the old Gemini keys (do this first, it takes two minutes)

1. Open [Google AI Studio → API keys](https://aistudio.google.com/apikey) with every Google
   account whose keys were ever in `api_keys.txt`.
2. Delete every key that was in the file before the "Prepare for deployment" commit.
3. Create new keys and put them in `api_keys.txt` on the server (Data → Extract Skills) and on
   your PC. Never commit them.

Once the old keys are deleted, the copies in the history are useless.

### 1b. Hide or remove the old database

Easiest: **make the repository private.** The repository owner (AikaAtUE) opens the repository
on GitHub → **Settings** → scroll to **Danger Zone** → **Change visibility** → **Private**.
Collaborators keep access; nobody else can read the history.

If it has to stay public, remove the files from every commit instead (this rewrites history,
so tell your teammates first):

```
pip install git-filter-repo
git clone --mirror https://github.com/AikaAtUE/uenvision-capstone.git
cd uenvision-capstone.git
git filter-repo --invert-paths --path api_keys.txt --path db.sqlite3
git push --force --mirror
```

Afterwards everyone deletes their local copy and clones again (old copies still have the
files and would put them back on the next push). On the server, first copy the `data/` folder
somewhere safe (`cp -a data ~/data-backup`), then run
`git fetch origin && git reset --hard origin/main` in `/home/uenvision/uenvision-capstone`
and copy back any files under `data/` the site changed (custom skills, recommendations).
`db.sqlite3`, `.env` and `api_keys.txt` are not tracked by git, so the reset leaves them alone.
Forks and old clones made by other people can't be cleaned this way, so step 1a still matters.

### 1c. Passwords from the old database

The update adds a check (migration 0010) that flags every account still using `default123` or
`rizal123`: those users are sent to Settings to choose a new password the next time they log in.
Anyone whose account was in the old committed database and whose password was something they
also use elsewhere should change it.

---

## 2. Turn on HTTPS

While the site runs on `http://201.18.219.201`, passwords and login cookies travel unencrypted.

1. Check what the server has now: `ssh root@201.18.219.201`, then
   `grep -E 'DJANGO_HTTPS|ALLOWED_HOSTS|CSRF' /home/uenvision/uenvision-capstone/.env`.
   If `DJANGO_HTTPS=1` and the site opens on `https://`, you are done.
2. Otherwise follow **DEPLOY.md, Step 8** with your domain (`uenvision.tech`, the one the
   noreply mailbox uses, if that is where the site lives):
   - add `uenvision.tech www.uenvision.tech` to `server_name` in the nginx file,
   - add them to `DJANGO_ALLOWED_HOSTS` in `.env`,
   - run `certbot --nginx -d uenvision.tech -d www.uenvision.tech` and choose **redirect**,
   - in `.env` set `DJANGO_HTTPS=1` and
     `DJANGO_CSRF_TRUSTED_ORIGINS=https://uenvision.tech,https://www.uenvision.tech`,
   - `systemctl restart uenvision`.
3. Open `https://uenvision.tech`, log in, and check the padlock. After a few days without
   problems, set `DJANGO_HSTS_SECONDS=31536000` and restart again.
