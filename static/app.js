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
if (!DEBUG) {
    document.addEventListener('DOMContentLoaded', () => {
        const debugPanel = document.getElementById('debug-panel');
        const analyzeDebug = document.getElementById('analyze-debug');
        if (debugPanel) debugPanel.style.display = 'none';
        if (analyzeDebug) analyzeDebug.style.display = 'none';
    });
}

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
async function updateAuthUI() {
    const authLoggedOut = document.getElementById('auth-logged-out');
    const authLoggedIn = document.getElementById('auth-logged-in');
    const userEmailEl = document.getElementById('user-email');
    const userPill = document.getElementById('user-pill');
    const userDropdown = document.getElementById('user-dropdown');
    
    try {
        const response = await fetch('/api/me', { credentials: 'include' });
        if (response.ok) {
            const data = await response.json();
            if (data.authenticated) {
                // Show logged in UI
                if (authLoggedOut) authLoggedOut.style.display = 'none';
                if (authLoggedIn) authLoggedIn.style.display = 'flex';
                if (userEmailEl) userEmailEl.textContent = data.email || '';
                if (urlParams.get('debug') === '1') hudLog(`Auth: authenticated as ${data.email}`);
            } else {
                // Show logged out UI
                if (authLoggedOut) authLoggedOut.style.display = 'block';
                if (authLoggedIn) authLoggedIn.style.display = 'none';
                if (userDropdown) userDropdown.classList.remove('open');
                if (userPill) userPill.classList.remove('open');
                if (urlParams.get('debug') === '1') hudLog('Auth: not authenticated');
            }
        } else {
            // Not authenticated
            if (authLoggedOut) authLoggedOut.style.display = 'block';
            if (authLoggedIn) authLoggedIn.style.display = 'none';
            if (userDropdown) userDropdown.classList.remove('open');
            if (userPill) userPill.classList.remove('open');
            if (urlParams.get('debug') === '1') hudLog('Auth: not authenticated (error)');
        }
    } catch (err) {
        if (urlParams.get('debug') === '1') hudLog(`Auth check error: ${err.message}`);
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
                if (urlParams.get('debug') === '1') hudLog(`ERROR: ${err.message}`);
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
                    if (urlParams.get('debug') === '1') hudLog(`ERROR: Analyze failed: ${response.status}`);
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
                    if (urlParams.get('debug') === '1') hudLog(`ERROR: Failed to parse response: ${parseErr.message}`);
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
                if (urlParams.get('debug') === '1') hudLog(`ERROR: ${err.message}`);
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
                if (urlParams.get('debug') === '1') hudLog(`ERROR: ${err.message}`);
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
    
    // Fullscreen button
    const fullscreenBtn = document.getElementById('fullscreen-btn');
    const previewContainerEl = document.getElementById('preview-container');
    const previewIframeEl = document.getElementById('preview-iframe');
    if (fullscreenBtn) {
        fullscreenBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (DEBUG) hudLog('Fullscreen clicked');
            
            try {
                // Try preview wrapper first, then container, then iframe
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
                    showToast('Failed to enter fullscreen', 'error');
                }
                if (DEBUG) hudLog(`Fullscreen error: ${err.message}`);
            }
        });
        if (DEBUG) hudLog('Fullscreen button handler attached');
    }
    
    if (DEBUG) hudLog('All handlers attached');
});

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

