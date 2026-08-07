# Getting this running - step by step

This is the bridge between Claude and Distru. It has to live somewhere on the
internet, running all the time, with its own web address - not on your laptop,
not inside a Claude chat.

## The simplest path: Railway (free tier is enough for this)

1. Go to railway.app and sign up (you can use your GitHub account, or email)
2. Click "New Project" -> "Deploy from GitHub repo" (you'll need to put these
   three files - `distru_mcp_server.py`, `requirements.txt`, and this file -
   into a new GitHub repository first; GitHub's "upload files" button on a new
   repo works fine, no command-line needed)
3. Once Railway finds your repo, it will try to run it automatically
4. Before it starts, go to the "Variables" tab and add one:
   - Name: `DISTRU_API_TOKEN`
   - Value: your Distru token (the one starting with `eyJ...`)

   This is the secure way to hand it your token - it's stored by Railway, not
   typed into any chat or written into the code itself.
5. Once it deploys, Railway will show you a public URL, something like
   `https://distru-bridge-production.up.railway.app`
6. **That URL is what goes into Claude's Custom Connector screen** - not
   Distru's URL, not your token. Just that Railway address.

## Other options, if you'd rather not use Railway

Render.com and Fly.io work the same basic way: point them at your code, set
the same `DISTRU_API_TOKEN` environment variable, get back a public URL, use
that URL in Claude's connector setup.

## If something goes wrong

The most likely hiccup is the `mcp` package's exact setup command shifting
slightly since this was written (it's a newer library and updates often).
If the deploy fails, copy the exact error message from Railway's build logs
and send it over - that's usually a five-minute fix, not a rebuild.
