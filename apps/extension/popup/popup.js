/**
 * LeadAI Chrome Extension — Popup Script
 * Handles: DOM extraction, API communication, real-time status updates
 */

let API_BASE = 'http://localhost:8000';
const POLL_INTERVAL_MS = 2000;
let currentLeadId = null;
let pollTimer = null;
let activeTabId = null;
let activeTabUrl = null;

const $ = id => document.getElementById(id);

// ── Settings Button ───────────────────────────────────────────────────────────
$('settingsBtn')?.addEventListener('click', () => {
  chrome.runtime.openOptionsPage();
});

// ── State management ──────────────────────────────────────────────────────────

function showState(stateName) {
  ['notLinkedIn', 'readyState', 'loadingState', 'resultState'].forEach(id => {
    $(id)?.classList.add('hidden');
  });
  $(stateName)?.classList.remove('hidden');
}

// ── Boot ──────────────────────────────────────────────────────────────────────

async function init() {
  // Load API base URL from storage
  const storage = await chrome.storage.local.get(['apiBaseUrl', 'activeLeadInfo']);
  if (storage.apiBaseUrl) {
    API_BASE = storage.apiBaseUrl;
  }

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.url) {
    showState('notLinkedIn');
    return;
  }
  
  activeTabId = tab.id;
  activeTabUrl = tab.url;

  // Check if we were already polling for this tab's URL
  if (storage.activeLeadInfo && storage.activeLeadInfo.url === activeTabUrl) {
    currentLeadId = storage.activeLeadInfo.leadId;
    showState('loadingState');
    startPolling(currentLeadId);
    return;
  }

  const isLinkedIn = activeTabUrl.includes('linkedin.com/in/') || activeTabUrl.includes('linkedin.com/company/');
  const isCompanyWebsite = !activeTabUrl.includes('linkedin.com') && !activeTabUrl.includes('chrome://');

  if (!isLinkedIn && !isCompanyWebsite) {
    showState('notLinkedIn');
    return;
  }

  showState('readyState');
  $('statusDot').classList.add('active');

  // Inject content script on demand
  try {
    await chrome.scripting.executeScript({
      target: { tabId: activeTabId },
      files: ['content.js']
    });
    
    // Allow a tiny delay for script to initialize its listener
    await new Promise(r => setTimeout(r, 50));
    
    const response = await chrome.tabs.sendMessage(activeTabId, { action: 'EXTRACT_PROFILE' });
    if (response?.success) {
      prefillForm(response.data);
    }
  } catch (err) {
    console.warn('[LeadAI] Could not extract profile:', err);
    if (!isLinkedIn) {
      // Fallback for company website if script fails
      prefillForm({ type: 'company', company: tab.title, url: tab.url });
    }
  }
}

function prefillForm(data) {
  if (data.name) {
    $('inputName').value = data.name;
    $('profileName').textContent = data.name;
    $('profileAvatar').textContent = data.name[0]?.toUpperCase() || '?';
  }
  if (data.title) {
    $('inputTitle').value = data.title;
    $('profileTitle').textContent = data.title;
  }
  if (data.company) {
    $('inputCompany').value = data.company;
    $('profileCompany').textContent = data.company;
  }
  if (data.location) {
    $('inputLocation').value = data.location;
  }
}

// ── Enrich ────────────────────────────────────────────────────────────────────

$('enrichBtn')?.addEventListener('click', async () => {
  const payload = {
    name: $('inputName').value.trim(),
    title: $('inputTitle').value.trim(),
    company: $('inputCompany').value.trim(),
    location: $('inputLocation').value.trim(),
    url: activeTabUrl,
  };

  if (!payload.name && !payload.company) {
    alert('Please enter at least a name or company.');
    return;
  }

  $('enrichBtnText').textContent = 'Sending…';
  $('enrichSpinner').classList.remove('hidden');
  $('enrichBtn').disabled = true;

  try {
    const resp = await fetch(`${API_BASE}/api/v1/chrome/enrich`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) throw new Error(`API error: ${resp.status}`);
    const lead = await resp.json();
    currentLeadId = lead.id;

    // Save state to resume polling if popup closes
    await chrome.storage.local.set({
      activeLeadInfo: { leadId: currentLeadId, url: activeTabUrl }
    });

    showState('loadingState');
    animatePipelineStages(lead.pipeline_status);
    startPolling(lead.id);

  } catch (err) {
    $('enrichBtnText').textContent = 'Enrich Lead';
    $('enrichSpinner').classList.add('hidden');
    $('enrichBtn').disabled = false;
    alert(`Error: ${err.message}`);
  }
});

// ── Pipeline Stage Animation ──────────────────────────────────────────────────

const STATUS_STAGE_MAP = {
  SCRAPING_WEBSITE: 0,
  SCRAPING_LINKEDIN: 1,
  SCRAPING_NEWS: 2,
  SCORING_ICP: 3,
  GENERATING_EMAIL: 4,
};

function animatePipelineStages(status) {
  const currentIdx = STATUS_STAGE_MAP[status] ?? 0;
  const stages = document.querySelectorAll('.stage');

  stages.forEach((el, i) => {
    el.classList.remove('active', 'done', 'failed');
    if (i < currentIdx) el.classList.add('done');
    else if (i === currentIdx) el.classList.add('active');
  });
}

// ── Polling ───────────────────────────────────────────────────────────────────

