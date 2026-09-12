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
    console.warn("Reddit Story Queue: extraction failed", result && result.error);
    await flash(tab.id, "ERR", "#c0392b");
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
    await flash(tab.id, result.lowConfidence ? "OK?" : "OK", "#2e7d32");
  } catch (e) {
    console.warn("Reddit Story Queue: download failed", e);
    await flash(tab.id, "ERR", "#c0392b");
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

    // Strategy 3: last-resort generic fallback -- grabs the main content
    // area's text. Flagged low-confidence since it may include noise.
    const ogTitleEl = document.querySelector('meta[property="og:title"]');
    const ogTitle = ogTitleEl ? ogTitleEl.content : document.title;
    const main = document.querySelector("main");
    const fallbackText = main ? cleanText(main.innerText).slice(0, 4000) : "";
    if (fallbackText) {
      const id = matchOrEmpty(/\/comments\/([a-z0-9]+)/i, location.pathname) || String(Date.now());
      const subreddit = matchOrEmpty(/\/r\/([^/]+)/, location.pathname);
      return {
        ok: true,
        lowConfidence: true,
        data: { id, subreddit, title: cleanText(ogTitle), selftext: fallbackText, score: null, permalink: location.href },
      };
    }

    return { ok: false, error: "Could not find a post title/body on this page. Make sure you're on a text-post page." };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}
