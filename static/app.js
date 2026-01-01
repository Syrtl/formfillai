// Minimal frontend wiring - Sign In, Magic Link, Analyze PDF
// HUD (Heads-Up Display) for debugging without DevTools

// Create HUD element (hidden by default, show only with ?debug=1)
const hud = document.createElement('div');
hud.id = 'hud';
hud.style.cssText = `
    position: fixed;
    bottom: 20px;
    left: 20px;
    background: rgba(0, 0, 0, 0.9);
    color: #0f0;
    padding: 12px;
    border-radius: 6px;
    font-family: monospace;
    font-size: 11px;
    z-index: 10003;
    max-width: 400px;
    max-height: 300px;
    overflow-y: auto;
    word-break: break-word;
    pointer-events: none;
    display: none;
`;
document.body.appendChild(hud);

// Show HUD only if ?debug=1
const urlParams = new URLSearchParams(window.location.search);
const DEBUG = urlParams.get('debug') === '1';
if (DEBUG) {
    hud.style.display = 'block';
} else {
    hud.style.display = 'none';
}

// Hide other debug panels if not in debug mode
document.addEventListener('DOMContentLoaded', () => {
    if (!DEBUG) {
        const debugPanel = document.getElementById('debug-panel');
        const analyzeDebug = document.getElementById('analyze-debug');
        if (debugPanel) debugPanel.style.display = 'none';
        if (analyzeDebug) analyzeDebug.style.display = 'none';
    }
});

function hudLog(message) {
    const timestamp = new Date().toLocaleTimeString();
    const entry = document.createElement('div');
    entry.style.marginBottom = '4px';
    entry.textContent = `[${timestamp}] ${message}`;
    hud.appendChild(entry);
    hud.scrollTop = hud.scrollHeight;
    // Keep last 50 entries
    while (hud.children.length > 50) {
        hud.removeChild(hud.firstChild);
    }
    console.log('[HUD]', message);
}

// Show HUD on load (only if debug mode)
if (DEBUG) {
    hudLog('HUD: JS loaded');
}

// Capturing click listener to diagnose overlay issues
document.addEventListener('click', (e) => {
    const target = e.target;
    const targetInfo = `${target.tagName}${target.id ? '#' + target.id : ''}${target.className ? '.' + String(target.className).trim().replace(/\s+/g, '.') : ''}`;
    const topEl = document.elementFromPoint(e.clientX, e.clientY);
    const topElInfo = topEl ? `${topEl.tagName}${topEl.id ? '#' + topEl.id : ''}${topEl.className ? '.' + String(topEl.className).trim().replace(/\s+/g, '.') : ''}` : 'none';
    
    if (DEBUG) {
        hudLog(`Clicked: ${targetInfo} -> Top: ${topElInfo}`);
        
        // If clicks reach document but not the button, there's an overlay
        if (target !== topEl) {
            hudLog(`WARNING: Click intercepted! Target: ${targetInfo}, Top: ${topElInfo}`);
        }
    }
}, true); // capture phase

// Global state
let currentFields = [];
let currentPdfFile = null;
let currentPreviewUrl = null;
let currentDownloadUrl = null;
let currentUploadId = null;

// Auth UI update function
// Apply plan UI (hide pricing for Pro users)
function applyPlanUI(me) {
    const pricingSection = document.getElementById('pricing') || document.getElementById('plan-section');
    const upgradeBtn = document.getElementById('upgrade-btn');
    
    if (me && me.is_pro === true) {
        // Hide pricing section for Pro users
        if (pricingSection) {
            pricingSection.style.display = 'none';
        }
        // Hide upgrade button if exists
        if (upgradeBtn) {
            upgradeBtn.style.display = 'none';
        }
    } else {
        // Show pricing section for Free users
        if (pricingSection) {
            pricingSection.style.display = '';
        }
        if (upgradeBtn) {
            upgradeBtn.style.display = '';
        }
    }
}

async function updateAuthUI() {
    const authLoggedOut = document.getElementById('auth-logged-out');
    const authLoggedIn = document.getElementById('auth-logged-in');
    const userEmailEl = document.getElementById('user-email');
    const userPill = document.getElementById('user-pill');
    const userDropdown = document.getElementById('user-dropdown');
    const pricingSection = document.getElementById('pricing');
    const upgradeBtn = document.getElementById('upgrade-btn');
    const upgradeForm = document.getElementById('upgrade-form');
    const proStatusSection = document.getElementById('pro-status-section');
    
    try {
        const response = await fetch('/api/me', { credentials: 'include' });
        if (response.ok) {
            const data = await response.json();
            if (data.authenticated) {
                // Show logged in UI
                if (authLoggedOut) authLoggedOut.style.display = 'none';
                if (authLoggedIn) authLoggedIn.style.display = 'flex';
                if (userEmailEl) userEmailEl.textContent = data.email || '';
                
                // Update plan badge if exists
                const planBadge = document.getElementById('plan-badge');
                if (planBadge) {
                    if (data.is_pro || data.plan === 'pro') {
                        planBadge.textContent = 'PRO';
                        planBadge.className = 'plan-badge pro';
                        planBadge.style.display = 'inline';
                    } else {
                        planBadge.style.display = 'none';
                    }
                }
                
                // Apply plan UI (hide pricing for Pro users)
                applyPlanUI(data);
                
                if (DEBUG) hudLog(`Auth: authenticated as ${data.email}, plan: ${data.plan || 'free'}, is_pro: ${data.is_pro || false}`);
            } else {
                // Show logged out UI
                if (authLoggedOut) authLoggedOut.style.display = 'block';
                if (authLoggedIn) authLoggedIn.style.display = 'none';
                if (userDropdown) userDropdown.classList.remove('open');
                if (userPill) userPill.classList.remove('open');
                // Show pricing for non-authenticated users
                if (pricingSection) pricingSection.style.display = 'block';
                if (upgradeBtn) upgradeBtn.style.display = 'block';
                if (upgradeForm) upgradeForm.style.display = 'block';
                if (proStatusSection) proStatusSection.style.display = 'none';
                if (DEBUG) hudLog('Auth: not authenticated');
            }
        } else {
            // Not authenticated
            if (authLoggedOut) authLoggedOut.style.display = 'block';
            if (authLoggedIn) authLoggedIn.style.display = 'none';
            if (userDropdown) userDropdown.classList.remove('open');
            if (userPill) userPill.classList.remove('open');
            // Show pricing for non-authenticated users
            if (pricingSection) pricingSection.style.display = 'block';
            if (upgradeBtn) upgradeBtn.style.display = 'block';
            if (upgradeForm) upgradeForm.style.display = 'block';
            if (proStatusSection) proStatusSection.style.display = 'none';
            if (DEBUG) hudLog('Auth: not authenticated (error)');
        }
    } catch (err) {
        if (DEBUG) hudLog(`Auth check error: ${err.message}`);
    }
}