function startPolling(leadId) {
  stopPolling();
  pollTimer = setInterval(async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/v1/leads/${leadId}`);
      if (!resp.ok) return;
      const lead = await resp.json();

      animatePipelineStages(lead.pipeline_status);

      if (['COMPLETED', 'PARTIAL_SUCCESS', 'FAILED'].includes(lead.pipeline_status)) {
        stopPolling();
        // Clear active polling state so it doesn't resume on next open
        chrome.storage.local.remove(['activeLeadInfo']);
        showResult(lead);
      }
    } catch (err) {
      console.warn('[LeadAI] Poll failed:', err);
    }
  }, POLL_INTERVAL_MS);
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

// ── Results ───────────────────────────────────────────────────────────────────

function showResult(lead) {
  showState('resultState');

  const score = lead.icp_score ?? 0;
  const scoreEl = $('resultScore');
  scoreEl.textContent = score;
  scoreEl.style.color = score >= 75 ? '#16A34A' : score >= 50 ? '#D97706' : '#DC2626';

  $('resultScoreLabel').textContent = score >= 75 ? 'Strong Fit' : score >= 50 ? 'Moderate Fit' : 'Weak Fit';

  const statusEl = $('resultStatus');
  const isPartial = lead.pipeline_status === 'PARTIAL_SUCCESS';
  const isFailed = lead.pipeline_status === 'FAILED';
  statusEl.textContent = isPartial ? 'Partial' : isFailed ? 'Failed' : 'Enriched';
  statusEl.style.background = isPartial ? '#FEF3C7' : isFailed ? '#FEE2E2' : '#DCFCE7';
  statusEl.style.color = isPartial ? '#D97706' : isFailed ? '#DC2626' : '#16A34A';

  const topSignal = lead.buying_signals?.[0];
  $('resultSignal').textContent = topSignal
    ? `💡 ${topSignal.description}`
    : 'No specific buying signals detected.';

  const emailBadge = $('resultEmailBadge');
  const variantsContainer = $('resultVariants');
  
  if (lead.email_drafts?.length > 0) {
    emailBadge.style.display = 'block';
    variantsContainer.style.display = 'block';
    variantsContainer.innerHTML = ''; // Clear previous

    // Render exactly 2 variants per requirements
    const draftsToShow = lead.email_drafts.slice(0, 2);
    
    draftsToShow.forEach((draft, idx) => {
      const draftEl = document.createElement('div');
      draftEl.style.border = '1px solid #E5E7EB';
      draftEl.style.borderRadius = '6px';
      draftEl.style.padding = '10px';
      draftEl.style.marginBottom = '8px';
      draftEl.style.background = '#fff';
      draftEl.style.position = 'relative';

      const label = document.createElement('div');
      label.textContent = `Variant ${idx + 1}: ${draft.variant || 'Standard'}`;
      label.style.fontWeight = '600';
      label.style.fontSize = '11px';
      label.style.marginBottom = '6px';
      label.style.color = '#4F46E5';

      const subject = document.createElement('div');
      subject.innerHTML = `<strong>Subj:</strong> ${draft.subject}`;
      subject.style.fontSize = '12px';
      subject.style.marginBottom = '4px';

      const bodyPreview = document.createElement('div');
      // Show just a short preview
      const bodyLines = draft.body.split('\n').filter(l => l.trim().length > 0);
      bodyPreview.textContent = bodyLines[0] || draft.body.substring(0, 50) + '...';
      bodyPreview.style.fontSize = '11px';
      bodyPreview.style.color = '#6B7280';
      bodyPreview.style.whiteSpace = 'nowrap';
      bodyPreview.style.overflow = 'hidden';
      bodyPreview.style.textOverflow = 'ellipsis';

      const copyBtn = document.createElement('button');
      copyBtn.textContent = 'Copy';
      copyBtn.style.position = 'absolute';
      copyBtn.style.top = '8px';
      copyBtn.style.right = '8px';
      copyBtn.style.background = '#EEF2FF';
      copyBtn.style.color = '#4F46E5';
      copyBtn.style.border = 'none';
      copyBtn.style.padding = '4px 8px';
      copyBtn.style.borderRadius = '4px';
      copyBtn.style.fontSize = '10px';
      copyBtn.style.cursor = 'pointer';
      copyBtn.style.fontWeight = '600';

      copyBtn.onclick = () => {
        const fullText = `Subject: ${draft.subject}\n\n${draft.body}`;
        navigator.clipboard.writeText(fullText).then(() => {
          copyBtn.textContent = 'Copied!';
          setTimeout(() => { copyBtn.textContent = 'Copy'; }, 2000);
        });
      };

      draftEl.appendChild(label);
      draftEl.appendChild(subject);
      draftEl.appendChild(bodyPreview);
      draftEl.appendChild(copyBtn);
      
      variantsContainer.appendChild(draftEl);
    });
  } else {
    emailBadge.style.display = 'none';
    variantsContainer.style.display = 'none';
  }

  $('openDashboardBtn').onclick = () => {
    // Determine appropriate dashboard url based on API_BASE
    const dashboardUrl = API_BASE.includes('localhost') 
      ? `http://localhost:3000/leads/${lead.id}`
      : `https://leadai-production.up.railway.app/leads/${lead.id}`;
    chrome.tabs.create({ url: dashboardUrl });
  };
}

$('resetBtn')?.addEventListener('click', () => {
  currentLeadId = null;
  chrome.storage.local.remove(['activeLeadInfo']);
  stopPolling();
  
  $('enrichBtnText').textContent = 'Enrich Lead';
  $('enrichSpinner').classList.add('hidden');
  $('enrichBtn').disabled = false;
  
  init();
});

// Start
init();
