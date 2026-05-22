# The Dotty Project — Discord community server

This directory holds the tooling to stand up the official Discord community for
The Dotty Project. The **server itself is created by hand** (Discord's API can't
create a server you personally own); everything *inside* it — roles, categories,
channels, permissions — is provisioned by `provision.py` so the layout is
reproducible and version-controlled.

## The layout it builds

```
Roles:  @Maintainer  @Contributor  @Helper  @Builder

📌 INFORMATION
   #welcome-and-rules    Community Rules channel — read-only
   #announcements        Announcement channel — read-only
   🔒 #mod-updates       Community Updates channel — mods only
💬 COMMUNITY
   #general  #introductions  #show-your-dotty (forum)  #off-topic
🛠️ BUILD & SUPPORT
   #setup-help (forum)  #hardware-and-firmware  #voice-and-self-hosting
🧑‍💻 DEVELOPMENT
   #github-feed (read-only)  #contributing  #feature-ideas
🔊 VOICE
   General   Build Hangout
```

Edit the `ROLES` and `LAYOUT` constants at the top of `provision.py` to change
it. The script is **idempotent** — re-run it after edits and it only adds what's
missing. It never deletes channels.

## One-time setup

### 1. Create the server

In the Discord app: click the `+` in the server rail → **Create My Own** →
**For a club or community** → name it *The Dotty Project*, add an icon.

### 2. Enable the Community feature

Server Settings → **Enable Community** → run the wizard. It requires a verified
email on your account and walks you through creating a **Rules channel** and a
**Community Updates channel**. Accept its defaults — `provision.py` finds those
two channels automatically and slots them into the `INFORMATION` category.
Enabling Community is what unlocks Announcement channels and the welcome screen.

### 3. Create the bot

Go to <https://discord.com/developers/applications> → **New Application** → name
it (e.g. *Dotty Concierge*) → **Bot** tab → **Reset Token** → copy the token.
No privileged intents are needed for provisioning.

### 4. Invite the bot

OAuth2 → **URL Generator** → scope `bot` → permission **Administrator** → open
the generated URL and add the bot to your server. (Administrator keeps setup
painless; tighten or remove it afterward — see step 7.)

Equivalent direct URL — replace `CLIENT_ID` with your application's ID:

```
https://discord.com/oauth2/authorize?client_id=CLIENT_ID&scope=bot&permissions=8
```

### 5. Run the provisioner

```bash
cd community/discord
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then paste your bot token into .env
python provision.py
```

The bot connects, builds the layout, prints what it created, and exits.

### 6. Wire up the GitHub feed

No bot needed for this. In Discord: `#github-feed` → **Edit Channel** →
**Integrations** → **Webhooks** → **New Webhook** → copy its URL. Then in the
GitHub repo: **Settings → Webhooks → Add webhook**, paste the URL **with
`/github` appended**, content type `application/json`, and choose which events
to send (pushes, PRs, issues). Commits and PRs now post automatically.

### 7. Lock it down

Once the layout looks right, you no longer need an Administrator bot sitting in
the server. Either remove the bot, or in Server Settings → Roles drop its role
down to just **Manage Channels** + **Manage Roles** so future re-runs still work
without granting it full control.

### 8. Share it

Create an invite link (right-click the server → Invite People → **Edit invite
link** → set it to never expire) and add it to the project README.
