// Runs when the toolbar icon is clicked while viewing a Reddit post.
// Extracts the post's title/body from the page and saves it as a JSON file
// under Downloads/reddit-story-queue/ for the pipeline to pick up.

async function saveToQueue(tab) {
  if (!tab.id || !tab.url || !/reddit\.com/.test(tab.url)) {
    await flash(tab.id, "ERR", "#c0392b");
    return;
  }

  let injection;
  try {
    [injection] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: extractPost,
    });
  } catch (e) {
    console.warn("Reddit Story Queue: injection failed", e);
    await flash(tab.id, "ERR", "#c0392b");
    return;
  }

  const result = injection && injection.result;
  if (!result || !result.ok) {
    const reason = (result && result.error) || "Extraction failed for an unknown reason.";
    console.warn("Reddit Story Queue:", reason);
    await flash(tab.id, "ERR", "#c0392b");
    await toast(tab.id, reason, false);
    return;
  }

  const post = result.data;
  const json = JSON.stringify(
    { ...post, queued_at: new Date().toISOString(), source: "extension" },
    null,
    2
  );
  const b64 = btoa(unescape(encodeURIComponent(json)));
  const dataUrl = `data:application/json;base64,${b64}`;
  const safeId = (post.id || String(Date.now())).replace(/[^a-zA-Z0-9_-]/g, "");

  try {
    await chrome.downloads.download({
      url: dataUrl,
      filename: `reddit-story-queue/${safeId}.json`,
      saveAs: false,
      conflictAction: "uniquify",
    });
    await flash(tab.id, "OK", "#2e7d32");
    const detail = post.selftext
      ? `${post.selftext.split(/\s+/).length} words`
      : `${(post.image_urls || []).length} image(s) -- will be transcribed`;
    await toast(tab.id, `Queued: "${post.title.slice(0, 60)}" (${detail})`, true);
  } catch (e) {
    console.warn("Reddit Story Queue: download failed", e);
    await flash(tab.id, "ERR", "#c0392b");
    await toast(tab.id, `Couldn't save the queue file: ${e}`, false);
  }
}

/** Surface the outcome in the page itself -- a red badge alone doesn't say why. */
async function toast(tabId, message, ok) {
  if (!tabId) return;
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      func: (msg, good) => {
        const el = document.createElement("div");
        el.textContent = msg;
        Object.assign(el.style, {
          position: "fixed", top: "16px", right: "16px", zIndex: "2147483647",
          maxWidth: "380px", padding: "12px 16px", borderRadius: "10px",
          font: "14px/1.4 system-ui, sans-serif", color: "#fff",
          background: good ? "#2e7d32" : "#c0392b",
          boxShadow: "0 4px 16px rgba(0,0,0,.35)", whiteSpace: "pre-wrap",
        });
        document.body.appendChild(el);
        setTimeout(() => el.remove(), good ? 4000 : 9000);
      },
      args: [message, ok],
    });
  } catch (e) {
    console.warn("Reddit Story Queue: could not show toast", e);
  }
}

async function flash(tabId, text, color) {
  if (!tabId) return;
  await chrome.action.setBadgeBackgroundColor({ color, tabId });
  await chrome.action.setBadgeText({ text, tabId });
  setTimeout(() => chrome.action.setBadgeText({ text: "", tabId }), 2500);
}

chrome.action.onClicked.addListener((tab) => {
  saveToQueue(tab);
});

// Injected into the Reddit page itself -- must be a plain, self-contained
// function (no closures over outer scope) since chrome.scripting serializes it.
function extractPost() {
  function cleanText(t) {
    return (t || "").replace(/\r/g, "").replace(/\n{3,}/g, "\n\n").trim();
  }
  function matchOrEmpty(re, str) {
    const m = str.match(re);
    return m ? m[1] : "";
  }

  try {
    // Strategy 1: modern Reddit's <shreddit-post> web component.
    const shPost = document.querySelector("shreddit-post");
    if (shPost) {
      const title = shPost.getAttribute("post-title") || document.title;
      const permalinkAttr = shPost.getAttribute("permalink");
      const permalink = permalinkAttr ? new URL(permalinkAttr, location.origin).href : location.href;
      const subredditAttr = shPost.getAttribute("subreddit-prefixed-name") || "";
      const subreddit =
        subredditAttr.replace(/^r\//i, "") || matchOrEmpty(/\/r\/([^/]+)/, location.pathname);
      const id =
        shPost.getAttribute("id") ||
        shPost.getAttribute("post-id") ||
        matchOrEmpty(/\/comments\/([a-z0-9]+)/i, location.pathname);

      const bodyEl = shPost.querySelector('[slot="text-body"]') || document.querySelector('[slot="text-body"]');
      const selftext = bodyEl ? cleanText(bodyEl.innerText) : "";

      if (selftext) {
        return { ok: true, data: { id, subreddit, title: cleanText(title), selftext, score: null, permalink } };
      }
    }

    // Strategy 2: old.reddit.com's classic markup.
    const oldTitleEl = document.querySelector("a.title, .top-matter a.title");
    const oldBodyEl = document.querySelector(".usertext-body .md, .expando .usertext-body .md");
    if (oldTitleEl && oldBodyEl) {
      const id = matchOrEmpty(/\/comments\/([a-z0-9]+)/i, location.pathname);
      const subreddit = matchOrEmpty(/\/r\/([^/]+)/, location.pathname);
      return {
        ok: true,
        data: {
          id,
          subreddit,
          title: cleanText(oldTitleEl.innerText || oldTitleEl.textContent),
          selftext: cleanText(oldBodyEl.innerText),
          score: null,
          permalink: location.href,
        },
      };
    }

    // No body text: this may still be an image post (screenshots of texts,
    // notes, chat logs), which the pipeline can transcribe. Collect the post
    // images so it can read them. Deliberately NOT scraping <main> as a
    // fallback -- that pulls in nav chrome and the whole comments section,
    // which would then get narrated as if it were the story.
    const host = document.querySelector("shreddit-post") || document.querySelector("article") || document;
    const imgs = Array.from(host.querySelectorAll("img"))
      .filter((im) => /(^|\/\/)(i|preview|external-preview)\.redd\.it\//.test(im.src || ""))
      .filter((im) => (im.naturalWidth || im.width || 0) >= 200)
      .map((im) => im.src);
    const imageUrls = Array.from(new Set(imgs)).slice(0, 6);

    if (imageUrls.length) {
      const id = matchOrEmpty(/\/comments\/([a-z0-9]+)/i, location.pathname) || String(Date.now());
      const subreddit = matchOrEmpty(/\/r\/([^/]+)/, location.pathname);
      const ogTitleEl = document.querySelector('meta[property="og:title"]');
      const title = cleanText(
        (shPost && shPost.getAttribute("post-title")) || (ogTitleEl ? ogTitleEl.content : document.title)
      );
      return {
        ok: true,
        kind: "image",
        data: { id, subreddit, title, selftext: "", image_urls: imageUrls, score: null, permalink: location.href },
      };
    }

    return {
      ok: false,
      error:
        "No post body or images found. This looks like a link post or a feed page rather than a " +
        "single post -- there's nothing to narrate. Open a text post or an image post and try again.",
    };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}
