// i18n module for client-side translations
import { LANGUAGES, getLanguageByCode, normalizeLanguageCode } from './languages.js';

const DEFAULT_LOCALE = 'en';
const TRANSLATIONS_CACHE = {};
let currentLocale = DEFAULT_LOCALE;
let fallbackTranslations = null;

/**
 * Detect user's preferred language from browser
 */
export function detectLocale() {
    // Check localStorage first (user preference)
    try {
        const saved = localStorage.getItem('ffai_locale');
        if (saved && getLanguageByCode(saved)) {
            return saved;
        }
    } catch (e) {
        // localStorage not available
    }
    
    // Check navigator.language
    if (typeof navigator !== 'undefined' && navigator.language) {
        const detected = normalizeLanguageCode(navigator.language);
        if (detected !== DEFAULT_LOCALE) {
            return detected;
        }
    }
    
    // Check Accept-Language header (if available via meta tag or server)
    const metaLang = document.querySelector('meta[http-equiv="content-language"]');
    if (metaLang && metaLang.content) {
        const detected = normalizeLanguageCode(metaLang.content);
        if (detected !== DEFAULT_LOCALE) {
            return detected;
        }
    }
    
    return DEFAULT_LOCALE;
}

/**
 * Set current locale and persist to localStorage
 */
export function setLocale(locale) {
    const normalized = normalizeLanguageCode(locale);
    if (!getLanguageByCode(normalized)) {
        console.warn(`Locale ${locale} not supported, falling back to ${DEFAULT_LOCALE}`);
        currentLocale = DEFAULT_LOCALE;
    } else {
        currentLocale = normalized;
    }
    
    try {
        localStorage.setItem('ffai_locale', currentLocale);
    } catch (e) {
        console.warn('Failed to save locale to localStorage:', e);
    }
    
    return currentLocale;
}

/**
 * Load translations for a locale
 */
export async function loadTranslations(locale) {
    const normalized = normalizeLanguageCode(locale);
    
    // Check cache first
    if (TRANSLATIONS_CACHE[normalized]) {
        return TRANSLATIONS_CACHE[normalized];
    }
    
    try {
        const response = await fetch(`/static/i18n/${normalized}.json`);
        if (!response.ok) {
            throw new Error(`Failed to load ${normalized}.json: ${response.status}`);
        }
        const translations = await response.json();
        TRANSLATIONS_CACHE[normalized] = translations;
        return translations;
    } catch (error) {
        console.warn(`Failed to load translations for ${normalized}:`, error);
        
        // Load English as fallback
        if (normalized !== DEFAULT_LOCALE) {
            if (!fallbackTranslations) {
                try {
                    const fallbackResponse = await fetch(`/static/i18n/${DEFAULT_LOCALE}.json`);
                    if (fallbackResponse.ok) {
                        fallbackTranslations = await fallbackResponse.json();
                    }
                } catch (e) {
                    console.error('Failed to load fallback translations:', e);
                }
            }
            return fallbackTranslations || {};
        }
        
        return {};
    }
}

/**
 * Get translation for a key with optional parameters
 */
export function t(key, params = {}) {
    const translations = TRANSLATIONS_CACHE[currentLocale] || {};
    const fallback = TRANSLATIONS_CACHE[DEFAULT_LOCALE] || fallbackTranslations || {};
    
    // Try current locale first, then fallback to English
    let text = translations[key] || fallback[key] || key;
    
    // Replace placeholders like {count}, {filename}, etc.
    if (typeof text === 'string') {
        for (const [param, value] of Object.entries(params)) {
            text = text.replace(new RegExp(`\\{${param}\\}`, 'g'), String(value));
        }
    }
    
    return text;
}

/**
 * Initialize i18n system
 */
export async function initI18n(initialLocale = null) {
    // Detect or use provided locale
    const locale = initialLocale || detectLocale();
    setLocale(locale);
    
    // Load translations for current locale and English fallback
    await Promise.all([
        loadTranslations(currentLocale),
        currentLocale !== DEFAULT_LOCALE ? loadTranslations(DEFAULT_LOCALE) : Promise.resolve(null)
    ]);
    
    return currentLocale;
}

/**
 * Update all elements with data-i18n attribute
 */
export function updatePageTranslations() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        if (!key) return;
        
        const translation = t(key);
        if (translation && translation !== key) {
            if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
                // Handle placeholder separately
                const placeholderKey = el.getAttribute('data-i18n-placeholder');
                if (placeholderKey) {
                    el.placeholder = t(placeholderKey);
                }
            } else if (el.hasAttribute('title')) {
                el.title = translation;
            } else {
                el.textContent = translation;
            }
        }
    });
    
    // Update placeholder attributes
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        const key = el.getAttribute('data-i18n-placeholder');
        if (key) {
            el.placeholder = t(key);
        }
    });
}

// Export current locale getter
export function getCurrentLocale() {
    return currentLocale;
}

// Export available languages
export { LANGUAGES, getLanguageByCode };

