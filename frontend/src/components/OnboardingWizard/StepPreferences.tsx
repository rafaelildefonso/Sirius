import { Globe, Sun, Bell, Type } from 'lucide-react';
import type { ThemeMode, Language } from '../../lib/store';

interface StepPreferencesProps {
  language: Language;
  theme: ThemeMode;
  notifications: boolean;
  fontSize: 'small' | 'default' | 'large';
  onLanguageChange: (lang: Language) => void;
  onThemeChange: (theme: ThemeMode) => void;
  onNotificationsChange: (val: boolean) => void;
  onFontSizeChange: (size: 'small' | 'default' | 'large') => void;
}

const LANGUAGES: { id: Language; label: string; flag: string }[] = [
  { id: 'pt', label: 'Português', flag: '🇧🇷' },
  { id: 'en', label: 'English', flag: '🇺🇸' },
  { id: 'es', label: 'Español', flag: '🇪🇸' },
];

const THEMES: { id: ThemeMode; label: string }[] = [
  { id: 'light', label: 'Claro' },
  { id: 'dark', label: 'Escuro' },
  { id: 'system', label: 'Sistema' },
];

const FONT_SIZES: { id: 'small' | 'default' | 'large'; label: string }[] = [
  { id: 'small', label: 'Pequena' },
  { id: 'default', label: 'Padrão' },
  { id: 'large', label: 'Grande' },
];

export function StepPreferences({
  language,
  theme,
  notifications,
  fontSize,
  onLanguageChange,
  onThemeChange,
  onNotificationsChange,
  onFontSizeChange,
}: StepPreferencesProps) {
  return (
    <div className="py-4">
      <h2 className="text-xl font-bold mb-2 text-center" style={{ color: 'var(--color-text)' }}>
        Preferências
      </h2>
      <p className="text-sm text-center mb-6" style={{ color: 'var(--color-text-secondary)' }}>
        Ajuste as configurações gerais do sistema
      </p>

      <div className="space-y-6">
        {/* Idioma */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <Globe size={16} style={{ color: 'var(--color-accent)' }} />
            <label className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
              Idioma
            </label>
          </div>
          <div className="grid grid-cols-3 gap-2">
            {LANGUAGES.map((lang) => (
              <button
                key={lang.id}
                onClick={() => onLanguageChange(lang.id)}
                className="px-3 py-2 rounded-lg text-sm transition-all"
                style={{
                  background: language === lang.id ? 'var(--color-accent)' : 'var(--color-bg)',
                  color: language === lang.id ? 'var(--color-on-accent)' : 'var(--color-text)',
                  border: `1px solid ${language === lang.id ? 'var(--color-accent)' : 'var(--color-border)'}`,
                }}
              >
                <span className="mr-1">{lang.flag}</span>
                {lang.label}
              </button>
            ))}
          </div>
        </div>

        {/* Tema */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <Sun size={16} style={{ color: 'var(--color-accent)' }} />
            <label className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
              Tema
            </label>
          </div>
          <div className="grid grid-cols-3 gap-2">
            {THEMES.map((t) => (
              <button
                key={t.id}
                onClick={() => onThemeChange(t.id)}
                className="px-3 py-2 rounded-lg text-sm transition-all"
                style={{
                  background: theme === t.id ? 'var(--color-accent)' : 'var(--color-bg)',
                  color: theme === t.id ? 'var(--color-on-accent)' : 'var(--color-text)',
                  border: `1px solid ${theme === t.id ? 'var(--color-accent)' : 'var(--color-border)'}`,
                }}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {/* Tamanho da fonte */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <Type size={16} style={{ color: 'var(--color-accent)' }} />
            <label className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
              Tamanho da Fonte
            </label>
          </div>
          <div className="grid grid-cols-3 gap-2">
            {FONT_SIZES.map((size) => (
              <button
                key={size.id}
                onClick={() => onFontSizeChange(size.id)}
                className="px-3 py-2 rounded-lg text-sm transition-all"
                style={{
                  background: fontSize === size.id ? 'var(--color-accent)' : 'var(--color-bg)',
                  color: fontSize === size.id ? 'var(--color-on-accent)' : 'var(--color-text)',
                  border: `1px solid ${fontSize === size.id ? 'var(--color-accent)' : 'var(--color-border)'}`,
                  fontSize: size.id === 'small' ? '12px' : size.id === 'large' ? '16px' : '14px',
                }}
              >
                {size.label}
              </button>
            ))}
          </div>
        </div>

        {/* Notificações */}
        <div>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Bell size={16} style={{ color: 'var(--color-accent)' }} />
              <label className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                Notificações
              </label>
            </div>
            <button
              onClick={() => onNotificationsChange(!notifications)}
              className="relative w-12 h-6 rounded-full transition-colors"
              style={{
                background: notifications ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
              }}
            >
              <span
                className="absolute top-1 w-4 h-4 rounded-full bg-white transition-all"
                style={{
                  left: notifications ? 'calc(100% - 1.25rem)' : '0.25rem',
                }}
              />
            </button>
          </div>
          <p className="text-xs mt-1 ml-6" style={{ color: 'var(--color-text-secondary)' }}>
            Receber alertas sobre tarefas e atualizações importantes
          </p>
        </div>
      </div>
    </div>
  );
}
