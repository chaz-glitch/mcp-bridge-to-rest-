[DEPLOY_README-2.md](https://github.com/user-attachments/files/30841936/DEPLOY_README-2.md)
# Getting this running - step by step

This is the bridge between Claude and Distru. It has to live somewhere on the
internet, running all the time, with its own web address - not on your laptop,
not inside a Claude chat.

## Updating an EXISTING deployment (you already have this running)

This version adds a second layer of protection: the bridge now requires a
secret to answer any request, not just a real Distru token buried inside it.
Follow this order exactly to avoid a gap where the bridge is briefly down:

1. **First**, in Railway, go to your existing service -> Variables -> New
   Variable, and add:
   - Name: `BRIDGE_SECRET`
   - Value: `Tc24Tv8f49fp2h-fk5HXfKVWMhmD_9BbPGQtvdzGrpk`

   (Adding this now, before the new code arrives, is what avoids any
   downtime - the old code doesn't look for this variable yet, so adding it
   early is harmless.)
2. **Then**, update `distru_mcp_server.py` on GitHub with the new version -
   same as every previous update: click the file, pencil icon, replace the
   contents, commit. This triggers a fresh deploy automatically.
3. Wait for it to show "Online" again in Railway.
4. **Last**, go back to Claude's Custom Connector settings and change the URL
   you originally entered from:
   `https://your-app.up.railway.app/mcp`
   to:
   `https://your-app.up.railway.app/mcp?key=Tc24Tv8f49fp2h-fk5HXfKVWMhmD_9BbPGQtvdzGrpk`

   That's the whole change - same URL, with `?key=...` added to the end.
   Without it, requests will now get rejected (that's the fix working
   correctly, not a new bug).

Keep that secret value private the same way you'd treat the Distru token
itself - anyone who has it can use the bridge, same as anyone who has your
Distru token could use Distru directly.

## The simplest path for a NEW deployment: Railway (free tier is enough)

1. Go to railway.app and sign up (you can use your GitHub account, or email)
2. Click "New Project" -> "Deploy from GitHub repo" (you'll need to put these
   three files - `distru_mcp_server.py`, `requirements.txt`, and this file -
   into a new GitHub repository first; GitHub's "upload files" button on a new
   repo works fine, no command-line needed)
3. Once Railway finds your repo, it will try to run it automatically
4. Before it starts, go to the "Variables" tab and add two:
   - Name: `DISTRU_API_TOKEN`, Value: your Distru token (the one starting
     with `eyJ...`)
   - Name: `BRIDGE_SECRET`, Value: a strong random string - the server will
     refuse to start without one

   This is the secure way to hand it these values - stored by Railway, not
   typed into any chat or written into the code itself.
5. Once it deploys, Railway will show you a public URL, something like
   `https://distru-bridge-production.up.railway.app`
6. **In Claude's Custom Connector screen, use that URL with `?key=` and your
   BRIDGE_SECRET value appended** - e.g.
   `https://distru-bridge-production.up.railway.app/mcp?key=your-secret-here`

## Other options, if you'd rather not use Railway

Render.com and Fly.io work the same basic way: point them at your code, set
the same `DISTRU_API_TOKEN` and `BRIDGE_SECRET` environment variables, get
back a public URL, use that URL (with `?key=...`) in Claude's connector setup.

## If something goes wrong

The most likely hiccup is the `mcp` package's exact setup command shifting
slightly since this was written (it's a newer library and updates often).
If the deploy fails, copy the exact error message from Railway's build logs
and send it over - that's usually a five-minute fix, not a rebuild.

This update specifically also has one more thing that could need a small
fix: the exact method name used to pull Leaflet's underlying app out for
wrapping with the new secret check is a best-effort guess, not confirmed
against a real run. If the deploy logs show a "DIAGNOSTIC: mcp.streamable_
http_app() doesn't exist" message, that's expected in that scenario, not
alarming - it'll also print the real list of what IS available, and send
that over the same way as any other error log.