// Wait for DOM
document.addEventListener('DOMContentLoaded', () => {
    if (DEBUG) {
        hudLog('DOMContentLoaded fired');
    }
    
    // Check auth on load
    updateAuthUI();
    
    // Handle auth_success=1
    if (urlParams.get('auth_success') === '1') {
        updateAuthUI().then(() => {
            if (typeof showToast === 'function') {
                showToast('Signed in!', 'success');
            }
            // Remove query params
            const newUrl = window.location.pathname;
            window.history.replaceState({}, '', newUrl);
        });
    }
    
    // Bind profile modal handlers (primary method)
    bindProfileModalHandlers();
    
    // Get required elements
    const signInBtn = document.getElementById('signInBtn');
    const signInModal = document.getElementById('signInModal');
    const signInEmailInput = document.getElementById('signInEmail');
    const sendMagicBtn = document.getElementById('sendMagicBtn');
    const analyzeBtn = document.getElementById('analyzeBtn');
    const pdfFileInput = document.getElementById('pdfFileInput');
    const signInStatus = document.getElementById('sign-in-status');
    const uploadForm = document.getElementById('upload-form');
    
    // Check for missing elements
    if (DEBUG) {
        if (!signInBtn) hudLog('ERROR: Missing element: signInBtn');
        if (!signInModal) hudLog('ERROR: Missing element: signInModal');
        if (!signInEmailInput) hudLog('ERROR: Missing element: signInEmail');
        if (!sendMagicBtn) hudLog('ERROR: Missing element: sendMagicBtn');
        if (!analyzeBtn) hudLog('ERROR: Missing element: analyzeBtn');
        if (!pdfFileInput) hudLog('ERROR: Missing element: pdfFileInput');
    }
    
    // Sign In button -> open modal (use .active class)
    if (signInBtn && signInModal && signInEmailInput) {
        signInBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (DEBUG) hudLog('Sign In clicked');
            try {
                signInModal.classList.add('active');
                signInEmailInput.focus();
                if (DEBUG) hudLog('Modal opened');
            } catch (err) {
                if (DEBUG) hudLog(`ERROR opening modal: ${err.message}`);
            }
        });
        if (DEBUG) hudLog('Sign In handler attached');
    }
    
    // Close modal handlers
    const closeSignInBtn = document.getElementById('closeSignInBtn');
    if (closeSignInBtn && signInModal) {
        closeSignInBtn.addEventListener('click', () => {
            signInModal.classList.remove('active');
            if (DEBUG) hudLog('Modal closed');
        });
    }
    
    // Close modal on outside click
    if (signInModal) {
        signInModal.addEventListener('click', (e) => {
            if (e.target === signInModal) {
                signInModal.classList.remove('active');
                if (DEBUG) hudLog('Modal closed (outside click)');
            }
        });
    }
    
    // Send magic link button -> POST /auth/send-magic-link
    if (sendMagicBtn && signInEmailInput) {
        sendMagicBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (DEBUG) hudLog('Send magic link clicked');
            
            const email = signInEmailInput.value.trim();
            if (!email) {
                if (signInStatus) {
                    signInStatus.innerHTML = '<div style="color: var(--error); margin-top: 0.5rem;">Please enter an email address.</div>';
                }
                return;
            }
            
            sendMagicBtn.disabled = true;
            sendMagicBtn.textContent = 'Sending...';
            if (signInStatus) signInStatus.innerHTML = '';
            
            try {
                const formData = new FormData();
                formData.append('email', email);
                
                if (DEBUG) hudLog(`POST /auth/send-magic-link (email: ${email})`);
                const response = await fetch('/auth/send-magic-link', {
                    method: 'POST',
                    body: formData,
                    credentials: 'include'
                });
                
                const responseText = await response.text();
                if (DEBUG) {
                    const responsePreview = responseText.substring(0, 120);
                    hudLog(`POST /auth/send-magic-link -> status ${response.status} + ${responsePreview}`);
                }
                
                if (response.ok) {
                    if (DEBUG) hudLog('Magic link sent successfully');
                    if (signInStatus) {
                        signInStatus.innerHTML = '<div style="color: #16a34a; margin-top: 0.5rem; padding: 0.75rem; background: rgba(22, 163, 74, 0.15); border: 1px solid rgba(22, 163, 74, 0.3); border-radius: 6px; font-weight: 500;">Magic link sent. Check your email.</div>';
                    }
                    if (typeof showToast === 'function') {
                        showToast('Magic link sent. Check your email.', 'success');
                    }
                } else {
                    let errorMsg = 'Failed to send magic link';
                    try {
                        const errorData = JSON.parse(responseText);
                        errorMsg = errorData.detail || errorMsg;
                    } catch (e) {
                        errorMsg = responseText.substring(0, 100) || errorMsg;
                    }
                    if (DEBUG) hudLog(`ERROR: Magic link send failed: ${response.status}`);
                    if (signInStatus) {
                        signInStatus.innerHTML = `<div style="color: var(--error); margin-top: 0.5rem; padding: 0.5rem; background: rgba(220, 38, 38, 0.1); border-radius: 4px;">${errorMsg}</div>`;
                    }
                    if (typeof showToast === 'function') {
                        showToast(errorMsg, 'error');
                    }
                }
            } catch (err) {
                if (DEBUG) hudLog(`ERROR: ${err.message}`);
                if (signInStatus) {
                    signInStatus.innerHTML = `<div style="color: var(--error); margin-top: 0.5rem; padding: 0.5rem; background: rgba(220, 38, 38, 0.1); border-radius: 4px;">Failed to send magic link: ${err.message}</div>`;
                }
                if (typeof showToast === 'function') {
                    showToast('Failed to send magic link', 'error');
                }
            } finally {
                sendMagicBtn.disabled = false;
                sendMagicBtn.textContent = 'Send magic link';
            }
        });
        if (DEBUG) hudLog('Send magic link handler attached');
    }
    
    // User menu dropdown toggle
    const userPill = document.getElementById('user-pill');
    const userDropdown = document.getElementById('user-dropdown');
    if (userPill && userDropdown) {
        userPill.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            userPill.classList.toggle('open');
            userDropdown.classList.toggle('open');
        });
        
        // Close dropdown on outside click
        document.addEventListener('click', (e) => {
            if (userPill && userDropdown && !userPill.contains(e.target) && !userDropdown.contains(e.target)) {
                userPill.classList.remove('open');
                userDropdown.classList.remove('open');
            }
        });
        
        // Close dropdown on ESC
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && userDropdown && userDropdown.classList.contains('open')) {
                userPill.classList.remove('open');
                userDropdown.classList.remove('open');
            }
        });
    }
    
    // Sign out handler
    const logoutBtn = document.getElementById('logout-btn') || document.getElementById('logout-menu-item');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (DEBUG) hudLog('Logout clicked');
            
            // Close dropdown
            if (userPill) userPill.classList.remove('open');
            if (userDropdown) userDropdown.classList.remove('open');
            
            try {
                const response = await fetch('/auth/logout', {
                    method: 'POST',
                    credentials: 'include'
                });
                if (DEBUG) hudLog(`POST /auth/logout -> status ${response.status}`);
                await updateAuthUI();
                if (typeof showToast === 'function') {
                    showToast('Signed out', 'success');
                }
            } catch (err) {
                if (DEBUG) hudLog(`Logout error: ${err.message}`);
                await updateAuthUI(); // Still update UI even on error
            }
        });
    }
    
    // Analyze PDF button -> POST /fields
    if (analyzeBtn && pdfFileInput) {
        analyzeBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (DEBUG) hudLog('Analyze clicked');
            
            const file = pdfFileInput.files[0];
            if (!file) {
                if (DEBUG) hudLog('ERROR: No file selected');
                if (typeof showToast === 'function') {
                    showToast('Please select a PDF file first', 'error');
                }
                return;
            }
            
            // Immediately show feedback
            if (DEBUG) hudLog(`POST /fields (file: ${file.name}, size: ${file.size})`);
            if (typeof showToast === 'function') {
                showToast('Uploading...', 'success');
            }
            analyzeBtn.disabled = true;
            analyzeBtn.textContent = 'Analyzing...';
            
            try {
                const formData = new FormData();
                formData.append('pdf_file', file);
                
                const response = await fetch('/fields', {
                    method: 'POST',
                    body: formData,
                    credentials: 'include'
                });
                
                const responseText = await response.text();
                if (DEBUG) {
                    const responsePreview = responseText.substring(0, 120);
                    hudLog(`POST /fields -> status ${response.status} + ${responsePreview}`);
                }
                
                if (response.status === 401) {
                    if (DEBUG) hudLog('ERROR: Not signed in (401)');
                    if (typeof showToast === 'function') {
                        showToast('Please sign in first', 'error');
                    }
                    return;
                }
                
                if (!response.ok) {
                    if (DEBUG) hudLog(`ERROR: Analyze failed: ${response.status}`);
                    if (typeof showToast === 'function') {
                        showToast('Failed to analyze PDF', 'error');
                    }
                    return;
                }
                
                // Success - parse response
                let responseData;
                try {
                    responseData = JSON.parse(responseText);
                } catch (parseErr) {
                    if (DEBUG) hudLog(`ERROR: Failed to parse response: ${parseErr.message}`);
                    return;
                }
                
                const fields = responseData.fields || [];
                const fieldCount = fields.length;
                
                // Store fields globally for Fill submission
                currentFields = fields;
                currentPdfFile = file;
                
                if (DEBUG) hudLog(`Success: Fields found: ${fieldCount}`);
                
                if (fieldCount === 0) {
                    if (typeof showToast === 'function') {
                        showToast('No fillable fields found in PDF', 'error');
                    }
                    return;
                }
                
                // Show fields count
                if (typeof showToast === 'function') {
                    showToast(`Fields found: ${fieldCount}`, 'success');
                }
                
                // Show preview if available
                if (responseData.preview_url) {
                    const previewIframe = document.getElementById('preview-iframe');
                    const previewContainer = document.getElementById('preview-container');
                    const previewLink = document.getElementById('preview-link');
                    
                    if (previewIframe && previewContainer) {
                        const previewUrl = `${responseData.preview_url}?t=${Date.now()}`;
                        previewIframe.src = previewUrl;
                        previewContainer.style.display = 'block';
                        previewContainer.setAttribute('data-has-preview', 'true');
                        previewContainer.classList.add('has-preview');
                        
                        // Store preview URL for download
                        currentPreviewUrl = responseData.preview_url;
                        if (responseData.upload_id) {
                            currentUploadId = responseData.upload_id;
                        }
                        
                        if (DEBUG) hudLog(`Preview iframe set: ${previewUrl}`);
                        
                        // Fallback link
                        if (previewLink) {
                            previewLink.href = responseData.preview_url;
                            previewLink.textContent = 'Open preview in new tab';
                        }
                    } else {
                        if (DEBUG) hudLog('WARNING: Preview elements not found');
                    }
                }
                
                // Render fields
                renderFields(fields);
                if (DEBUG) hudLog('Fields rendered');
                
            } catch (err) {
                if (DEBUG) hudLog(`ERROR: ${err.message}`);
                if (typeof showToast === 'function') {
                    showToast('Failed to analyze PDF', 'error');
                }
            } finally {
                analyzeBtn.disabled = false;
                analyzeBtn.textContent = 'Analyze PDF';
            }
        });
        if (DEBUG) hudLog('Analyze PDF handler attached');
    }
    
    // Intercept Fill My Form submission
    if (uploadForm) {
        uploadForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (DEBUG) hudLog('Fill My Form submitted');
            
            if (!currentPdfFile) {
                if (typeof showToast === 'function') {
                    showToast('Please analyze a PDF first', 'error');
                }
                return;
            }
            
            // Collect field values
            const fieldValues = {};
            let hasAnyValue = false;
            
            currentFields.forEach((field) => {
                const input = document.getElementById(`field_${field.name}`);
                if (input) {
                    let value;
                    if (input.type === 'checkbox') {
                        value = input.checked ? 'true' : '';
                    } else {
                        value = input.value.trim();
                    }
                    if (value) {
                        fieldValues[field.name] = value;
                        hasAnyValue = true;
                    }
                }
            });
            
            if (!hasAnyValue) {
                if (typeof showToast === 'function') {
                    showToast('Please fill at least one field', 'error');
                }
                return;
            }
            
            // Build FormData
            const formData = new FormData();
            formData.append('pdf_file', currentPdfFile);
            formData.append('fields_json', JSON.stringify(fieldValues));
            
            const submitBtn = document.getElementById('submit-btn');
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.textContent = 'Filling...';
            }
            
            try {
                if (DEBUG) hudLog(`POST /fill with ${Object.keys(fieldValues).length} fields`);
                const response = await fetch('/fill', {
                    method: 'POST',
                    body: formData,
                    credentials: 'include'
                });
                
                const responseText = await response.text();
                if (DEBUG) {
                    const responsePreview = responseText.substring(0, 120);
                    hudLog(`POST /fill -> status ${response.status} + ${responsePreview}`);
                }
                
                if (!response.ok) {
                    let errorMsg = 'Failed to fill form';
                    try {
                        const errorData = JSON.parse(responseText);
                        errorMsg = errorData.detail || errorMsg;
                    } catch (e) {
                        errorMsg = responseText.substring(0, 100) || errorMsg;
                    }
                    if (typeof showToast === 'function') {
                        showToast(errorMsg, 'error');
                    }
                    return;
                }
                
                // Success - update preview
                let responseData;
                try {
                    responseData = JSON.parse(responseText);
                } catch (parseErr) {
                    if (DEBUG) hudLog(`ERROR: Failed to parse response: ${parseErr.message}`);
                    return;
                }
                
                if (responseData.preview_url) {
                    const previewIframe = document.getElementById('preview-iframe');
                    const previewContainer = document.getElementById('preview-container');
                    
                    if (previewIframe && previewContainer) {
                        const previewUrl = `${responseData.preview_url}?t=${Date.now()}`;
                        previewIframe.src = previewUrl;
                        previewContainer.style.display = 'block';
                        previewContainer.setAttribute('data-has-preview', 'true');
                        previewContainer.classList.add('has-preview');
                        
                        // Store download URL if available (filled PDF)
                        if (responseData.download_url) {
                            currentDownloadUrl = responseData.download_url;
                        }
                        // Also store preview URL as fallback
                        currentPreviewUrl = responseData.preview_url;
                        
                        if (DEBUG) hudLog(`Preview updated: ${previewUrl}`);
                    }
                }
                
                if (typeof showToast === 'function') {
                    showToast('Form filled successfully!', 'success');
                }
            } catch (err) {
                if (DEBUG) hudLog(`ERROR: ${err.message}`);
                if (typeof showToast === 'function') {
                    showToast('Failed to fill form', 'error');
                }
            } finally {
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.textContent = 'Fill My Form';
                }
            }
        });
        if (DEBUG) hudLog('Fill form handler attached');
    }
    
    // Download PDF button
    const downloadBtn = document.getElementById('download-btn');
    if (downloadBtn) {
        downloadBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (DEBUG) hudLog('Download clicked');
            
            let downloadUrl = null;
            if (currentDownloadUrl) {
                downloadUrl = currentDownloadUrl;
            } else if (currentUploadId) {
                downloadUrl = `/download-upload/${currentUploadId}`;
            } else if (currentPreviewUrl) {
                // Extract file_id from preview URL if it's /preview/{file_id}
                const match = currentPreviewUrl.match(/\/preview\/([^\/\?]+)/);
                if (match) {
                    downloadUrl = `/download/${match[1]}`;
                }
            }
            
            if (downloadUrl) {
                window.open(downloadUrl, '_blank');
                if (DEBUG) hudLog(`Download: ${downloadUrl}`);
            } else {
                if (typeof showToast === 'function') {
                    showToast('Nothing to download yet', 'error');
                }
                if (DEBUG) hudLog('WARNING: No download URL available');
            }
        });
        if (DEBUG) hudLog('Download button handler attached');
    }
    
    // Fullscreen button (toggle)
    const fullscreenBtn = document.getElementById('fullscreen-btn');
    const previewContainerEl = document.getElementById('preview-container');
    const previewIframeEl = document.getElementById('preview-iframe');
    if (fullscreenBtn) {
        // Update button text based on fullscreen state
        function updateFullscreenButton() {
            const isFs = !!document.fullscreenElement;
            if (fullscreenBtn) {
                fullscreenBtn.textContent = isFs ? 'Exit Fullscreen' : 'Fullscreen';
            }
        }
        
        // Listen for fullscreen changes (including ESC)
        document.addEventListener('fullscreenchange', updateFullscreenButton);
        
        fullscreenBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (DEBUG) hudLog('Fullscreen clicked');
            
            try {
                // If already in fullscreen, exit
                if (document.fullscreenElement) {
                    await document.exitFullscreen();
                    if (DEBUG) hudLog('Exited fullscreen');
                    return;
                }
                
                // Otherwise, enter fullscreen
                const previewWrapper = document.getElementById('preview-wrapper');
                if (previewWrapper && previewWrapper.requestFullscreen) {
                    await previewWrapper.requestFullscreen();
                } else if (previewContainerEl && previewContainerEl.requestFullscreen) {
                    await previewContainerEl.requestFullscreen();
                } else if (previewIframeEl && previewIframeEl.requestFullscreen) {
                    await previewIframeEl.requestFullscreen();
                } else {
                    if (typeof showToast === 'function') {
                        showToast('Fullscreen not supported in this browser', 'error');
                    }
                    if (DEBUG) hudLog('WARNING: Fullscreen API not available');
                }
            } catch (err) {
                if (typeof showToast === 'function') {
                    showToast('Failed to toggle fullscreen', 'error');
                }
                if (DEBUG) hudLog(`Fullscreen error: ${err.message}`);
            }
        });
        if (DEBUG) hudLog('Fullscreen button handler attached');
    }
    
    // Profiles menu item - open modal
    const profilesMenuItem = getEl('profiles-menu-item');
    if (profilesMenuItem) {
        profilesMenuItem.addEventListener('click', async (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (DEBUG) hudLog('Profiles menu item clicked');
            
            // Close dropdown first
            const userPill = getEl('user-pill');
            const userDropdown = getEl('user-dropdown');
            if (userPill) userPill.classList.remove('open');
            if (userDropdown) userDropdown.classList.remove('open');
            
            // Open profile modal
            await openProfileModal();
        });
        if (DEBUG) hudLog('Profiles menu item handler attached');
    }
    
    // Close profile modal on outside click
    const profileModal = getEl('profileModal');
    if (profileModal) {
        profileModal.addEventListener('click', (e) => {
            if (e.target === profileModal) {
                profileModal.classList.remove('active');
            }
        });
    }
    
    // Close profile modal on ESC
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const profileModal = getEl('profileModal');
            if (profileModal && profileModal.classList.contains('active')) {
                profileModal.classList.remove('active');
            }
        }
    });
    
    // Load profile data function
    async function loadProfileData() {
        // Wiring check - verify all required elements exist
        const profileModal = getEl('profileModal');
        const profileEmailCurrent = getEl('profileEmailCurrent');
        const profileEmailNew = getEl('profileEmailNew');
        const profileFullName = getEl('profileFullName');
        const profilePhone = getEl('profilePhone');
        const profileStatus = getEl('profileStatus');
        const profilePlanStatus = getEl('profilePlanStatus');
        
        // Check all required elements
        const missing = [];
        if (!profileModal) missing.push('profileModal');
        if (!profileEmailCurrent) missing.push('profileEmailCurrent');
        if (!profileEmailNew) missing.push('profileEmailNew');
        if (!profileFullName) missing.push('profileFullName');
        if (!profilePhone) missing.push('profilePhone');
        if (!saveProfileBtn) missing.push('saveProfileBtn');
        if (!saveEmailBtn) missing.push('saveEmailBtn');
        if (!profileStatus) missing.push('profileStatus');
        if (!profilePlanStatus) missing.push('profilePlanStatus');
        if (!profilePlanActions) missing.push('profile-plan-actions');
        
        if (missing.length > 0) {
            if (DEBUG) {
                const errorMsg = `WIRING ERROR: Missing ${missing.join(', ')}`;
                if (profileStatus) {
                    profileStatus.textContent = errorMsg;
                    profileStatus.style.color = '#ef4444';
                }
                hudLog(errorMsg);
            } else {
                // In production, show user-friendly message
                if (profileStatus) {
                    profileStatus.textContent = 'Something went wrong. Please refresh.';
                    profileStatus.style.color = '#ef4444';
                }
            }
            return;
        }
        
        // Clear status
        if (profileStatus) {
            profileStatus.textContent = '';
        }
        
        try {
            const response = await fetch('/api/me', { credentials: 'include' });
            if (response.ok) {
                const data = await response.json();
                if (data.authenticated) {
                    // Set account info
                    if (profileEmailCurrent) profileEmailCurrent.value = data.email || '';
                    if (profileEmailNew) profileEmailNew.value = data.email || '';
                    if (profileFullName) profileFullName.value = data.full_name || '';
                    if (profilePhone) profilePhone.value = data.phone || '';
                    
                    // Set plan status
                    const isPro = data.is_pro || data.plan === 'pro';
                    if (profilePlanStatus) {
                        profilePlanStatus.textContent = isPro ? 'Pro' : 'Free';
                        profilePlanStatus.style.color = isPro ? 'var(--primary)' : 'var(--text)';
                    }
                    
                    // Apply plan actions
                    applyPlanActions(data);
                }
            }
        } catch (err) {
            if (DEBUG) hudLog(`Profile load error: ${err.message}`);
            if (profileStatus) {
                profileStatus.textContent = 'Failed to load profile data. Please refresh.';
                profileStatus.style.color = '#ef4444';
            }
        }
    }
    
    // Helper function to get element by ID
    function getEl(id) {
        return document.getElementById(id);
    }
    
    // Helper function for profile status
    function setProfileStatus(msg, type) {
        const profileStatus = getEl('profileStatus');
        if (!profileStatus) return;
        
        if (!msg) {
            profileStatus.textContent = '';
            return;
        }
        
        let color = '#666'; // default gray for info
        if (type === 'success') {
            color = '#16a34a'; // green
        } else if (type === 'error') {
            color = '#ef4444'; // red
        }
        
        profileStatus.textContent = msg;
        profileStatus.style.color = color;
    }
    
    // Helper to parse response based on content-type
    async function parseResponse(response) {
        const contentType = response.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
            return await response.json();
        } else {
            return { detail: await response.text() };
        }
    }
    
    // Open profile modal function
    async function openProfileModal() {
        const profileModal = getEl('profileModal');
        if (profileModal) {
            profileModal.classList.add('active');
            await loadProfileData();
        }
    }
    
    // Apply plan actions based on user data
    function applyPlanActions(me) {
        const profilePlanActions = getEl('profile-plan-actions');
        const manageSubscriptionBtn = getEl('manageSubscriptionBtn');
        const upgradeToProBtn = getEl('upgradeToProBtn');
        
        if (!profilePlanActions) return;
        
        // Hide all buttons first
        if (manageSubscriptionBtn) manageSubscriptionBtn.style.display = 'none';
        if (upgradeToProBtn) upgradeToProBtn.style.display = 'none';
        
        // Clear any helper text
        const existingText = profilePlanActions.querySelector('p');
        if (existingText) existingText.remove();
        
        const isPro = me.is_pro || me.plan === 'pro';
        
        if (isPro) {
            const stripeCustomerId = me.stripe_customer_id;
            const stripeEnabled = me.stripe_enabled;
            
            if (stripeEnabled && stripeCustomerId) {
                // Pro user with Stripe customer - show Manage Subscription
                if (manageSubscriptionBtn) {
                    manageSubscriptionBtn.style.display = 'block';
                    manageSubscriptionBtn.disabled = false;
                    manageSubscriptionBtn.textContent = 'Manage Subscription';
                    manageSubscriptionBtn.className = 'primary';
                    manageSubscriptionBtn.style.opacity = '';
                    manageSubscriptionBtn.style.cursor = '';
                }
                const helperText = document.createElement('p');
                helperText.style.cssText = 'font-size: 0.875rem; color: var(--text-muted); margin-top: 0.5rem;';
                helperText.textContent = 'Manage your subscription, payment methods, and billing in the Stripe portal.';
                profilePlanActions.appendChild(helperText);
            } else {
                // Pro user without Stripe - show disabled button
                if (manageSubscriptionBtn) {
                    manageSubscriptionBtn.style.display = 'block';
                    manageSubscriptionBtn.disabled = true;
                    manageSubscriptionBtn.textContent = 'Billing portal unavailable';
                    manageSubscriptionBtn.className = 'secondary';
                    manageSubscriptionBtn.style.opacity = '0.6';
                    manageSubscriptionBtn.style.cursor = 'not-allowed';
                }
                const helperText = document.createElement('p');
                helperText.style.cssText = 'font-size: 0.875rem; color: var(--text-muted); margin-top: 0.5rem;';
                helperText.textContent = 'No Stripe customer ID for this account.';
                profilePlanActions.appendChild(helperText);
            }
        } else {
            // Free user - show Upgrade to Pro
            if (upgradeToProBtn) {
                upgradeToProBtn.style.display = 'block';
                upgradeToProBtn.disabled = !me.stripe_enabled;
                if (!me.stripe_enabled) {
                    upgradeToProBtn.className = 'secondary';
                    upgradeToProBtn.style.opacity = '0.6';
                    upgradeToProBtn.style.cursor = 'not-allowed';
                    const helperText = document.createElement('p');
                    helperText.style.cssText = 'font-size: 0.875rem; color: var(--text-muted); margin-top: 0.5rem;';
                    helperText.textContent = 'Payments are not configured.';
                    profilePlanActions.appendChild(helperText);
                }
            }
        }
    }
    
    // Bind profile modal handlers (primary method)
    function bindProfileModalHandlers() {
        const saveProfileBtn = getEl('saveProfileBtn');
        const saveEmailBtn = getEl('saveEmailBtn');
        const manageSubscriptionBtn = getEl('manageSubscriptionBtn');
        const upgradeToProBtn = getEl('upgradeToProBtn');
        const closeProfileBtn = getEl('closeProfileBtn');
        const profileModal = getEl('profileModal');
        
        // Save Profile handler
        if (saveProfileBtn) {
            saveProfileBtn.addEventListener('click', async (e) => {
                e.preventDefault();
                e.stopPropagation();
                
                const profileFullName = getEl('profileFullName');
                const profilePhone = getEl('profilePhone');
                
                if (!profileFullName || !profilePhone) {
                    setProfileStatus('Something went wrong. Please refresh.', 'error');
                    return;
                }
            
            const fullName = profileFullName.value.trim();
            const phone = profilePhone.value.trim();
            
            setProfileStatus('Saving profile…', 'info');
            
            try {
                saveProfileBtn.disabled = true;
                saveProfileBtn.textContent = 'Saving…';
                
                const response = await fetch('/api/profile/update', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify({ full_name: fullName, phone: phone })
                });
                
                const data = await parseResponse(response);
                
                if (response.ok) {
                    setProfileStatus('Saved ✅', 'success');
                    // Verify by calling /api/me and repopulate inputs
                    try {
                        const verifyResponse = await fetch('/api/me', { credentials: 'include' });
                        if (verifyResponse.ok) {
                            const verifyData = await verifyResponse.json();
                            if (verifyData.authenticated) {
                                // Repopulate inputs from verified data
                                if (profileFullName) profileFullName.value = verifyData.full_name || '';
                                if (profilePhone) profilePhone.value = verifyData.phone || '';
                            }
                        }
                    } catch (verifyErr) {
                        // Non-critical, just log
                        if (DEBUG) hudLog(`Verify error: ${verifyErr.message}`);
                    }
                } else {
                    const errorDetail = data.detail || 'Failed to update profile';
                    // Show first 200 chars of error
                    const errorPreview = errorDetail.substring(0, 200);
                    setProfileStatus(`Error (${response.status}): ${errorPreview}`, 'error');
                }
            } catch (err) {
                setProfileStatus(`Error: ${err.message}`, 'error');
                if (DEBUG) hudLog(`Save profile error: ${err.message}`);
            } finally {
                saveProfileBtn.disabled = false;
                saveProfileBtn.textContent = 'Save Changes';
            }
            });
            if (DEBUG) hudLog('Save profile button handler attached');
        }
        
        // Save Email handler
        if (saveEmailBtn) {
            saveEmailBtn.addEventListener('click', async (e) => {
                e.preventDefault();
                e.stopPropagation();
                
                const profileEmailNew = getEl('profileEmailNew');
                
                if (!profileEmailNew) {
                    setProfileStatus('Something went wrong. Please refresh.', 'error');
                    return;
                }
            
            const newEmail = profileEmailNew.value.trim();
            
            if (!newEmail) {
                setProfileStatus('Email cannot be empty', 'error');
                return;
            }
            
            setProfileStatus('Updating email…', 'info');
            
            try {
                saveEmailBtn.disabled = true;
                saveEmailBtn.textContent = 'Saving…';
                
                const response = await fetch('/api/profile/update-email', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify({ new_email: newEmail, email: newEmail })
                });
                
                const data = await parseResponse(response);
                
                if (response.ok) {
                    setProfileStatus('Email updated ✅', 'success');
                    // Update header email immediately
                    const userEmailEl = document.getElementById('user-email');
                    if (userEmailEl) {
                        userEmailEl.textContent = data.email || newEmail;
                    }
                    // Update profileEmailCurrent display
                    const profileEmailCurrent = document.getElementById('profileEmailCurrent');
                    if (profileEmailCurrent) {
                        profileEmailCurrent.value = data.email || newEmail;
                    }
                    // Also update profileEmailNew
                    if (profileEmailNew) {
                        profileEmailNew.value = data.email || newEmail;
                    }
                    // Refresh auth UI
                    await updateAuthUI();
                } else {
                    const errorDetail = data.detail || 'Failed to update email';
                    
                    // Handle specific status codes
                    if (response.status === 429) {
                        // Cooldown - show exact message with days remaining
                        setProfileStatus(errorDetail, 'error');
                    } else if (response.status === 409) {
                        // Email already taken
                        setProfileStatus(errorDetail, 'error');
                    } else {
                        // Other errors
                        setProfileStatus(`Error (${response.status}): ${errorDetail}`, 'error');
                    }
                }
            } catch (err) {
                setProfileStatus(`Error: ${err.message}`, 'error');
                if (DEBUG) hudLog(`Save email error: ${err.message}`);
            } finally {
                saveEmailBtn.disabled = false;
                saveEmailBtn.textContent = 'Save Email';
            }
        });
        if (DEBUG) hudLog('Save email button handler attached');
    }
    
    if (DEBUG) hudLog('All handlers attached');
});

