# Gmail script

Centinel reads your Gmail through this small Google Apps Script. It runs on
Google's servers under your own account, so there is no Google Cloud project to
create and no public server to expose. It is **read-only**: `appsscript.json`
grants only the `gmail.readonly` scope, so it can never send, change or delete
mail. Every request must carry a secret that only you and Centinel know.

## Setup (once)

1. Generate a secret:

   ```sh
   uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. Go to [script.google.com](https://script.google.com) and create a new project.
   Name it `Centinel`.
3. In **Project Settings**, check **Show "appsscript.json" manifest file in
   editor**.
4. In **Editor**, replace the contents of `Code.gs` and `appsscript.json` with
   the files in this folder.
5. In **Project Settings → Script properties**, add a property
   `CENTINEL_SECRET` with the secret from step 1.
6. Click **Deploy → New deployment**, choose the type **Web app**, and set:
   - **Execute as:** Me
   - **Who has access:** Anyone

   Click **Deploy** and authorize access. Google warns that the app is not
   verified because you wrote it yourself: click **Advanced → Go to Centinel**.
   The permission it asks for should be only to *view* your email.
7. Copy the **Web app URL** and add both values to your `.env`:

   ```sh
   GMAIL_SCRIPT_URL=https://script.google.com/macros/s/.../exec
   GMAIL_SCRIPT_SECRET=<the secret from step 1>
   ```

8. Check that it answers (it should print `{"emails": [...]}`):

   ```sh
   curl -L "$GMAIL_SCRIPT_URL?secret=$GMAIL_SCRIPT_SECRET&action=search&senders=someone@example.com&days=7"
   ```

The secret and the URL are like a password: keep them only in `.env`, which is
never committed.

## Updating the script

After changing `Code.gs`, use **Deploy → Manage deployments → Edit → Version:
New version** so the same URL serves the new code. A new deployment would get a
new URL.
