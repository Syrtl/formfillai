// Language metadata: code, nativeName, flag emoji, English name, popularity order
export const LANGUAGES = [
    { code: 'en', nativeName: 'English', flag: '🇬🇧', englishName: 'English', order: 0 },
    { code: 'de', nativeName: 'Deutsch', flag: '🇩🇪', englishName: 'German', order: 1 },
    { code: 'fr', nativeName: 'Français', flag: '🇫🇷', englishName: 'French', order: 2 },
    { code: 'it', nativeName: 'Italiano', flag: '🇮🇹', englishName: 'Italian', order: 3 },
    { code: 'es', nativeName: 'Español', flag: '🇪🇸', englishName: 'Spanish', order: 4 },
    { code: 'pl', nativeName: 'Polski', flag: '🇵🇱', englishName: 'Polish', order: 5 },
    { code: 'ro', nativeName: 'Română', flag: '🇷🇴', englishName: 'Romanian', order: 6 },
    { code: 'nl', nativeName: 'Nederlands', flag: '🇳🇱', englishName: 'Dutch', order: 7 },
    { code: 'cs', nativeName: 'Čeština', flag: '🇨🇿', englishName: 'Czech', order: 8 },
    { code: 'el', nativeName: 'Ελληνικά', flag: '🇬🇷', englishName: 'Greek', order: 9 },
    { code: 'hu', nativeName: 'Magyar', flag: '🇭🇺', englishName: 'Hungarian', order: 10 },
    { code: 'pt', nativeName: 'Português', flag: '🇵🇹', englishName: 'Portuguese', order: 11 },
    { code: 'sv', nativeName: 'Svenska', flag: '🇸🇪', englishName: 'Swedish', order: 12 },
    { code: 'da', nativeName: 'Dansk', flag: '🇩🇰', englishName: 'Danish', order: 13 },
    { code: 'fi', nativeName: 'Suomi', flag: '🇫🇮', englishName: 'Finnish', order: 14 },
    { code: 'sk', nativeName: 'Slovenčina', flag: '🇸🇰', englishName: 'Slovak', order: 15 },
    { code: 'bg', nativeName: 'Български', flag: '🇧🇬', englishName: 'Bulgarian', order: 16 },
    { code: 'hr', nativeName: 'Hrvatski', flag: '🇭🇷', englishName: 'Croatian', order: 17 },
    { code: 'sl', nativeName: 'Slovenščina', flag: '🇸🇮', englishName: 'Slovenian', order: 18 },
    { code: 'lt', nativeName: 'Lietuvių', flag: '🇱🇹', englishName: 'Lithuanian', order: 19 },
    { code: 'lv', nativeName: 'Latviešu', flag: '🇱🇻', englishName: 'Latvian', order: 20 },
    { code: 'et', nativeName: 'Eesti', flag: '🇪🇪', englishName: 'Estonian', order: 21 },
    { code: 'ga', nativeName: 'Gaeilge', flag: '🇮🇪', englishName: 'Irish', order: 22 },
    { code: 'mt', nativeName: 'Malti', flag: '🇲🇹', englishName: 'Maltese', order: 23 },
    { code: 'ru', nativeName: 'Русский', flag: '🇷🇺', englishName: 'Russian', order: 24 },
    { code: 'uk', nativeName: 'Українська', flag: '🇺🇦', englishName: 'Ukrainian', order: 25 },
];

export function getLanguageByCode(code) {
    return LANGUAGES.find(lang => lang.code === code);
}

export function normalizeLanguageCode(lang) {
    if (!lang) return 'en';
    const normalized = lang.toLowerCase().split('-')[0].split('_')[0];
    return LANGUAGES.find(l => l.code === normalized) ? normalized : 'en';
}