// Human-friendly field label function
function prettyLabel(name) {
    const n = String(name || '').trim();
    if (!n) return '';
    
    // Normalize: lowercase, remove non-alphanumeric
    const key = n.toLowerCase().replace(/[^a-z0-9]/g, '');
    
    // Special-case common abbreviations
    const map = {
        'dob': 'Date of Birth',
        'dateofbirth': 'Date of Birth',
        'birthdate': 'Date of Birth',
        'birth_date': 'Date of Birth',
        'phonenumber': 'Phone Number',
        'phonenum': 'Phone Number',
        'phone': 'Phone Number',
        'tel': 'Phone Number',
        'zipcode': 'ZIP Code',
        'zip': 'ZIP Code',
        'zip_code': 'ZIP Code',
        'ssn': 'SSN',
        'socialsecuritynumber': 'SSN',
        'firstname': 'First Name',
        'fname': 'First Name',
        'first_name': 'First Name',
        'lastname': 'Last Name',
        'lname': 'Last Name',
        'last_name': 'Last Name',
        'addressline1': 'Address Line 1',
        'addr1': 'Address Line 1',
        'address1': 'Address Line 1',
        'address_line1': 'Address Line 1',
        'addressline2': 'Address Line 2',
        'addr2': 'Address Line 2',
        'address2': 'Address Line 2',
        'address_line2': 'Address Line 2',
        'email': 'Email',
        'emailaddress': 'Email',
        'email_address': 'Email'
    };
    
    if (map[key]) {
        return map[key];
    }
    
    // Fallback: split snake_case/camelCase and capitalize
    return n
        .replace(/_/g, ' ')
        .replace(/([a-z])([A-Z])/g, '$1 $2')
        .replace(/\s+/g, ' ')
        .trim()
        .split(' ')
        .map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
        .join(' ');
}

