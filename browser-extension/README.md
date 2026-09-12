# Reddit Story Queue (browser extension)

Click the toolbar icon while you're viewing a Reddit post you want narrated. It
saves the title + body text into `Downloads/reddit-story-queue/` as a JSON
file. `run_pipeline.py` checks that folder first, before it ever touches the
Reddit API -- so this only ever sends posts *you* personally chose to view
and click on, not an automated bulk scrape.

## Install (Chrome / Edge)

1. Go to `chrome://extensions` (or `edge://extensions`)
2. Turn on **Developer mode** (top right)
3. Click **Load unpacked**
4. Select this `browser-extension` folder
5. Pin the extension (puzzle-piece icon in the toolbar -> pin) so it's easy to click

## Use

1. Browse Reddit normally, open a text post you like (works on both the new
   Reddit UI and old.reddit.com)
2. Click the extension's toolbar icon
3. A green **OK** badge means it saved. A **OK?** badge means it saved but
   used a lower-confidence fallback extractor -- check the saved JSON file
   before relying on it. A red **ERR** badge means it couldn't find a
   post title/body on that page (you're probably not on a single-post view).

Queued posts land in `%USERPROFILE%\Downloads\reddit-story-queue\`. The
pipeline moves each one to a `used\` subfolder there once it's been turned
into a video, so nothing gets narrated twice.

## Notes

- Reddit's page markup changes over time; if extraction stops working
  (repeated ERR badges), the selectors in `background.js`'s `extractPost()`
  function need updating to match Reddit's current DOM.
- This extension doesn't run in the background or touch any page you haven't
  clicked it on -- no scraping happens unless you click.
