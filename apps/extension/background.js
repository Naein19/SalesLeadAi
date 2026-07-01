// Background service worker — handles extension lifecycle
chrome.runtime.onInstalled.addListener(() => {
  console.log('[LeadAI] Extension installed');
});

// Store API base URL only if not already set
chrome.storage.local.get(['apiBaseUrl'], (result) => {
  if (!result.apiBaseUrl) {
    chrome.storage.local.set({
      apiBaseUrl: 'http://localhost:8000'
    });
  }
});
