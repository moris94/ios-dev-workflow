---
name: support-page
description: Create and publish the App Store support URL and privacy policy URL. Unless the human already configured their own URLs, generate ONE bilingual (en/ja) page that is both the support page and the privacy policy, fill the support e-mail from the FACTORY_SUPPORT_EMAIL environment variable, publish it to Notion through a connected Notion MCP server (or show the text for manual publishing when no Notion MCP is connected), and record the URL. Use for the factory "support_page" stage.
user-invocable: false
---

# Support & privacy page (stage `support_page`)


## 0. Decide
`app-factory support-page status`
- `links_user_specified: true` → the human gave their own URLs in `factory/config.json` (`app.links.support`,
  `app.links.privacy_policy`). Run `app-factory support-page use-existing`, then gate. Nothing is generated.
- otherwise continue.
- `email_env_set: false` → **stop and ask the human** to set `FACTORY_SUPPORT_EMAIL` (the public support address)
  in their environment. Never invent an address and never write the address into a committed file.

## 1. Draft (committed, no e-mail inside)
`app-factory support-page draft` writes `factory/artifacts/support_page/page.md` from config/MVP/charter:
English then Japanese; sections `## Support` / `## Privacy Policy` / `## サポート` / `## プライバシーポリシー`;
the address appears only as the placeholder `{{SUPPORT_EMAIL}}`.
Review and edit the wording if needed so it matches the charter's tone and the MVP's real data handling
(`mvp.privacy`: every collected data type must be named; mention tracking honestly; explain purchases, Restore
Purchases and Apple refunds when the app sells IAP). Keep the headings and the placeholder.

## 2. Render (e-mail filled in, not committed)
`app-factory support-page render` → `.factory-tmp/support-page/page.rendered.md` (title + content with the real address).

## 3. Publish
**If a Notion MCP server is connected** (tools named like `mcp__Notion__notion-create-pages`,
`…notion-update-page`, `…notion-search`, `…notion-fetch`):
1. Parent page: use `FACTORY_NOTION_PARENT_PAGE` if set (a page URL or id). Strongly recommended: a parent page
   that is already *Shared → Published to web*, so the new child page is public immediately (the Notion API/MCP
   cannot switch on "Publish to web" itself). If unset, search Notion for a suitable published parent or ask the human.
2. Create one page with `notion-create-pages` under that parent: title = the rendered title, content = the rendered
   Markdown (keep the heading structure).
   If the page already exists from an earlier run (check `factory/artifacts/support_page/publication.json` →
   `notion_page_id`), **update that page with `notion-update-page` instead of creating a duplicate**.
3. Take the page's public URL (notion.site / notion.so link of the published page).
4. `app-factory support-page record --url <public URL> --provider notion --notion-page-id <id>` — checks the URL answers HTTP 200 and writes
   `publication.json`, then sets **both** `app.links.support` and `app.links.privacy_policy` to that URL.
   If the check fails, the page is not public yet: ask the human to enable *Share → Publish* on the page (or its parent), then record again.

**If no Notion MCP server is connected**: show the full rendered page text (from `.factory-tmp/support-page/page.rendered.md`)
to the human in the conversation, ask them to publish it (Notion, GitHub Pages, their website…) and tell you the public
URL, then run `app-factory support-page record --url <URL> --provider manual`. This is a human stop.

## 4. Gate
`app-factory gate support_page --owner <owner>` — sections present in en/ja, placeholder used and no hard-coded address,
IAP/data types covered, published content equals the current draft (edit → re-render → re-publish → re-record),
URL is public https and reachable, and both config links point to it.

Downstream: `aso` uses the same URL for `support_url` and `privacy_policy_url`; the app's `AppLinks.swift`
(Settings and paywall links) is generated from the same config, so the store and the app never disagree.
