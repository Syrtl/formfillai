// Minimal frontend wiring - Sign In, Magic Link, Analyze PDF
// HUD (Heads-Up Display) for debugging without DevTools

// Create HUD element
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
`;
document.body.appendChild(hud);

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

// Show HUD on load
hudLog('HUD: JS loaded');

// Capturing click listener to diagnose overlay issues
document.addEventListener('click', (e) => {
    const target = e.target;
    const targetInfo = `${target.tagName}${target.id ? '#' + target.id : ''}${target.className ? '.' + String(target.className).trim().replace(/\s+/g, '.') : ''}`;
    const topEl = document.elementFromPoint(e.clientX, e.clientY);
    const topElInfo = topEl ? `${topEl.tagName}${topEl.id ? '#' + topEl.id : ''}${topEl.className ? '.' + String(topEl.className).trim().replace(/\s+/g, '.') : ''}` : 'none';
    
    hudLog(`Clicked: ${targetInfo} -> Top: ${topElInfo}`);
    
    // If clicks reach document but not the button, there's an overlay
    if (target !== topEl) {
        hudLog(`WARNING: Click intercepted! Target: ${targetInfo}, Top: ${topElInfo}`);
    }
}, true); // capture phase

// Wait for DOM
document.addEventListener('DOMContentLoaded', () => {
    hudLog('DOMContentLoaded fired');
    
    // Get required elements
    const signInBtn = document.getElementById('signInBtn');
    const signInModal = document.getElementById('signInModal');
    const signInEmailInput = document.getElementById('signInEmail');
    const sendMagicBtn = document.getElementById('sendMagicBtn');
    const analyzeBtn = document.getElementById('analyzeBtn');
    const pdfFileInput = document.getElementById('pdfFileInput');
    
    // Check for missing elements
    if (!signInBtn) hudLog('ERROR: Missing element: signInBtn');
    if (!signInModal) hudLog('ERROR: Missing element: signInModal');
    if (!signInEmailInput) hudLog('ERROR: Missing element: signInEmail');
    if (!sendMagicBtn) hudLog('ERROR: Missing element: sendMagicBtn');
    if (!analyzeBtn) hudLog('ERROR: Missing element: analyzeBtn');
    if (!pdfFileInput) hudLog('ERROR: Missing element: pdfFileInput');
    
    // Sign In button -> open modal
    if (signInBtn && signInModal && signInEmailInput) {
        signInBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            hudLog('Sign In clicked');
            try {
                signInModal.hidden = false;
                signInEmailInput.focus();
                hudLog('Modal opened');
            } catch (err) {
                hudLog(`ERROR opening modal: ${err.message}`);
            }
        });
        hudLog('Sign In handler attached');
    }
    
    // Close modal handlers
    const closeSignInBtn = document.getElementById('closeSignInBtn');
    if (closeSignInBtn && signInModal) {
        closeSignInBtn.addEventListener('click', () => {
            signInModal.hidden = true;
            hudLog('Modal closed');
        });
    }
    
    // Close modal on outside click
    if (signInModal) {
        signInModal.addEventListener('click', (e) => {
            if (e.target === signInModal) {
                signInModal.hidden = true;
                hudLog('Modal closed (outside click)');
            }
        });
    }
    
    // Send magic link button -> POST /auth/send-magic-link
    if (sendMagicBtn && signInEmailInput) {
        sendMagicBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            e.stopPropagation();
            hudLog('Send magic link clicked');
            
            const email = signInEmailInput.value.trim();
            if (!email) {
                hudLog('ERROR: Email empty');
                return;
            }
            
            sendMagicBtn.disabled = true;
            sendMagicBtn.textContent = 'Sending...';
            
            try {
                const formData = new FormData();
                formData.append('email', email);
                
                hudLog(`POST /auth/send-magic-link (email: ${email})`);
                const response = await fetch('/auth/send-magic-link', {
                    method: 'POST',
                    body: formData,
                    credentials: 'include'
                });
                
                const responseText = await response.text();
                const responsePreview = responseText.substring(0, 120);
                hudLog(`POST /auth/send-magic-link -> status ${response.status} + ${responsePreview}`);
                
                if (response.ok) {
                    hudLog('Magic link sent successfully');
                    if (typeof showToast === 'function') {
                        showToast('Check your email for the magic link', 'success');
                    }
                } else {
                    hudLog(`ERROR: Magic link send failed: ${response.status}`);
                    if (typeof showToast === 'function') {
                        showToast('Failed to send magic link', 'error');
                    }
                }
            } catch (err) {
                hudLog(`ERROR: ${err.message}`);
                if (typeof showToast === 'function') {
                    showToast('Failed to send magic link', 'error');
                }
            } finally {
                sendMagicBtn.disabled = false;
                sendMagicBtn.textContent = 'Send magic link';
            }
        });
        hudLog('Send magic link handler attached');
    }
    
    // Analyze PDF button -> POST /fields
    if (analyzeBtn && pdfFileInput) {
        analyzeBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            e.stopPropagation();
            hudLog('Analyze clicked');
            
            const file = pdfFileInput.files[0];
            if (!file) {
                hudLog('ERROR: No file selected');
                if (typeof showToast === 'function') {
                    showToast('Please select a PDF file first', 'error');
                }
                return;
            }
            
            // Immediately show feedback
            hudLog(`POST /fields (file: ${file.name}, size: ${file.size})`);
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
                const responsePreview = responseText.substring(0, 120);
                hudLog(`POST /fields -> status ${response.status} + ${responsePreview}`);
                
                if (response.status === 401) {
                    hudLog('ERROR: Not signed in (401)');
                    if (typeof showToast === 'function') {
                        showToast('Please sign in first', 'error');
                    }
                    return;
                }
                
                if (!response.ok) {
                    hudLog(`ERROR: Analyze failed: ${response.status}`);
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
                    hudLog(`ERROR: Failed to parse response: ${parseErr.message}`);
                    return;
                }
                
                const fields = responseData.fields || [];
                const fieldCount = fields.length;
                hudLog(`Success: Fields found: ${fieldCount}`);
                
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
                        previewContainer.hidden = false;
                        hudLog(`Preview iframe set: ${previewUrl}`);
                        
                        // Fallback link
                        if (previewLink) {
                            previewLink.href = responseData.preview_url;
                            previewLink.textContent = 'Open preview in new tab';
                        }
                    } else {
                        hudLog('WARNING: Preview elements not found');
                    }
                }
                
                // Render fields if renderFields function exists
                if (typeof renderFields === 'function') {
                    renderFields(fields);
                    hudLog('Fields rendered');
                } else {
                    hudLog('WARNING: renderFields function not found');
                }
                
            } catch (err) {
                hudLog(`ERROR: ${err.message}`);
                if (typeof showToast === 'function') {
                    showToast('Failed to analyze PDF', 'error');
                }
            } finally {
                analyzeBtn.disabled = false;
                analyzeBtn.textContent = 'Analyze PDF';
            }
        });
        hudLog('Analyze PDF handler attached');
    }
    
    hudLog('All handlers attached');
});

