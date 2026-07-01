/**
 * Chrome Extension Content Script — LinkedIn DOM extractor
 *
 * Runs on all LinkedIn pages. Listens for messages from the popup,
 * extracts visible profile data from the DOM (no API calls),
 * and returns structured data.
 *
 * Known failure modes:
 * - LinkedIn may change CSS class names (DOM selectors may break)
 * - Company pages have different structure than personal profiles
 */

const PROFILE_SELECTORS = {
  name: [
    'h1.text-heading-xlarge',
    '.pv-text-details__left-panel h1',
    'h1[class*="title"]',
    '.inline.t-24.t-black.t-normal.break-words',
    '[data-generated-suggestion-target]'
  ],
  title: [
    '.text-body-medium.break-words',
    '.pv-text-details__left-panel .text-body-medium',
    '.pv-text-details__left-panel .text-body-large',
    'h2.text-body-medium'
  ],
  company: [
    '.pv-text-details__right-panel .hoverable-link-text',
    '.inline-show-more-text--is-collapsed .hoverable-link-text',
    'button[aria-label*="Current company"] .visually-hidden',
    '.pv-entity__summary-info h3',
    'ul.pv-text-details__right-panel li button span'
  ],
  location: [
    '.text-body-small.inline.t-black--light.break-words',
    '.pv-text-details__left-panel span.t-black--light',
    '.pv-top-card--list-bullet li.t-black--light'
  ],
};

function extractFirst(selectors) {
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el) {
      const text = el.innerText?.trim();
      if (text) return text;
    }
  }
  return null;
}

function isCompanyPage() {
  return window.location.pathname.startsWith('/company/');
}

function extractProfileData() {
  const url = window.location.href;
  const hostname = window.location.hostname;

  // Generic Company Website Logic
  if (!hostname.includes('linkedin.com')) {
    // Try to find the best company name from meta tags or title
    const metaOgSiteName = document.querySelector('meta[property="og:site_name"]')?.content;
    const metaOgTitle = document.querySelector('meta[property="og:title"]')?.content;
    const documentTitle = document.title.split('-')[0].split('|')[0].trim();
    
    const companyName = metaOgSiteName || metaOgTitle || documentTitle || hostname;
    
    const description = document.querySelector('meta[name="description"]')?.content 
                     || document.querySelector('meta[property="og:description"]')?.content
                     || null;

    return {
      type: 'company',
      company: companyName,
      url: url,
      description: description,
      name: null,
      title: null,
      location: null,
    };
  }

  // LinkedIn Company Page Logic
  if (isCompanyPage()) {
    const companyName = document.querySelector('h1.org-top-card-summary__title')?.innerText?.trim()
      || document.querySelector('h1[class*="title"]')?.innerText?.trim()
      || document.querySelector('.org-top-card-summary__title-wrapper h1')?.innerText?.trim()
      || null;
    const description = document.querySelector('.org-top-card-summary-info-list__info-item')?.innerText?.trim() || null;

    return {
      type: 'company',
      company: companyName,
      url,
      description,
      name: null,
      title: null,
      location: null,
    };
  }

  // Personal profile extraction
  return {
    type: 'person',
    name: extractFirst(PROFILE_SELECTORS.name),
    title: extractFirst(PROFILE_SELECTORS.title),
    company: extractFirst(PROFILE_SELECTORS.company),
    location: extractFirst(PROFILE_SELECTORS.location),
    url,
  };
}

// Listen for messages from popup
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === 'EXTRACT_PROFILE') {
    const data = extractProfileData();
    sendResponse({ success: true, data });
  }
  return true; // Keep channel open for async response
});