// Implement renderFields function (single source of truth)
function renderFields(fields) {
    const fieldsContainer = document.getElementById('fields-container');
    const fieldsList = document.getElementById('fields-list');
    const fieldsSummary = document.getElementById('fields-summary');
    const submitBtn = document.getElementById('submit-btn');
    
    if (!fieldsContainer || !fieldsList || !fieldsSummary) {
        if (DEBUG) hudLog('ERROR: Missing fields container elements');
        return;
    }
    
    // Show fields container
    fieldsContainer.style.display = 'block';
    
    // Update summary
    const fieldCount = fields.length;
    fieldsSummary.textContent = `Fields found: ${fieldCount}`;
    
    // Clear existing fields
    fieldsList.innerHTML = '';
    
    // Render each field
    fields.forEach((field) => {
        const fieldName = field.name || '';
        // Use field.label from PDF (exact match), fallback to field.name
        const fieldLabel = field.label || fieldName;
        const fieldType = field.type || 'text';
        const isRequired = field.required || false;
        const fieldValue = field.value || '';
        const options = field.options || [];
        
        // Create field wrapper
        const fieldDiv = document.createElement('div');
        fieldDiv.style.marginBottom = '1rem';
        
        // Create label
        const label = document.createElement('label');
        label.setAttribute('for', `field_${fieldName}`);
        label.textContent = fieldLabel + (isRequired ? ' *' : '');
        label.style.display = 'block';
        label.style.marginBottom = '0.25rem';
        label.style.fontWeight = '600';
        fieldDiv.appendChild(label);
        
        // Create input based on type
        let input;
        if (fieldType === 'checkbox') {
            input = document.createElement('input');
            input.type = 'checkbox';
            input.id = `field_${fieldName}`;
            input.name = fieldName;
            if (fieldValue === 'true' || fieldValue === true) {
                input.checked = true;
            }
        } else if (fieldType === 'choice' && options.length > 0) {
            input = document.createElement('select');
            input.id = `field_${fieldName}`;
            input.name = fieldName;
            input.style.width = '100%';
            input.style.padding = '0.5rem';
            input.style.border = '1px solid var(--border)';
            input.style.borderRadius = '6px';
            
            // Add empty option
            const emptyOption = document.createElement('option');
            emptyOption.value = '';
            emptyOption.textContent = '-- Select --';
            input.appendChild(emptyOption);
            
            // Add options
            options.forEach((option) => {
                const optionEl = document.createElement('option');
                optionEl.value = option;
                optionEl.textContent = option;
                if (fieldValue === option) {
                    optionEl.selected = true;
                }
                input.appendChild(optionEl);
            });
        } else {
            // Text input
            input = document.createElement('input');
            input.type = 'text';
            input.id = `field_${fieldName}`;
            input.name = fieldName;
            input.value = fieldValue;
            input.style.width = '100%';
            input.style.padding = '0.5rem';
            input.style.border = '1px solid var(--border)';
            input.style.borderRadius = '6px';
        }
        
        if (isRequired) {
            input.required = true;
        }
        
        fieldDiv.appendChild(input);
        fieldsList.appendChild(fieldDiv);
    });
    
    // Show submit button
    if (submitBtn) {
        submitBtn.style.display = 'block';
    }
    
    if (DEBUG) hudLog(`Rendered ${fieldCount} fields`);
}

// Expose renderFields globally
window.renderFields = renderFields;

